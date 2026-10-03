import type { NextRequest } from "next/server";

// Same-origin proxy: no token persistence, caching or configurable destination.
async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await context.params;
  if (path.some(segment => !/^[a-zA-Z0-9_-]+$/.test(segment))) return new Response(null, { status: 400 });
  const url = `${process.env.API_INTERNAL_URL ?? "http://localhost:8001"}/api/forms${path.length ? "/" + path.join("/") : ""}${request.nextUrl.search}`;
  try {
    const response = await fetch(url, {
      method: request.method, cache: "no-store", redirect: "error",
      headers: { Authorization: request.headers.get("authorization") ?? "", "Content-Type": "application/json" },
      ...(request.method !== "GET" ? { body: await request.text() } : {}),
    });
    return new Response(await response.text(), { status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch { return Response.json({ detail: "API indisponible" }, { status: 502 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
