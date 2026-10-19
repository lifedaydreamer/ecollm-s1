import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
type Context = {params: Promise<{path: string[]}>};
async function proxy(request: NextRequest, context: Context) {
  const {path} = await context.params;
  if (path.some(p => p === ".." || p.includes("\\"))) return new Response("Invalid path", {status: 400});
  const base = process.env.TRADEPILOT_API_URL || "http://127.0.0.1:8100";
  const headers = new Headers();
  headers.set("X-API-Key", process.env.TRADEPILOT_TOKEN || "");
  if (request.headers.has("content-type")) headers.set("content-type", request.headers.get("content-type")!);
  try {
    const result = await fetch(`${base}/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`, {
      method: request.method, headers, body: ["GET","HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: "no-store", signal: AbortSignal.timeout(240000)
    });
    const output = new Headers();
    for (const key of ["content-type", "content-disposition"]) if (result.headers.has(key)) output.set(key,result.headers.get(key)!);
    return new Response(result.body, {status: result.status, headers: output});
  } catch {return Response.json({detail: "后端暂不可用，请检查远程服务"}, {status:502});}
}
export {proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH};
