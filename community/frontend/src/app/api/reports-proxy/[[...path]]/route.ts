import type { NextRequest } from "next/server";

async function proxy(request: NextRequest, context: { params: Promise<{ path?: string[] }> }) {
  const { path = [] } = await context.params;
  if (path.some(segment => !/^[a-zA-Z0-9_-]+$/.test(segment))) return new Response(null, { status: 400 });
  const endpoint = "/api/reports" + (path.length ? "/" + path.join("/") : "") + request.nextUrl.search;
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://localhost:8001"}${endpoint}`, {
      method: request.method, cache: "no-store", redirect: "error",
      headers: { Authorization: request.headers.get("authorization") ?? "",
        "Content-Type": request.headers.get("content-type") ?? "application/json" },
      ...(request.method !== "GET" ? { body: await request.arrayBuffer() } : {}),
    });
    return new Response(response.body, { status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store",
        "Content-Disposition": response.headers.get("content-disposition") ?? "inline", "X-Content-Type-Options": "nosniff" } });
  } catch { return Response.json({ detail: { code: "API_UNAVAILABLE" } }, { status: 502 }); }
}
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
