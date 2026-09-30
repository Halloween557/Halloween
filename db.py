"""Postgres helpers for the Windows worker (psycopg, not HTTP)."""

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from constants import DEFAULT_DEVICE_ID, DEFAULT_SESSION_ID


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL in your .env file (Neon connection string).")
    return url


@contextmanager
def get_conn():
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        yield conn


def heartbeat(conn, device_id: str | None = None):
    did = device_id or os.environ.get("DEVICE_ID") or DEFAULT_DEVICE_ID
    conn.execute(
        """
        INSERT INTO devices (id, last_seen_at, status)
        VALUES (%s, now(), 'online')
        ON CONFLICT (id) DO UPDATE
        SET last_seen_at = now(), status = 'online'
        """,
        (did,),
    )
    conn.commit()


def load_agent_state(conn, session_id: str):
    state = conn.execute(
        "SELECT messages FROM agent_state WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    pending_row = conn.execute(
        "SELECT payload FROM pending_actions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    messages = (state or {}).get("messages") or []
    pending = (pending_row or {}).get("payload")
    return messages, pending


def save_agent_state(conn, session_id: str, messages, pending):
    conn.execute(
        """
        INSERT INTO agent_state (session_id, messages, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (session_id) DO UPDATE
        SET messages = EXCLUDED.messages, updated_at = now()
        """,
        (session_id, Json(messages)),
    )
    if pending is None:
        conn.execute("DELETE FROM pending_actions WHERE session_id = %s", (session_id,))
    else:
        conn.execute(
            """
            INSERT INTO pending_actions (session_id, payload, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (session_id) DO UPDATE
            SET payload = EXCLUDED.payload, updated_at = now()
            """,
            (session_id, Json(pending)),
        )


def claim_inbox(conn):
    with conn.transaction():
        row = conn.execute(
            """
            SELECT id, session_id, body
            FROM inbox
            WHERE status = 'queued'
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE inbox SET status = 'processing' WHERE id = %s",
            (row["id"],),
        )
        return row


def complete_inbox(conn, inbox_id, ok: bool = True):
    conn.execute(
        "UPDATE inbox SET status = %s WHERE id = %s",
        ("done" if ok else "failed", inbox_id),
    )


def insert_assistant_message(conn, session_id: str, content: str):
    conn.execute(
        """
        INSERT INTO messages (session_id, role, content)
        VALUES (%s, 'assistant', %s)
        """,
        (session_id, content),
    )


def ensure_default_session(conn):
    conn.execute(
        """
        INSERT INTO sessions (id)
        VALUES (%s)
        ON CONFLICT (id) DO NOTHING
        """,
        (DEFAULT_SESSION_ID,),
    )
    conn.commit()


# ---- Memory helpers ----

def load_memories(conn, session_id: str) -> list[dict]:
    """Return all memories for a session as a list of dicts."""
    return conn.execute(
        """
        SELECT key, category, content, updated_at
        FROM agent_memories
        WHERE session_id = %s
        ORDER BY updated_at DESC
        """,
        (session_id,),
    ).fetchall()


def upsert_memory(conn, session_id: str, key: str, content: str, category: str = "general"):
    """Insert or update a memory entry."""
    conn.execute(
        """
        INSERT INTO agent_memories (session_id, key, content, category, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT ON CONSTRAINT agent_memories_session_key_uidx DO UPDATE
        SET content = EXCLUDED.content,
            category = EXCLUDED.category,
            updated_at = now()
        """,
        (session_id, key, content, category),
    )
    conn.commit()


def delete_memory(conn, session_id: str, key: str) -> bool:
    """Delete a memory by key. Returns True if a row was removed."""
    result = conn.execute(
        "DELETE FROM agent_memories WHERE session_id = %s AND key = %s",
        (session_id, key),
    )
    conn.commit()
    return (result.rowcount or 0) > 0
