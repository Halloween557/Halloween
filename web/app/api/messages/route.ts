import { NextResponse } from "next/server";
import { checkAuth } from "@/lib/auth";
import { DEFAULT_SESSION_ID, ONLINE_THRESHOLD_MS } from "@/lib/constants";
import { sql } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type MessageRow = {
  id: string;
  role: string;
  content: string;
  created_at: string;
};

type DeviceRow = {
  id: string;
  last_seen_at: string;
  status: string;
};

function devicePayload(row: DeviceRow | undefined) {
  if (!row) {
    return { online: false, status: "offline", last_seen_at: null };
  }
  const lastSeen = new Date(row.last_seen_at).getTime();
  const online = Number.isFinite(lastSeen) && Date.now() - lastSeen < ONLINE_THRESHOLD_MS;
  return {
    online,
    status: online ? "online" : "offline",
    last_seen_at: row.last_seen_at,
  };
}

export async function GET(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const sessionId = url.searchParams.get("session_id") || DEFAULT_SESSION_ID;
  const db = sql();

  const messages = (await db`
    SELECT id, role, content, created_at
    FROM messages
    WHERE session_id = ${sessionId}
    ORDER BY created_at ASC
    LIMIT 200
  `) as MessageRow[];

  const devices = (await db`
    SELECT id, last_seen_at, status
    FROM devices
    ORDER BY last_seen_at DESC
    LIMIT 1
  `) as DeviceRow[];

  return NextResponse.json({
    messages,
    device: devicePayload(devices[0]),
  });
}

export async function POST(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  let body: { message?: string; client_id?: string; session_id?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const message = String(body.message ?? "").trim();
  if (!message) {
    return NextResponse.json({ error: "message required" }, { status: 400 });
  }

  const sessionId = body.session_id || DEFAULT_SESSION_ID;
  const clientId = body.client_id ? String(body.client_id) : null;
  const db = sql();

  if (clientId) {
    const existing = await db`
      SELECT id FROM messages
      WHERE session_id = ${sessionId} AND client_id = ${clientId}
      LIMIT 1
    `;
    if (existing.length > 0) {
      return NextResponse.json({ ok: true, duplicate: true });
    }
  }

  try {
    await db`
      WITH msg AS (
        INSERT INTO messages (session_id, role, content, client_id)
        VALUES (${sessionId}, 'user', ${message}, ${clientId})
        RETURNING id
      )
      INSERT INTO inbox (session_id, body, status)
      VALUES (${sessionId}, ${message}, 'queued')
    `;
  } catch (err) {
    const text = err instanceof Error ? err.message : String(err);
    if (text.includes("messages_session_client_id_uidx")) {
      return NextResponse.json({ ok: true, duplicate: true });
    }
    throw err;
  }

  return NextResponse.json({ ok: true });
}
