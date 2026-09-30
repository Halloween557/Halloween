import { NextResponse } from "next/server";
import { checkAuth } from "@/lib/auth";
import { DEFAULT_SESSION_ID } from "@/lib/constants";
import { sql } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const sessionId = url.searchParams.get("session_id") || DEFAULT_SESSION_ID;
  const db = sql();

  try {
    const memories = await db`
      SELECT id, category, key, content, created_at, updated_at
      FROM agent_memories
      WHERE session_id = ${sessionId}
      ORDER BY updated_at DESC
      LIMIT 100
    `;
    return NextResponse.json({ memories });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  let body: { key?: string; content?: string; category?: string; session_id?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const key = String(body.key ?? "").trim();
  const content = String(body.content ?? "").trim();
  const category = String(body.category ?? "general").trim();
  const sessionId = body.session_id || DEFAULT_SESSION_ID;

  if (!key || !content) {
    return NextResponse.json({ error: "key and content are required" }, { status: 400 });
  }

  const db = sql();
  try {
    await db`
      INSERT INTO agent_memories (session_id, category, key, content, updated_at)
      VALUES (${sessionId}, ${category}, ${key}, ${content}, now())
      ON CONFLICT (session_id, key) DO UPDATE
      SET category = EXCLUDED.category,
          content = EXCLUDED.content,
          updated_at = now()
    `;
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function DELETE(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const key = url.searchParams.get("key");
  const sessionId = url.searchParams.get("session_id") || DEFAULT_SESSION_ID;

  if (!key) {
    return NextResponse.json({ error: "key is required" }, { status: 400 });
  }

  const db = sql();
  try {
    await db`
      DELETE FROM agent_memories
      WHERE session_id = ${sessionId} AND key = ${key}
    `;
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
