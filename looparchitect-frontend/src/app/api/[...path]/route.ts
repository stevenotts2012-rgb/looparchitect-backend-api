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
 * BACKEND_ORIGIN   Server-side URL of the FastAPI service.
 *                  Defaults to http://localhost:8000.
 *                  Example (Railway): https://api-production-xxx.up.railway.app
 *
 * Final request path verified by this proxy:
 *   browser POST /api/v1/loops/with-file
 *        → proxy
 *        → FastAPI POST /api/v1/loops/with-file   ✅
 */

import { NextRequest, NextResponse } from "next/server";

/** FastAPI backend origin — set BACKEND_ORIGIN in .env.local or Railway env. */
const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

/** HTTP methods that Next.js App Router should handle. */
export const dynamic = "force-dynamic";

async function proxyRequest(
  request: NextRequest,
  { params }: { params: { path: string[] } }
): Promise<NextResponse> {
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

  let body: BodyInit | null = null;
  if (request.method !== "GET" && request.method !== "HEAD") {
    body = await request.arrayBuffer();
  }

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
