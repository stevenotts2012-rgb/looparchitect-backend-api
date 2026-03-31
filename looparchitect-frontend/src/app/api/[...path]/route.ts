/**
 * Next.js catch-all API proxy
 *
 * Forwards every request sent to /api/... from the browser to the FastAPI
 * backend so that:
 *   1. CORS is never a problem — the browser only talks to the Next.js
 *      origin; the server-to-server call is same-domain from the browser's
 *      perspective.
 *   2. Multipart file uploads (POST /api/v1/loops/with-file) reach FastAPI
 *      reliably without any path mangling.
 *
 * Environment variables
 * ─────────────────────
 * BACKEND_ORIGIN   Server-side URL of the FastAPI service (never sent to the
 *                  browser).  Set this in .env.local for local development.
 *
 *                  Local dev default : http://localhost:8000
 *                  Production example: https://api-production-xxx.up.railway.app
 *
 *                  Fallback chain: BACKEND_ORIGIN → NEXT_PUBLIC_API_URL → http://localhost:8000
 *                  In local dev, only BACKEND_ORIGIN (or the built-in default) is needed.
 *
 * Final request path verified by this proxy:
 *   browser POST /api/v1/loops/with-file
 *        → proxy (Next.js, port 3000)
 *        → FastAPI POST /api/v1/loops/with-file (port 8000)  ✅
 */

import { NextRequest, NextResponse } from "next/server";

/** FastAPI backend origin — set BACKEND_ORIGIN in .env.local or Railway env. */
const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

/** HTTP methods that Next.js App Router should handle. */
export const dynamic = "force-dynamic";

// Next.js 15 made route segment params async (Promise<{…}>).
// Next.js 13/14 passes them as a plain object.
// Using Promise.resolve() handles both without a breaking change.
type RouteContext = { params: Promise<{ path: string[] }> | { path: string[] } };

async function proxyRequest(
  request: NextRequest,
  context: RouteContext
): Promise<NextResponse> {
  // Await params — resolves instantly on Next.js 14 (plain object) and
  // correctly on Next.js 15 (Promise).
  const params = await Promise.resolve(context.params);

  // Reconstruct the path from the catch-all segments, preserving the
  // leading /api/ prefix so FastAPI receives the exact same path.
  const backendPath = "/" + params.path.join("/");
  const search = request.nextUrl.search ?? "";
  const targetUrl = `${BACKEND_ORIGIN}${backendPath}${search}`;

  // Build forwarded headers.  We strip the `host` header so FastAPI sees
  // its own hostname, and omit `content-length` because we are streaming
  // the body and the length may change.
  const forwardHeaders = new Headers(request.headers);
  forwardHeaders.delete("host");
  forwardHeaders.delete("content-length");

  // Propagate correlation ID if already present; otherwise let FastAPI
  // middleware generate one.
  const correlationId = request.headers.get("x-correlation-id");
  if (correlationId) {
    forwardHeaders.set("x-correlation-id", correlationId);
  }

  // Stream the request body directly to FastAPI instead of buffering it with
  // arrayBuffer().  Buffering the entire file in memory caused hangs and
  // timeouts for large audio uploads (up to 50 MB) and prevented the POST
  // from ever reaching the backend.  Streaming via request.body avoids that
  // and works for any file size.  The duplex:"half" option below is required
  // by Node 18+ fetch when a ReadableStream is used as the request body.
  const body: BodyInit | null =
    request.method !== "GET" && request.method !== "HEAD"
      ? request.body
      : null;

  let backendResponse: Response;
  try {
    backendResponse = await fetch(targetUrl, {
      method: request.method,
      headers: forwardHeaders,
      body,
      // @ts-expect-error — Node 18 fetch supports duplex for streaming
      duplex: "half",
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      { error: "Proxy error", detail: message },
      { status: 502 }
    );
  }

  // Stream the backend response body back to the browser.
  const responseHeaders = new Headers(backendResponse.headers);
  // Remove encoding headers that Next.js handles itself.
  responseHeaders.delete("transfer-encoding");

  return new NextResponse(backendResponse.body, {
    status: backendResponse.status,
    statusText: backendResponse.statusText,
    headers: responseHeaders,
  });
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
