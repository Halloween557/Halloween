import { timingSafeEqual } from "crypto";
import { NextResponse } from "next/server";

export function unauthorized() {
  return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
}

export function checkAuth(req: Request): NextResponse | null {
  const token = process.env.AGENT_TOKEN;
  if (!token) {
    return NextResponse.json({ error: "Server missing AGENT_TOKEN" }, { status: 500 });
  }
  const header = req.headers.get("authorization") ?? "";
  const expected = `Bearer ${token}`;
  const a = Buffer.from(header);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    return unauthorized();
  }
  return null;
}
