"""
CLOUD STANDBY WORKER — the always-on backup brain.

Deploy this file (plus the small requirements set) to any always-on Linux host
(VPS, Railway, Fly.io, Oracle Always-Free VM, ...). It answers your phone chat
even when this Windows PC is switched off or asleep.

How it stays out of the way:
  * The Windows worker heartbeats into the `devices` table (id = DEVICE_ID)
    every ~5s. This worker watches that heartbeat: while it is fresh, it stays
    quiet and lets the PC worker do everything (apps, files, PowerShell, ...).
  * When the heartbeat goes stale (PC off), it claims the queued inbox jobs and
    replies using cloud tools ONLY: the cloud LLM (Groq) + web search +
    persistent memory + goals. PC-only tools are disabled, so nothing ever runs
    on the wrong machine.
  * It NEVER writes a heartbeat, so the web UI keeps showing the true PC status.

Running:
  python cloud_worker.py            # stay alive, poll forever (for a VPS / systemd)
  python cloud_worker.py --once     # process at most one job, then exit (cron-style hosts)

Requires cloud LLM env vars, e.g. LLM_PROVIDER=groq + GROQ_API_KEY + LLM_MODEL.
"""

import os
import sys
import time
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv

from agent import Session
from constants import DEFAULT_DEVICE_ID
from db import (
    claim_inbox,
    complete_inbox,
    ensure_default_session,
    get_conn,
    insert_assistant_message,
    load_memories,
)
from poller import build_extra_fns, persist_session, restore_session

load_dotenv()

# ─── Configuration ────────────────────────────────────────────────────────────

POLL_SECONDS          = float(os.environ.get("CLOUD_POLL_SECONDS", "2"))
TAKEOVER_AFTER_SECONDS = float(os.environ.get("CLOUD_TAKEOVER_SECONDS", "25"))
# A 'processing' row older than this is treated as orphaned (the worker that
# claimed it crashed), so the standby can recover instead of waiting forever.
MAX_JOB_AGE_SECONDS    = float(os.environ.get("CLOUD_MAX_JOB_AGE_SECONDS", "180"))
PC_DEVICE_ID          = os.environ.get("DEVICE_ID") or DEFAULT_DEVICE_ID

# Tools the cloud standby is allowed to use. Everything that touches the PC is
# deliberately excluded so it can never act on the wrong machine.
CLOUD_TOOLS = {
    "remember", "recall", "forget",
    "schedule_goal", "list_goals", "cancel_goal", "complete_goal",
    "web_search", "read_webpage",
}

REPLY_PREFIX = "☁️ (Windows PC offline \u2014 answered from cloud)\n\n"

CLOUD_MODE_HINT = """

[CURRENT MODE: CLOUD STANDBY \u2014 the user's Windows PC is currently OFFLINE.]
- You are answering from a cloud backup host. PC capabilities are NOT available
  right now: no files, apps, processes, PowerShell, or system_info.
- You still have web_search, read_webpage, your persistent memory, and goals.
- If the user asks for something that needs the PC, tell them clearly that it
  can't run until the PC is powered on, keep the request in mind, and offer
  whatever you can do right now (research, recall, planning)."""


# ─── Heartbeat helpers ────────────────────────────────────────────────────────

def pc_device_age(conn) -> float | None:
    """Seconds since the Windows PC last heartbeated. None if never seen."""
    row = conn.execute(
        "SELECT last_seen_at FROM devices WHERE id = %s",
        (PC_DEVICE_ID,),
    ).fetchone()
    if row is None or row["last_seen_at"] is None:
        return None
    return (datetime.now(timezone.utc) - row["last_seen_at"]).total_seconds()


def any_job_processing(conn) -> bool:
    """True if a worker is actively handling a job (recent 'processing' row).

    Old 'processing' rows are orphaned (crashed worker) and ignored so a stuck
    row can never permanently disable the standby.
    """
    row = conn.execute(
        "SELECT 1 FROM inbox WHERE status = 'processing'"
        " AND created_at > now() - make_interval(secs => %s) LIMIT 1",
        (MAX_JOB_AGE_SECONDS,),
    ).fetchone()
    return row is not None


# ─── Job processing ───────────────────────────────────────────────────────────

def process_job(conn, session_cache: dict, job) -> None:
    session_id = str(job["session_id"])
    session = session_cache.get(session_id)
    if session is None:
        session = Session()
        session.enabled_tools = set(CLOUD_TOOLS)
        session.system_extra = CLOUD_MODE_HINT
        session_cache[session_id] = session
    restore_session(conn, session, session_id)

    # Refresh tool closures so they use the current connection.
    session._extra_fns = build_extra_fns(conn, session_id)

    mems = load_memories(conn, session_id)
    if mems and not session.messages:
        mem_lines = "\n".join(f"  [{r['category']}] {r['key']}: {r['content']}" for r in mems)
        user_text = f"[Recalled memories]\n{mem_lines}\n\n{job['body']}"
    else:
        user_text = job["body"]

    reply = session.handle_user_message(user_text)
    persist_session(conn, session, session_id)
    insert_assistant_message(conn, session_id, f"{REPLY_PREFIX}{reply}")
    complete_inbox(conn, job["id"], ok=True)
    conn.commit()
    print(f"[cloud] answered inbox {job['id']} for session {session_id}")


# ─── Main loop ────────────────────────────────────────────────────────────────

def run_once(conn, session_cache: dict) -> bool:
    """Try to handle one queued job. Returns True when it did."""
    age = pc_device_age(conn)
    if age is not None and age <= TAKEOVER_AFTER_SECONDS:
        return False  # PC heartbeating — it owns the inbox
    if any_job_processing(conn):
        conn.rollback()
        return False  # another worker is mid-job; don't race it
    job = claim_inbox(conn)
    if not job:
        conn.rollback()
        return False
    print(f"[cloud] claimed inbox {job['id']} (PC last seen "
          f"{'never' if age is None else f'{age:.0f}s'} ago)")
    try:
        process_job(conn, session_cache, job)
    except Exception:
        traceback.print_exc()
        try:
            complete_inbox(conn, job["id"], ok=False)
            insert_assistant_message(
                conn,
                str(job["session_id"]),
                f"{REPLY_PREFIX}Cloud standby worker hit an error handling that message. "
                "Check the cloud worker log.",
            )
            conn.commit()
        except Exception:
            conn.rollback()
            traceback.print_exc()
    return True


def main():
    once = "--once" in sys.argv[1:]

    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("Set DATABASE_URL in your .env file (Neon connection string).")
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        raise RuntimeError(
            "The cloud standby worker needs a cloud LLM. Set LLM_PROVIDER=groq "
            "(or openai) with its API key — local Ollama does not exist in the cloud."
        )

    print(f"Cloud standby worker started ({provider}, model={os.environ.get('LLM_MODEL', '?')}). "
          f"Will take over only when {PC_DEVICE_ID} goes quiet for >{TAKEOVER_AFTER_SECONDS:.0f}s.")
    session_cache: dict[str, Session] = {}

    while True:
        try:
            with get_conn() as conn:
                ensure_default_session(conn)
                did = run_once(conn, session_cache)
                if once and did:
                    print("[cloud] --once done, exiting.")
                    break
        except KeyboardInterrupt:
            print("Stopping cloud worker.")
            break
        except Exception:
            traceback.print_exc()
            print("Connection lost; retrying in 3s...")
            time.sleep(3)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()