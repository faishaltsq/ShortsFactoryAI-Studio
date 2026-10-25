import type { NextRequest } from "next/server";

/**
 * Same-origin proxy to the local FastAPI server.
 *
 * The browser never needs a token or a cross-origin URL, so there is no CORS surface and no
 * credential in client code. `Range` is forwarded because video seeking depends on it, and
 * `content-length` is deliberately not forwarded — the fetch layer recomputes it.
 */
type RouteContext = { params: Promise<{ path: string[] }> };

const FORWARD_REQUEST = ["accept", "content-type", "range", "if-none-match", "if-modified-since"];
const DROP_RESPONSE = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "content-encoding",
  "content-length",
]);

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  let destination: URL;
  try {
    destination = new URL(process.env.STUDIO_API_ORIGIN ?? "http://127.0.0.1:8018");
    if (
      !["http:", "https:"].includes(destination.protocol) ||
      destination.username ||
      destination.password
    ) {
      return Response.json({ detail: "invalid API origin" }, { status: 500 });
    }
    const { path } = await context.params;
    destination.pathname = `/api/${path.map(encodeURIComponent).join("/")}`;
    destination.search = request.nextUrl.search;
  } catch {
    return Response.json({ detail: "invalid API origin" }, { status: 500 });
  }

  const headers = new Headers();
  for (const name of FORWARD_REQUEST) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const token = process.env.STUDIO_API_TOKEN;
  if (token) headers.set("authorization", `Bearer ${token}`);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let body: ArrayBuffer | undefined;
  if (hasBody) {
    body = await request.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(destination, {
      method: request.method,
      headers,
      body: hasBody && body && body.byteLength > 0 ? body : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json({ detail: "API tidak dapat dihubungi" }, { status: 502 });
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!DROP_RESPONSE.has(key.toLowerCase())) out.set(key, value);
  });
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const dynamic = "force-dynamic";
