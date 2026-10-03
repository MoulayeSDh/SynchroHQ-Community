import type { NextRequest } from "next/server";
async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await context.params;
  if (path.length > 1 || (path.length === 1 && !["demo", "administration", "login", "logout", "change-password"].includes(path[0]))) return new Response(null, { status: 404 });
  if (request.method === "POST" && !["demo", "login", "logout", "change-password"].includes(path[0] ?? "")) return new Response(null, { status: 405 });
  if (request.method === "GET" && ["login", "logout", "change-password"].includes(path[0] ?? "")) return new Response(null, { status: 405 });
  try {
    const r = await fetch(`${process.env.API_INTERNAL_URL ?? "http://localhost:8001"}/api/session${path.length ? "/" + path[0] : ""}`, {
      method: request.method, cache: "no-store", redirect: "error", headers: { Authorization: request.headers.get("authorization") ?? "", "Content-Type": "application/json" },
      ...(request.method === "POST" ? { body: await request.text() } : {}),
    });
    return new Response(r.status === 204 ? null : await r.text(), { status: r.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return Response.json({ detail: "SERVICE_UNAVAILABLE" }, { status: 502 }); }
}
export const GET = proxy;
export const POST = proxy;
