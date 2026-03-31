"use client";

/**
 * Generate Arrangement Page
 *
 * After the user clicks "Generate Arrangement" this page:
 * 1. Calls POST /api/v1/arrangements/generate
 * 2. Stores the returned job_id
 * 3. Polls GET /api/v1/jobs/{job_id} every 2 seconds (real job endpoint)
 * 4. Maps backend states → UI states:
 *      queued      → "Queued"
 *      processing  → "Processing"
 *      completed   → "Completed"   (backend stores as "succeeded"; API normalises)
 *      failed      → "Failed"
 * 5. Stops polling automatically when status is "completed" or "failed"
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  generateArrangement,
  getJobStatus,
  downloadArrangement,
  isTerminalJobStatus,
  type GenerateArrangementResponse,
  type JobStatus,
  type JobStatusResponse,
} from "@/api/client";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 2_000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PageState {
  loopId: string;
  targetSeconds: string;
  genre: string;
  styleText: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function GeneratePage() {
  const [form, setForm] = useState<PageState>({
    loopId: "",
    targetSeconds: "60",
    genre: "Trap",
    styleText: "",
  });

  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  // The generate response — contains job_id used for polling
  const [generateResponse, setGenerateResponse] =
    useState<GenerateArrangementResponse | null>(null);

  // job_id stored from the generate response
  const [jobId, setJobId] = useState<string | null>(null);

  // Current job status polled from GET /api/v1/jobs/{job_id}
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Polling logic
  // ---------------------------------------------------------------------------

  /**
   * Poll GET /api/v1/jobs/{job_id} until a terminal state is reached.
   * Stops automatically on "completed" or "failed".
   */
  const startPolling = useCallback((id: string) => {
    // Clear any existing interval before starting a new one
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
    }

    const poll = async () => {
      try {
        const status = await getJobStatus(id);
        setJobStatus(status);
        setPollError(null);

        // Stop polling when terminal state reached
        if (isTerminalJobStatus(status.status as JobStatus)) {
          if (pollIntervalRef.current !== null) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setPollError(message);
        // Do not stop polling on transient network errors
      }
    };

    // Immediate first poll then repeat
    poll();
    pollIntervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, []);

  // Clean up interval on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current !== null) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Generate handler
  // ---------------------------------------------------------------------------

  const handleGenerate = async () => {
    const loopIdNum = parseInt(form.loopId, 10);
    if (isNaN(loopIdNum) || loopIdNum <= 0) {
      setGenerateError("Please enter a valid Loop ID.");
      return;
    }

    setIsGenerating(true);
    setGenerateError(null);
    setGenerateResponse(null);
    setJobId(null);
    setJobStatus(null);
    setPollError(null);

    try {
      const response = await generateArrangement({
        loop_id: loopIdNum,
        target_seconds: parseInt(form.targetSeconds, 10) || 60,
        genre: form.genre || undefined,
        style_text_input: form.styleText || undefined,
        use_ai_parsing: Boolean(form.styleText),
      });

      setGenerateResponse(response);

      // Store job_id — prefer the top-level field added to support polling;
      // fall back to render_job_ids[0] for older backend versions.
      const resolvedJobId =
        response.job_id ?? response.render_job_ids?.[0] ?? null;

      if (resolvedJobId) {
        setJobId(resolvedJobId);
        startPolling(resolvedJobId);
      }
    } catch (err) {
      setGenerateError(
        err instanceof Error ? err.message : "An unexpected error occurred."
      );
    } finally {
      setIsGenerating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Download handler
  // ---------------------------------------------------------------------------

  const handleDownload = async () => {
    if (!generateResponse?.arrangement_id) return;
    try {
      const blob = await downloadArrangement(generateResponse.arrangement_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `arrangement-${generateResponse.arrangement_id}.wav`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(
        "Download failed: " +
          (err instanceof Error ? err.message : String(err))
      );
    }
  };

  // ---------------------------------------------------------------------------
  // Derived UI state
  // ---------------------------------------------------------------------------

  const uiStatus: Record<JobStatus, string> = {
    queued: "Queued",
    processing: "Processing",
    completed: "Completed",
    failed: "Failed",
  };

  const currentStatus = jobStatus?.status as JobStatus | undefined;
  const isCompleted = currentStatus === "completed";
  const isFailed = currentStatus === "failed";
  const isInProgress =
    currentStatus === "queued" || currentStatus === "processing";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="mx-auto max-w-2xl p-8 space-y-6">
      <h1 className="text-3xl font-bold">Generate Arrangement</h1>

      {/* Form */}
      <section className="space-y-4">
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="loopId">
            Loop ID
          </label>
          <input
            id="loopId"
            type="number"
            min={1}
            className="w-full border rounded px-3 py-2"
            value={form.loopId}
            onChange={(e) => setForm((f) => ({ ...f, loopId: e.target.value }))}
          />
        </div>

        <div>
          <label
            className="block text-sm font-medium mb-1"
            htmlFor="targetSeconds"
          >
            Duration (seconds)
          </label>
          <input
            id="targetSeconds"
            type="number"
            min={10}
            max={3600}
            className="w-full border rounded px-3 py-2"
            value={form.targetSeconds}
            onChange={(e) =>
              setForm((f) => ({ ...f, targetSeconds: e.target.value }))
            }
          />
        </div>

        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="genre">
            Genre
          </label>
          <input
            id="genre"
            type="text"
            className="w-full border rounded px-3 py-2"
            value={form.genre}
            onChange={(e) => setForm((f) => ({ ...f, genre: e.target.value }))}
          />
        </div>

        <div>
          <label
            className="block text-sm font-medium mb-1"
            htmlFor="styleText"
          >
            Style (natural language)
          </label>
          <input
            id="styleText"
            type="text"
            placeholder="e.g. dark cinematic trap"
            className="w-full border rounded px-3 py-2"
            value={form.styleText}
            onChange={(e) =>
              setForm((f) => ({ ...f, styleText: e.target.value }))
            }
          />
        </div>

        <button
          onClick={handleGenerate}
          disabled={isGenerating || isInProgress}
          className="w-full bg-blue-600 text-white py-2 rounded disabled:opacity-50"
        >
          {isGenerating ? "Requesting…" : "Generate Arrangement"}
        </button>

        {generateError && (
          <p className="text-red-600 text-sm">{generateError}</p>
        )}
      </section>

      {/* Job status — polled from GET /api/v1/jobs/{job_id} */}
      {jobId && (
        <section className="border rounded p-4 space-y-2">
          <h2 className="font-semibold text-lg">Job Status</h2>
          <p className="text-sm text-gray-500">
            Job ID: <code className="font-mono">{jobId}</code>
          </p>
          <p className="text-sm text-gray-500">
            Polling: <code className="font-mono">/api/v1/jobs/{jobId}</code>
          </p>

          {jobStatus ? (
            <>
              {currentStatus && (
                <div className="flex items-center gap-2">
                  <StatusBadge status={currentStatus} />
                  <span className="text-sm">
                    {uiStatus[currentStatus] ?? currentStatus}
                  </span>
                </div>
              )}

              {isInProgress && (
                <div className="w-full bg-gray-200 rounded h-2">
                  <div
                    className="bg-blue-500 h-2 rounded transition-all"
                    style={{ width: `${jobStatus.progress}%` }}
                  />
                </div>
              )}

              {jobStatus.progress_message && (
                <p className="text-sm text-gray-600">
                  {jobStatus.progress_message}
                </p>
              )}

              {isFailed && jobStatus.error_message && (
                <p className="text-sm text-red-600">{jobStatus.error_message}</p>
              )}
            </>
          ) : pollError ? (
            <p className="text-sm text-red-500">Poll error: {pollError}</p>
          ) : (
            <p className="text-sm text-gray-500">Loading…</p>
          )}
        </section>
      )}

      {/* Download — only shown when completed */}
      {isCompleted && generateResponse?.arrangement_id && (
        <section>
          <button
            onClick={handleDownload}
            className="w-full bg-green-600 text-white py-2 rounded"
          >
            Download Arrangement (WAV)
          </button>
        </section>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: JobStatus }) {
  const colors: Record<JobStatus, string> = {
    queued: "bg-yellow-100 text-yellow-800",
    processing: "bg-blue-100 text-blue-800",
    completed: "bg-green-100 text-green-800",
    failed: "bg-red-100 text-red-800",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${colors[status]}`}
    >
      {status}
    </span>
  );
}
