"""
Windows worker: heartbeat + claim inbox jobs from Neon, run the local Session,
write the assistant reply back, AND run the autonomous cycle.
The PC only makes outbound connections to Neon.
"""

import os
import time
import traceback

from dotenv import load_dotenv

load_dotenv()

from agent import Session
from autonomous import run_autonomous_cycle, make_goal_tools
from constants import DEFAULT_SESSION_ID
from db import (
    claim_inbox,
    complete_inbox,
    delete_memory,
    ensure_default_session,
    get_conn,
    heartbeat,
    insert_assistant_message,
    load_agent_state,
    load_memories,
    save_agent_state,
    upsert_memory,
)

POLL_SECONDS          = float(os.environ.get("POLL_SECONDS", "1"))
MAX_POLL_SECONDS      = float(os.environ.get("MAX_POLL_SECONDS", "4"))
HEARTBEAT_SECONDS     = float(os.environ.get("HEARTBEAT_SECONDS", "5"))
AUTONOMOUS_INTERVAL   = float(os.environ.get("AUTONOMOUS_INTERVAL", "10"))  # how often to check for due goals


def restore_session(conn, session: Session, session_id: str) -> Session:
    messages, pending = load_agent_state(conn, session_id)
    session.import_state(messages, pending)
    return session


def persist_session(conn, session: Session, session_id: str):
    state = session.export_state()
    save_agent_state(conn, session_id, state["messages"], state["pending"])


def make_memory_tools(conn, session_id: str) -> dict:
    """Return closure-based memory tool functions bound to the given session."""

    def remember(key: str, content: str, category: str = "general") -> str:
        upsert_memory(conn, session_id, key, content, category)
        return f"Remembered [{category}] {key}: {content}"

    def recall(key: str | None = None, category: str | None = None) -> str:
        rows = load_memories(conn, session_id)
        if not rows:
            return "No memories stored yet."
        if key:
            for r in rows:
                if r["key"] == key:
                    return f"[{r['category']}] {r['key']}: {r['content']}"
            return f"No memory found for key: {key}"
        if category:
            rows = [r for r in rows if r["category"] == category]
            if not rows:
                return f"No memories in category: {category}"
        lines = [f"[{r['category']}] {r['key']}: {r['content']}" for r in rows]
        return "\n".join(lines)

    def forget(key: str) -> str:
        removed = delete_memory(conn, session_id, key)
        return f"Forgotten: {key}" if removed else f"No memory found for key: {key}"

    return {"remember": remember, "recall": recall, "forget": forget}


def build_extra_fns(conn, session_id: str) -> dict:
    """Combine memory tools + goal tools into one dict for Session._extra_fns."""
    fns = {}
    fns.update(make_memory_tools(conn, session_id))
    fns.update(make_goal_tools(conn, session_id))
    return fns


def process_job(conn, session_cache: dict, job) -> None:
    session_id = str(job["session_id"])
    session = session_cache.get(session_id)
    if session is None:
        session = Session()
        session_cache[session_id] = session
    restore_session(conn, session, session_id)

    # Always refresh tool closures so they use the current connection.
    session._extra_fns = build_extra_fns(conn, session_id)

    # Prepend stored memories as context on the first turn of each job.
    memories = load_memories(conn, session_id)
    if memories and not session.messages:
        mem_lines = "\n".join(
            f"  [{r['category']}] {r['key']}: {r['content']}" for r in memories
        )
        user_text = f"[Recalled memories]\n{mem_lines}\n\n{job['body']}"
    else:
        user_text = job["body"]

    reply = session.handle_user_message(user_text)
    persist_session(conn, session, session_id)
    insert_assistant_message(conn, session_id, reply)
    complete_inbox(conn, job["id"], ok=True)
    conn.commit()


def run_loop():
    session_cache: dict[str, Session] = {}
    last_heartbeat  = 0.0
    last_autonomous = 0.0
    current_poll    = POLL_SECONDS

    with get_conn() as conn:
        ensure_default_session(conn)

        # Pre-load the default session
        default_session = session_cache.setdefault(DEFAULT_SESSION_ID, Session())
        restore_session(conn, default_session, DEFAULT_SESSION_ID)

        # Build a run_session closure for the autonomous cycle that uses the
        # default session and persists state + posts the reply to the messages table.
        def _autonomous_run(prompt: str) -> str:
            sess = session_cache.get(DEFAULT_SESSION_ID)
            if sess is None:
                return "(session not found)"
            # Refresh extra fns (DB connection may have been recycled)
            sess._extra_fns = build_extra_fns(conn, DEFAULT_SESSION_ID)
            restore_session(conn, sess, DEFAULT_SESSION_ID)
            reply = sess.handle_user_message(prompt)
            persist_session(conn, sess, DEFAULT_SESSION_ID)
            # Post autonomous reply as assistant message so it appears in the chat UI
            insert_assistant_message(conn, DEFAULT_SESSION_ID, f"🤖 [Autonomous] {reply}")
            conn.commit()
            return reply

        while True:
            now = time.monotonic()

            # Heartbeat
            if now - last_heartbeat >= HEARTBEAT_SECONDS:
                heartbeat(conn)
                last_heartbeat = now

            # Autonomous cycle (run periodically even when inbox is empty)
            if now - last_autonomous >= AUTONOMOUS_INTERVAL:
                try:
                    run_autonomous_cycle(_autonomous_run, DEFAULT_SESSION_ID, conn)
                except Exception:
                    traceback.print_exc()
                last_autonomous = now

            # Inbox job
            job = claim_inbox(conn)
            if not job:
                conn.rollback()
                time.sleep(current_poll)
                current_poll = min(current_poll * 1.5, MAX_POLL_SECONDS)
                continue

            current_poll = POLL_SECONDS
            print(f"Claimed inbox {job['id']}")
            try:
                process_job(conn, session_cache, job)
            except Exception:
                traceback.print_exc()
                try:
                    complete_inbox(conn, job["id"], ok=False)
                    insert_assistant_message(
                        conn,
                        str(job["session_id"]),
                        "Worker error while handling that message. Check the PC worker log.",
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    traceback.print_exc()


def main():
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("Set DATABASE_URL in your .env file (Neon connection string).")
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
    print(f"PC agent AUTONOMOUS worker started ({provider}). Polling Neon + running goal engine...")

    while True:
        try:
            run_loop()
        except KeyboardInterrupt:
            print("Stopping worker.")
            break
        except Exception:
            traceback.print_exc()
            print("Connection lost; retrying in 3s...")
            time.sleep(3)


if __name__ == "__main__":
    main()
