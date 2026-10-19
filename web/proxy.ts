import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "node:crypto";

// Loopback on a shared host is not an authentication boundary.
export function proxy(request: NextRequest) {
  const token = process.env.TRADEPILOT_TOKEN;
  if (!token) return new NextResponse("Workspace credential is not configured", {status: 503});
  const header = request.headers.get("authorization") || "";
  const candidate = header.startsWith("Basic ") ? Buffer.from(header.slice(6), "base64") : Buffer.alloc(0);
  const expected = Buffer.from(`tradepilot:${token}`, "utf8");
  if (candidate.length === expected.length && timingSafeEqual(candidate, expected)) return NextResponse.next();
  return new NextResponse("请使用服务器工作区凭据登录", {
    status: 401,
    headers: {"WWW-Authenticate": 'Basic realm="TradePilot workspace", charset="UTF-8"', "Cache-Control": "no-store"}
  });
}
export const config = {matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"]};
