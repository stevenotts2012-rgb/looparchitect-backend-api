/**
 * Regression tests for the "Download Arrangement" flow in the GeneratePage
 * component.
 *
 * Covers:
 *  - spinner shows while downloading and clears on success
 *  - direct URL (signed URL) path triggers browser download without blob fetch
 *  - blob fallback path triggers browser download when no signed URL
 *  - failed request clears spinner and shows actionable error
 *  - slow request times out and shows actionable error
 *  - double-click is ignored while a download is in progress
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";

// ── Module mocks (must be hoisted before imports that use them) ───────────────

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}));

// We mock only the functions exercised by download; the rest use the real impl.
vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>(
    "@/api/client"
  );
  return {
    ...actual,
    generateArrangement: vi.fn(),
    getJobStatus: vi.fn(),
    downloadArrangement: vi.fn(),
    getDawExportInfo: vi.fn(),
    downloadDawExport: vi.fn(),
  };
});

import GeneratePage from "../page";
import * as client from "@/api/client";

// ── helpers ───────────────────────────────────────────────────────────────────

const ARRANGEMENT_ID = 55;
const JOB_ID = "job-abc";

/** Minimal generate response */
function makeGenerateResponse() {
  return {
    arrangement_id: ARRANGEMENT_ID,
    loop_id: 1,
    status: "queued",
    job_id: JOB_ID,
    poll_url: `/api/v1/jobs/${JOB_ID}`,
    render_job_ids: [JOB_ID],
    candidates: [],
    structure_preview: [],
  };
}

/** Job-status response for a completed arrangement — includes a signed audio URL */
function makeCompletedStatus(signedUrl?: string) {
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
  vi.mocked(client.generateArrangement).mockResolvedValue(makeGenerateResponse());
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

describe("Download Arrangement – blob fallback path", () => {
  it("fetches blob and triggers download when no signed URL is present", async () => {
    const wavBlob = new Blob([new Uint8Array([82, 73, 70, 70])], {
      type: "audio/wav",
    });
    vi.mocked(client.downloadArrangement).mockResolvedValue(wavBlob);

    // Render without a signed URL so the blob path is taken
    await renderCompleted(/* no signed URL */ undefined);

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    await waitFor(() => expect(client.downloadArrangement).toHaveBeenCalledOnce());
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();

    // Button should be re-enabled after success
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /download arrangement \(wav\)/i })
      ).not.toBeDisabled()
    );
  });

  it("shows spinner label while the blob fetch is in progress", async () => {
    // Never-resolving fetch keeps the component in downloading state
    vi.mocked(client.downloadArrangement).mockImplementation(
      () => new Promise(() => {})
    );

    await renderCompleted();

    act(() => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /downloading…/i })
      ).toBeDisabled()
    );
  });
});

describe("Download Arrangement – failure handling", () => {
  it("clears the spinner and shows an error message when the fetch fails", async () => {
    vi.mocked(client.downloadArrangement).mockRejectedValue(
      new Error("Download failed: 500 Internal Server Error")
    );

    await renderCompleted();

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    // Spinner must clear
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /download arrangement \(wav\)/i })
      ).not.toBeDisabled()
    );

    // Error message should be visible
    expect(
      screen.getByText(/download failed/i)
    ).toBeInTheDocument();
  });

  it("clears the spinner and shows an actionable error on timeout", async () => {
    vi.mocked(client.downloadArrangement).mockRejectedValue(
      new Error("Download timed out after 60 seconds. Check your connection and try again.")
    );

    await renderCompleted();

    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /download arrangement/i })
      );
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /download arrangement \(wav\)/i })
      ).not.toBeDisabled()
    );

    expect(
      screen.getByText(/timed out/i)
    ).toBeInTheDocument();
  });
});

describe("Download Arrangement – double-click prevention", () => {
  it("ignores a second click while a download is already in progress", async () => {
    let resolveDownload!: (blob: Blob) => void;
    vi.mocked(client.downloadArrangement).mockImplementation(
      () =>
        new Promise<Blob>((resolve) => {
          resolveDownload = resolve;
        })
    );

    await renderCompleted();

    const downloadButton = screen.getByRole("button", {
      name: /download arrangement/i,
    });

    // First click — starts download
    act(() => {
      fireEvent.click(downloadButton);
    });

    // Wait for button to enter disabled/downloading state
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /downloading…/i })
      ).toBeDisabled()
    );

    // Second click — should be a no-op because button is disabled
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /downloading…/i }));
    });

    // downloadArrangement must only have been called once
    expect(client.downloadArrangement).toHaveBeenCalledOnce();

    // Resolve the first download
    await act(async () => {
      resolveDownload(new Blob([], { type: "audio/wav" }));
    });
  });
});
