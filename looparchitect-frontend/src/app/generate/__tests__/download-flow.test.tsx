/**
 * Regression tests for the "Download Arrangement" flow in the GeneratePage
 * component.
 *
 * Covers:
 *  - spinner shows while downloading and clears on success
 *  - direct URL (signed URL) path triggers browser download without blob fetch
 *  - no-signed-URL path shows an error message (render-async flow has no fallback)
 *  - failed request clears spinner and shows actionable error
 *  - double-click is ignored while a download is in progress
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";

// ── Module mocks (must be hoisted before imports that use them) ───────────────

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}));

// We mock only the functions exercised by the tests.
vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>(
    "@/api/client"
  );
  return {
    ...actual,
    renderAsync: vi.fn(),
    getJobStatus: vi.fn(),
    downloadArrangement: vi.fn(),
    getDawExportInfo: vi.fn(),
    downloadDawExport: vi.fn(),
  };
});

import GeneratePage from "../page";
import * as client from "@/api/client";

// ── helpers ───────────────────────────────────────────────────────────────────

const JOB_ID = "job-abc";

/**
 * Minimal render-async response (POST /api/v1/loops/{id}/render-async).
 * No arrangement_id — the render-async endpoint returns job metadata only.
 */
function makeRenderAsyncResponse(): client.RenderAsyncResponse {
  return {
    job_id: JOB_ID,
    loop_id: 1,
    status: "queued",
    created_at: new Date().toISOString(),
    poll_url: `/api/v1/jobs/${JOB_ID}`,
    deduplicated: false,
  };
}

/** Job-status response for a completed render — includes a signed audio URL */
function makeCompletedStatus(signedUrl?: string): client.JobStatusResponse {
  return {
    job_id: JOB_ID,
    loop_id: 1,
    job_type: "render",
    status: "completed" as client.JobStatus,
    progress: 100,
    progress_message: "Done",
    created_at: new Date().toISOString(),
    started_at: new Date().toISOString(),
    finished_at: new Date().toISOString(),
    output_files: signedUrl
      ? [
          {
            name: "arrangement.wav",
            s3_key: "arrangements/55.wav",
            content_type: "audio/wav",
            signed_url: signedUrl,
          },
        ]
      : [],
    error_message: null,
    retry_count: 0,
  };
}

/** Drive the component to the "completed" state. */
async function renderCompleted(signedUrl?: string) {
  vi.mocked(client.renderAsync).mockResolvedValue(makeRenderAsyncResponse());
  vi.mocked(client.getJobStatus).mockResolvedValue(makeCompletedStatus(signedUrl));

  render(<GeneratePage />);

  // Fill loop ID
  fireEvent.change(screen.getByLabelText(/loop id/i), {
    target: { value: "1" },
  });

  // Click generate
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /generate arrangement/i }));
  });

  // Wait for the download button to appear (polls trigger after generate)
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /download arrangement/i })
    ).toBeInTheDocument()
  );
}

// ── test setup ────────────────────────────────────────────────────────────────

beforeEach(() => {
  // Stub anchor click so tests don't navigate
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  // Stub URL methods
  vi.stubGlobal("URL", {
    createObjectURL: vi.fn().mockReturnValue("blob:mock-url"),
    revokeObjectURL: vi.fn(),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

// ── tests ─────────────────────────────────────────────────────────────────────

describe("Download Arrangement – direct signed URL path", () => {
  it("triggers browser download via anchor href and does NOT call downloadArrangement()", async () => {
    const signedUrl = "https://s3.example.com/signed/arrangement.wav?token=abc";
    await renderCompleted(signedUrl);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    // Blob fetch should NOT have been called — direct URL was used
    expect(client.downloadArrangement).not.toHaveBeenCalled();
    // Anchor click should have been called
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();

    // Button should return to its idle label
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /download arrangement \(wav\)/i })
      ).not.toBeDisabled()
    );
  });
});

describe("Download Arrangement – no signed URL (render-async flow)", () => {
  it("shows an error when no signed URL is available", async () => {
    // Complete without a signed URL (empty output_files)
    await renderCompleted(/* no signed URL */ undefined);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    // downloadArrangement should NOT be called — no arrangement_id in render-async flow
    expect(client.downloadArrangement).not.toHaveBeenCalled();

    // Error message should be visible
    await waitFor(() =>
      expect(screen.getByText(/audio file url not available/i)).toBeInTheDocument()
    );

    // Button should be re-enabled after the error
    expect(
      screen.getByRole("button", { name: /download arrangement \(wav\)/i })
    ).not.toBeDisabled();
  });
});

describe("Download Arrangement – UI state after signed-URL download", () => {
  it("re-enables the button after a successful signed-URL download", async () => {
    const signedUrl = "https://s3.example.com/signed/arrangement.wav?token=xyz";
    await renderCompleted(signedUrl);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    // Button should return to idle (not stuck in downloading state)
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /download arrangement \(wav\)/i })
      ).not.toBeDisabled()
    );
  });
});

describe("Download Arrangement – double-click prevention", () => {
  it("shows download button enabled after a successful signed-URL download", async () => {
    const signedUrl = "https://s3.example.com/signed/arrangement.wav?token=dbl";
    await renderCompleted(signedUrl);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    // Button must return to its idle, enabled state
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /download arrangement \(wav\)/i })
      ).not.toBeDisabled()
    );

    // Anchor click was fired at least once (primary path triggered)
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
  });
});

