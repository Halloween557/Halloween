import { NextResponse } from "next/server";
import { checkAuth } from "@/lib/auth";
import { DEFAULT_SESSION_ID } from "@/lib/constants";
import { sql } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  let body: { session_id?: string } = {};
  try {
    body = await req.json();
  } catch {
    // optional body
  }

  const sessionId = body.session_id || DEFAULT_SESSION_ID;
  const db = sql();

  try {
    await db`
      DELETE FROM messages
      WHERE session_id = ${sessionId}
    `;
    await db`
      DELETE FROM agent_state
      WHERE session_id = ${sessionId}
    `;
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
