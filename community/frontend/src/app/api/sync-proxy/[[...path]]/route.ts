import type { NextRequest } from "next/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await context.params;
  if (path.some(segment => !/^[a-zA-Z0-9_-]+$/.test(segment))) return new Response(null, { status: 400 });
  const endpoint = path.length === 1 && path[0] === "me" ? "/api/me" : "/api/sync/" + path.join("/");
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://localhost:8001"}${endpoint}`, {
      method: request.method, cache: "no-store", redirect: "error",
      headers: { Authorization: request.headers.get("authorization") ?? "",
        "Content-Type": request.headers.get("content-type") ?? "application/json" },
      ...(request.method !== "GET" ? { body: await request.arrayBuffer() } : {}),
    });
    return new Response(await response.text(), { status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return Response.json({ detail: { code: "API_UNAVAILABLE" } }, { status: 502 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
