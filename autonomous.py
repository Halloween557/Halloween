"""
Autonomous agent brain — goal management, cron scheduling,
condition evaluation, and the self-reflection loop.

Every AUTONOMOUS_INTERVAL_SECONDS the run_autonomous_cycle() function
is called from poller.py's main loop. It:
  1. Fires any goals whose next_run_at is in the past.
  2. Evaluates condition-based goals (PowerShell condition returns truthy).
  3. Runs a self-reflection turn every REFLECTION_INTERVAL_SECONDS.
  4. Runs the system watchdog (CPU / RAM / Disk spike alerts).
"""

import os
import re
import subprocess
import time
import traceback
from datetime import datetime, timezone
from typing import Any

from croniter import croniter  # pip install croniter

from db import get_conn
from constants import DEFAULT_SESSION_ID


# ─── Configuration ──────────────────────────────────────────────────────────

WATCHDOG_CPU_THRESHOLD    = float(os.environ.get("WATCHDOG_CPU",  "90"))   # %
WATCHDOG_RAM_THRESHOLD    = float(os.environ.get("WATCHDOG_RAM",  "92"))   # %
WATCHDOG_DISK_THRESHOLD   = float(os.environ.get("WATCHDOG_DISK", "95"))   # %
REFLECTION_INTERVAL_SECS  = int(os.environ.get("REFLECTION_INTERVAL", str(30 * 60)))  # 30 min
WATCHDOG_INTERVAL_SECS    = int(os.environ.get("WATCHDOG_INTERVAL", "60"))


# ─── DB Helpers ─────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def list_active_goals(conn, session_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, title, description, cron_expr, condition_ps,
               last_run_at, next_run_at, run_count, priority
        FROM agent_goals
        WHERE session_id = %s AND status = 'active'
        ORDER BY priority DESC, next_run_at ASC NULLS FIRST
        """,
        (session_id,),
    ).fetchall()
    return list(rows)


def get_goal(conn, goal_id: str, session_id: str) -> dict | None:
    return conn.execute(
        "SELECT * FROM agent_goals WHERE id = %s AND session_id = %s",
        (goal_id, session_id),
    ).fetchone()


def upsert_goal(conn, session_id: str, title: str, description: str,
                cron_expr: str | None = None, condition_ps: str | None = None,
                priority: int = 5) -> str:
    """Insert a new goal and return its UUID."""
    next_run = _compute_next_run(cron_expr)
    row = conn.execute(
        """
        INSERT INTO agent_goals
            (session_id, title, description, cron_expr, condition_ps, priority, next_run_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (session_id, title, description, cron_expr, condition_ps, priority, next_run),
    ).fetchone()
    conn.commit()
    return str(row["id"])


def update_goal_status(conn, goal_id: str, status: str):
    conn.execute(
        "UPDATE agent_goals SET status = %s, updated_at = now() WHERE id = %s",
        (status, goal_id),
    )
    conn.commit()


def mark_goal_ran(conn, goal_id: str, cron_expr: str | None):
    next_run = _compute_next_run(cron_expr)
    conn.execute(
        """
        UPDATE agent_goals
        SET last_run_at = now(),
            next_run_at = %s,
            run_count   = run_count + 1,
            updated_at  = now()
        WHERE id = %s
        """,
        (next_run, goal_id),
    )
    conn.commit()


def log_autonomous_run(conn, session_id: str, trigger_type: str, prompt: str,
                       reply: str, success: bool = True,
                       duration_ms: int | None = None,
                       goal_id: str | None = None):
    conn.execute(
        """
        INSERT INTO autonomous_log
            (session_id, goal_id, trigger_type, prompt, reply, success, duration_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (session_id, goal_id, trigger_type, prompt, reply, success, duration_ms),
    )
    conn.commit()


def get_autonomous_log(conn, session_id: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT al.id, al.trigger_type, al.prompt, al.reply, al.success,
               al.duration_ms, al.created_at, ag.title AS goal_title
        FROM autonomous_log al
        LEFT JOIN agent_goals ag ON ag.id = al.goal_id
        WHERE al.session_id = %s
        ORDER BY al.created_at DESC
        LIMIT %s
        """,
        (session_id, limit),
    ).fetchall()
    return list(rows)


# ─── Cron Helpers ───────────────────────────────────────────────────────────

def _compute_next_run(cron_expr: str | None) -> datetime | None:
    if not cron_expr:
        return None
    try:
        cron = croniter(cron_expr, _now_utc())
        return cron.get_next(datetime)
    except Exception:
        return None


def _goal_is_due(goal: dict) -> bool:
    """A goal is due if it has a cron schedule and next_run_at is in the past."""
    if not goal.get("cron_expr"):
        return False
    next_run = goal.get("next_run_at")
    if next_run is None:
        return True  # never ran yet — run it now
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    return _now_utc() >= next_run


# ─── Condition Evaluator ─────────────────────────────────────────────────────

def _eval_condition(condition_ps: str) -> bool:
    """
    Run a PowerShell one-liner and treat any truthy stdout as True.
    E.g. condition_ps = "(Get-PSDrive C).Free/1GB -lt 5"  → True when disk is nearly full.
    """
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", condition_ps],
            capture_output=True, text=True, timeout=15,
        )
        out = result.stdout.strip().lower()
        return out in ("true", "1", "yes")
    except Exception:
        return False


# ─── Autonomous Cycle State (module-level timestamps) ────────────────────────

_last_reflection: float = 0.0
_last_watchdog: float   = 0.0


# ─── Watchdog ────────────────────────────────────────────────────────────────

def _get_system_metrics() -> dict[str, float]:
    import psutil
    cpu  = psutil.cpu_percent(interval=1)
    ram  = psutil.virtual_memory().percent
    disk = psutil.disk_usage("C:\\").percent
    return {"cpu": cpu, "ram": ram, "disk": disk}


def _check_watchdog(run_session_fn, session_id: str, conn) -> bool:
    """Alert the user if CPU/RAM/Disk breach thresholds. Returns True if alert fired."""
    global _last_watchdog
    now = time.monotonic()
    if now - _last_watchdog < WATCHDOG_INTERVAL_SECS:
        return False
    _last_watchdog = now

    try:
        metrics = _get_system_metrics()
    except Exception:
        return False

    alerts = []
    if metrics["cpu"]  >= WATCHDOG_CPU_THRESHOLD:
        alerts.append(f"🔴 CPU usage critical: {metrics['cpu']:.0f}% (threshold: {WATCHDOG_CPU_THRESHOLD}%)")
    if metrics["ram"]  >= WATCHDOG_RAM_THRESHOLD:
        alerts.append(f"🔴 RAM usage critical: {metrics['ram']:.0f}% (threshold: {WATCHDOG_RAM_THRESHOLD}%)")
    if metrics["disk"] >= WATCHDOG_DISK_THRESHOLD:
        alerts.append(f"🔴 Disk C: usage critical: {metrics['disk']:.0f}% (threshold: {WATCHDOG_DISK_THRESHOLD}%)")

    if not alerts:
        return False

    alert_text = "\n".join(alerts)
    prompt = (
        f"[AUTONOMOUS WATCHDOG ALERT]\n{alert_text}\n\n"
        "Investigate and advise the user on what is consuming resources. "
        "Use list_processes and system_info to diagnose. Report findings concisely."
    )
    t0 = time.monotonic()
    reply = run_session_fn(prompt)
    duration_ms = int((time.monotonic() - t0) * 1000)
    log_autonomous_run(conn, session_id, "watchdog", prompt, reply,
                       success=True, duration_ms=duration_ms)
    return True


# ─── Self-Reflection ─────────────────────────────────────────────────────────

def _check_reflection(run_session_fn, session_id: str, conn) -> bool:
    """Periodic self-reflection: the agent reviews its state and acts proactively."""
    global _last_reflection
    now = time.monotonic()
    if now - _last_reflection < REFLECTION_INTERVAL_SECS:
        return False
    _last_reflection = now

    prompt = (
        "[AUTONOMOUS SELF-REFLECTION]\n"
        "You are about to perform a proactive self-reflection turn. "
        "Do the following:\n"
        "1. Recall all stored memories and review them for relevance.\n"
        "2. List your active goals from agent_goals (use recall with category='goal' or list_goals tool).\n"
        "3. Check current system health with system_info.\n"
        "4. If you notice anything worth proactively telling the user (low disk, stale memories, "
        "overdue goals, suggestions), write a brief, friendly summary. Otherwise say 'System healthy — "
        "no action needed.' Keep it short."
    )
    t0 = time.monotonic()
    reply = run_session_fn(prompt)
    duration_ms = int((time.monotonic() - t0) * 1000)
    log_autonomous_run(conn, session_id, "reflection", prompt, reply,
                       success=True, duration_ms=duration_ms)
    return True


# ─── Goal Runner ─────────────────────────────────────────────────────────────

def _run_goal(goal: dict, run_session_fn, session_id: str, conn) -> None:
    goal_id = str(goal["id"])
    title   = goal["title"]
    desc    = goal["description"]

    trigger_type = "condition" if goal.get("condition_ps") else "cron"
    prompt = (
        f"[AUTONOMOUS GOAL TRIGGERED: '{title}']\n"
        f"Goal description: {desc}\n\n"
        "Execute this goal now using your tools. Report the outcome concisely."
    )
    t0 = time.monotonic()
    try:
        reply = run_session_fn(prompt)
        success = True
    except Exception as e:
        reply = f"Error executing goal '{title}': {e}"
        success = False
        traceback.print_exc()

    duration_ms = int((time.monotonic() - t0) * 1000)
    log_autonomous_run(conn, session_id, trigger_type, prompt, reply,
                       success=success, duration_ms=duration_ms, goal_id=goal_id)
    mark_goal_ran(conn, goal_id, goal.get("cron_expr"))
    print(f"[autonomous] Goal '{title}' ran ({duration_ms}ms). success={success}")


# ─── Main Cycle ──────────────────────────────────────────────────────────────

def run_autonomous_cycle(run_session_fn, session_id: str, conn) -> None:
    """
    Call this periodically from the main poller loop.
    run_session_fn(prompt: str) -> str  — sends a prompt to the agent and returns reply.
    """
    try:
        # 1. Watchdog
        _check_watchdog(run_session_fn, session_id, conn)

        # 2. Self-Reflection
        _check_reflection(run_session_fn, session_id, conn)

        # 3. Goal evaluation
        goals = list_active_goals(conn, session_id)
        for goal in goals:
            should_run = False

            if goal.get("condition_ps"):
                should_run = _eval_condition(goal["condition_ps"])
            elif goal.get("cron_expr"):
                should_run = _goal_is_due(goal)

            if should_run:
                _run_goal(goal, run_session_fn, session_id, conn)

    except Exception:
        traceback.print_exc()


# ─── Tool helpers (called by tool closures injected from poller.py) ──────────

def _format_goal(g: dict) -> str:
    parts = [
        f"  [{g['id']}]",
        f"  Title:       {g['title']}",
        f"  Description: {g['description']}",
        f"  Priority:    {g['priority']}/10",
        f"  Cron:        {g.get('cron_expr') or '—'}",
        f"  Condition:   {g.get('condition_ps') or '—'}",
        f"  Runs:        {g.get('run_count', 0)}",
        f"  Next run:    {g.get('next_run_at') or 'soon'}",
    ]
    return "\n".join(parts)


def make_goal_tools(conn, session_id: str) -> dict:
    """Return goal management tool closures bound to the current DB connection."""

    def schedule_goal(title: str, description: str, cron: str | None = None,
                      condition_ps: str | None = None, priority: int = 5) -> str:
        goal_id = upsert_goal(conn, session_id, title, description,
                               cron_expr=cron, condition_ps=condition_ps, priority=priority)
        cron_info = f" | cron: '{cron}'" if cron else ""
        cond_info = f" | condition: '{condition_ps}'" if condition_ps else ""
        return (f"Goal '{title}' created (id={goal_id}){cron_info}{cond_info}. "
                "It will run autonomously when triggered.")

    def list_goals() -> str:
        goals = list_active_goals(conn, session_id)
        if not goals:
            return "No active goals. Use schedule_goal() to add one."
        return "\n\n".join(_format_goal(g) for g in goals)

    def cancel_goal(goal_id: str) -> str:
        g = get_goal(conn, goal_id, session_id)
        if not g:
            return f"Goal {goal_id} not found."
        update_goal_status(conn, goal_id, "cancelled")
        return f"Cancelled goal: {g['title']}"

    def complete_goal(goal_id: str) -> str:
        g = get_goal(conn, goal_id, session_id)
        if not g:
            return f"Goal {goal_id} not found."
        update_goal_status(conn, goal_id, "completed")
        return f"Marked goal as completed: {g['title']}"

    return {
        "schedule_goal": schedule_goal,
        "list_goals": list_goals,
        "cancel_goal": cancel_goal,
        "complete_goal": complete_goal,
    }
