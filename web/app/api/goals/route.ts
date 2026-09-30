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
    const goals = await db`
      SELECT id, title, description, status, priority, cron_expr, condition_ps,
             last_run_at, next_run_at, run_count, created_at
      FROM agent_goals
      WHERE session_id = ${sessionId}
      ORDER BY priority DESC, created_at DESC
      LIMIT 100
    `;

    const logs = await db`
      SELECT al.id, al.trigger_type, al.prompt, al.reply, al.success,
             al.duration_ms, al.created_at, ag.title AS goal_title
      FROM autonomous_log al
      LEFT JOIN agent_goals ag ON ag.id = al.goal_id
      WHERE al.session_id = ${sessionId}
      ORDER BY al.created_at DESC
      LIMIT 20
    `;

    return NextResponse.json({ goals, logs });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function POST(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  let body: {
    title?: string;
    description?: string;
    cron_expr?: string;
    condition_ps?: string;
    priority?: number;
    session_id?: string;
  };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const title = String(body.title ?? "").trim();
  const description = String(body.description ?? "").trim();
  const cron_expr = body.cron_expr ? String(body.cron_expr).trim() : null;
  const condition_ps = body.condition_ps ? String(body.condition_ps).trim() : null;
  const priority = Number(body.priority ?? 5);
  const sessionId = body.session_id || DEFAULT_SESSION_ID;

  if (!title || !description) {
    return NextResponse.json({ error: "title and description are required" }, { status: 400 });
  }

  const db = sql();
  try {
    const [created] = await db`
      INSERT INTO agent_goals (session_id, title, description, cron_expr, condition_ps, priority)
      VALUES (${sessionId}, ${title}, ${description}, ${cron_expr}, ${condition_ps}, ${priority})
      RETURNING id, title, created_at
    `;
    return NextResponse.json({ ok: true, goal: created });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}

export async function DELETE(req: Request) {
  const denied = checkAuth(req);
  if (denied) return denied;

  const url = new URL(req.url);
  const goalId = url.searchParams.get("id");
  const sessionId = url.searchParams.get("session_id") || DEFAULT_SESSION_ID;

  if (!goalId) {
    return NextResponse.json({ error: "id is required" }, { status: 400 });
  }

  const db = sql();
  try {
    await db`
      UPDATE agent_goals
      SET status = 'cancelled', updated_at = now()
      WHERE id = ${goalId} AND session_id = ${sessionId}
    `;
    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
