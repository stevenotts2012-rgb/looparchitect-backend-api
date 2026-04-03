/**
 * Regression tests for the arrangement download client functions.
 *
 * Covers:
 *  - successful blob download
 *  - failed request (non-2xx) throws
 *  - slow request times out and shows actionable error
 *  - AbortController cancels the fetch on timeout
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { downloadArrangement, downloadDawExport, DOWNLOAD_TIMEOUT_MS } from "../client";

// ── helpers ──────────────────────────────────────────────────────────────────

/** Build a minimal fetch Response-like object. */
function makeResponse(
  status: number,
  body: BodyInit | null = null,
  contentType = "audio/wav"
): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": contentType },
  });
}

// ── setup / teardown ─────────────────────────────────────────────────────────

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

// ── downloadArrangement ───────────────────────────────────────────────────────

describe("downloadArrangement", () => {
  it("returns a Blob on a successful 200 response", async () => {
    const audioData = new Uint8Array([82, 73, 70, 70]); // "RIFF" magic bytes
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse(200, audioData, "audio/wav"))
    );

    const promise = downloadArrangement(42);
    // No timers needed — resolves immediately
    const blob = await promise;

    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBe(audioData.byteLength);
  });

  it("throws a descriptive error for a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse(409, "Arrangement still processing"))
    );

    await expect(downloadArrangement(42)).rejects.toThrow("Download failed: 409");
  });

  it("throws a timeout error when the fetch stalls longer than DOWNLOAD_TIMEOUT_MS", async () => {
    // fetch returns a promise that never resolves
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            const signal = (init as RequestInit & { signal?: AbortSignal })?.signal;
            if (signal) {
              signal.addEventListener("abort", () => {
                reject(new DOMException("The operation was aborted.", "AbortError"));
              });
            }
          })
      )
    );

    const promise = downloadArrangement(42);
    // Advance time past the timeout threshold
    vi.advanceTimersByTime(DOWNLOAD_TIMEOUT_MS + 100);
    await expect(promise).rejects.toThrow(/timed out/i);
  });

  it("calls fetch with the arrangement's download URL", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(makeResponse(200, new Uint8Array([0x00]), "audio/wav"));
    vi.stubGlobal("fetch", fetchMock);

    await downloadArrangement(7);

    expect(fetchMock).toHaveBeenCalledOnce();
    const calledUrl: string = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toMatch(/\/api\/v1\/arrangements\/7\/download/);
  });
});

// ── downloadDawExport ─────────────────────────────────────────────────────────

describe("downloadDawExport", () => {
  it("returns a Blob on a successful 200 response", async () => {
    const zipData = new Uint8Array([80, 75, 3, 4]); // "PK\x03\x04" ZIP magic
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse(200, zipData, "application/zip"))
    );

    const promise = downloadDawExport(42);
    const blob = await promise;

    expect(blob).toBeInstanceOf(Blob);
    expect(blob.size).toBe(zipData.byteLength);
  });

  it("throws a descriptive error for a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(makeResponse(404, "Not found"))
    );

    await expect(downloadDawExport(42)).rejects.toThrow(
      "DAW export download failed: 404"
    );
  });

  it("throws a timeout error when the fetch stalls longer than DOWNLOAD_TIMEOUT_MS", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            const signal = (init as RequestInit & { signal?: AbortSignal })?.signal;
            if (signal) {
              signal.addEventListener("abort", () => {
                reject(new DOMException("The operation was aborted.", "AbortError"));
              });
            }
          })
      )
    );

    const promise = downloadDawExport(42);
    vi.advanceTimersByTime(DOWNLOAD_TIMEOUT_MS + 100);
    await expect(promise).rejects.toThrow(/timed out/i);
  });
});
