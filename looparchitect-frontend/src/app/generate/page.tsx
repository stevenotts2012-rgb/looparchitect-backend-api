"use client";

/**
 * Generate Arrangement Page
 *
 * After the user clicks "Generate Arrangement" this page:
 * 1. Calls POST /api/v1/loops/{loop_id}/render-async  (async render queue)
 * 2. Stores the returned job_id
 * 3. Polls GET /api/v1/jobs/{job_id} every 2 seconds (real job endpoint)
 * 4. Maps backend states → UI states:
 *      queued      → "Queued"
 *      processing  → "Processing"
 *      completed   → "Completed"   (backend stores as "succeeded"; API normalises)
 *      failed      → "Failed"
 * 5. Stops polling automatically when status is "completed" or "failed"
 * 6. Shows an audio preview player using the signed URL from output_files
 * 7. Allows WAV and DAW export (ZIP) downloads when completed
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  renderAsync,
  getJobStatus,
  downloadArrangement,
  getDawExportInfo,
  downloadDawExport,
  isTerminalJobStatus,
  BACKEND_BASE_URL,
  type RenderAsyncResponse,
  type JobStatus,
  type JobStatusResponse,
} from "@/api/client";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 2_000;

const GENRE_OPTIONS = ["trap", "drill", "rnb", "rage"] as const;
const VIBE_OPTIONS = [
  "dark",
  "emotional",
  "hype",
  "pain",
  "rage",
  "ambient",
  "cinematic",
] as const;

// Energy → colour mapping for timeline sections
const SECTION_ENERGY_COLORS: Record<string, string> = {
  intro: "bg-blue-100 text-blue-800",
  verse: "bg-yellow-100 text-yellow-800",
  pre_hook: "bg-orange-100 text-orange-800",
  hook: "bg-red-100 text-red-800",
  bridge: "bg-purple-100 text-purple-800",
  breakdown: "bg-purple-100 text-purple-800",
  outro: "bg-gray-100 text-gray-700",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PageState {
  loopId: string;
  targetSeconds: string;
  genre: string;
  vibe: string;
  variationIntensity: number;
  styleText: string;
  variationSeed: number | null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function GeneratePage() {
  const searchParams = useSearchParams();

  const [form, setForm] = useState<PageState>({
    loopId: "",
    targetSeconds: "60",
    genre: "trap",
    vibe: "",
    variationIntensity: 0.5,
    styleText: "",
    variationSeed: null,
  });

  // Pre-populate loopId from ?loopId= query parameter (set by upload page).
  const appliedQueryLoopId = useRef(false);
  useEffect(() => {
    if (appliedQueryLoopId.current) return;
    const qLoopId = searchParams.get("loopId");
    if (qLoopId) {
      setForm((f) => ({ ...f, loopId: qLoopId }));
      appliedQueryLoopId.current = true;
    }
  }, [searchParams]);

  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const [generateResponse, setGenerateResponse] =
    useState<RenderAsyncResponse | null>(null);

  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  const [isDawExporting, setIsDawExporting] = useState(false);
  const [dawExportError, setDawExportError] = useState<string | null>(null);

  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---------------------------------------------------------------------------
  // Polling logic
  // ---------------------------------------------------------------------------

  const startPolling = useCallback((id: string) => {
    if (pollIntervalRef.current !== null) {
      clearInterval(pollIntervalRef.current);
    }

    const poll = async () => {
      try {
        const status = await getJobStatus(id);
        setJobStatus(status);
        setPollError(null);

        if (process.env.NODE_ENV !== "production") {
          console.debug("[render_job_poll_status]", {
            job_id: id,
            status: status.status,
            progress: status.progress,
          });
        }

        if (isTerminalJobStatus(status.status as JobStatus)) {
          if (pollIntervalRef.current !== null) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setPollError(message);
      }
    };

    poll();
    pollIntervalRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current !== null) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Generate / Re-roll helpers
  // ---------------------------------------------------------------------------

  const _doGenerate = async (seed?: number) => {
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

    // Store seed used for potential re-roll
    const resolvedSeed = seed ?? form.variationSeed ?? undefined;
    if (resolvedSeed !== undefined) {
      setForm((f) => ({ ...f, variationSeed: resolvedSeed }));
    }

    try {
      // POST /api/v1/loops/{loop_id}/render-async — enqueues a render job
      const response = await renderAsync(loopIdNum, {
        genre: form.genre || undefined,
        length_seconds: parseInt(form.targetSeconds, 10) || 60,
        custom_style: form.styleText || undefined,
      });

      setGenerateResponse(response);

      const primaryJob = response.jobs?.[0];
      if (primaryJob?.job_id) {
        setJobId(primaryJob.job_id);
        startPolling(primaryJob.job_id);
      }
    } catch (err) {
      setGenerateError(
        err instanceof Error ? err.message : "An unexpected error occurred."
      );
    } finally {
      setIsGenerating(false);
    }
  };

  const handleGenerate = () => _doGenerate();

  /** Re-roll: generate again with a new random seed (positive signed 32-bit integer range) */
  const handleReRoll = () => {
    const newSeed = Math.floor(Math.random() * 0x7FFFFFFF);
    setForm((f) => ({ ...f, variationSeed: newSeed }));
    _doGenerate(newSeed);
  };

  // ---------------------------------------------------------------------------
  // Download handler
  // ---------------------------------------------------------------------------

  const handleDownload = async () => {
    if (isDownloading) return;

    setIsDownloading(true);
    setDownloadError(null);

    const filename = `arrangement-${jobId ?? "render"}.wav`;

    try {
      const signedUrl = jobStatus?.output_files?.find(
        (f) => f.content_type?.startsWith("audio") && f.signed_url
      )?.signed_url;

      if (signedUrl) {
        // Primary path: use the presigned URL — no extra round-trip needed
        const resolvedUrl = signedUrl.startsWith("http")
          ? signedUrl
          : `${BACKEND_BASE_URL}${signedUrl}`;
        console.log("[download] using signed URL:", resolvedUrl);
        const a = document.createElement("a");
        a.href = resolvedUrl;
        a.download = filename;
        a.click();
        return;
      }

      // Fallback: blob endpoint (requires arrangement_id; not available in
      // the render-async flow but kept for backward-compat with old sessions)
      if (generateResponse && "arrangement_id" in generateResponse &&
          (generateResponse as { arrangement_id?: number | null }).arrangement_id) {
        const arrId = (generateResponse as { arrangement_id: number }).arrangement_id;
        console.log("[download] falling back to blob endpoint, arrangement_id:", arrId);
        const blob = await downloadArrangement(arrId);
        const objectUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = objectUrl;
        a.download = `arrangement-${arrId}.wav`;
        a.click();
        URL.revokeObjectURL(objectUrl);
        return;
      }

      throw new Error(
        "Audio file URL not available. Please wait for the render to complete or try again."
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Download failed. Please try again.";
      console.error("[download] failed:", message);
      setDownloadError(message);
    } finally {
      setIsDownloading(false);
    }
  };

  // ---------------------------------------------------------------------------
  // DAW export handler
  // ---------------------------------------------------------------------------

  const handleDawExport = async () => {
    if (isDawExporting) return;

    setIsDawExporting(true);
    setDawExportError(null);

    // DAW export requires an arrangement_id — not present in the render-async flow.
    const arrId =
      generateResponse && "arrangement_id" in generateResponse
        ? (generateResponse as { arrangement_id?: number | null }).arrangement_id
        : null;

    if (!arrId) {
      setDawExportError("DAW export is not available for this render job.");
      setIsDawExporting(false);
      return;
    }

    try {
      const info = await getDawExportInfo(arrId);
      if (!info.ready_for_export) {
        throw new Error(info.message ?? "Arrangement is not ready for DAW export.");
      }

      if (info.download_url) {
        const resolvedUrl = info.download_url.startsWith("http")
          ? info.download_url
          : `${BACKEND_BASE_URL}${info.download_url}`;
        const a = document.createElement("a");
        a.href = resolvedUrl;
        a.download = `arrangement-${arrId}-daw-export.zip`;
        a.click();
        return;
      }

      const blob = await downloadDawExport(arrId);
      const objectUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = `arrangement-${arrId}-daw-export.zip`;
      a.click();
      URL.revokeObjectURL(objectUrl);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to download DAW export.";
      setDawExportError(message);
    } finally {
      setIsDawExporting(false);
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

  const audioSrc: string | null = (() => {
    if (!isCompleted) return null;
    const signedUrl = jobStatus?.output_files?.find(
      (f) => f.content_type?.startsWith("audio") && f.signed_url
    )?.signed_url;
    if (signedUrl) {
      return signedUrl.startsWith("http")
        ? signedUrl
        : `${BACKEND_BASE_URL}${signedUrl}`;
    }
    return null;
  })();

  const expectedDurationLabel: string | null = null;

  // Section preview not available in render-async flow
  const sectionPreview: unknown[] = [];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="mx-auto max-w-2xl p-8 space-y-6">
      <h1 className="text-3xl font-bold">Generate Arrangement</h1>

      {/* Form */}
      <section className="space-y-4">
        {/* Loop ID */}
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

        {/* Duration */}
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="targetSeconds">
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

        {/* Genre dropdown */}
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="genre">
            Genre
          </label>
          <select
            id="genre"
            className="w-full border rounded px-3 py-2 bg-white"
            value={form.genre}
            onChange={(e) => setForm((f) => ({ ...f, genre: e.target.value }))}
          >
            {GENRE_OPTIONS.map((g) => (
              <option key={g} value={g}>
                {g.charAt(0).toUpperCase() + g.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Vibe dropdown */}
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="vibe">
            Vibe
          </label>
          <select
            id="vibe"
            className="w-full border rounded px-3 py-2 bg-white"
            value={form.vibe}
            onChange={(e) => setForm((f) => ({ ...f, vibe: e.target.value }))}
          >
            <option value="">— None —</option>
            {VIBE_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Variation intensity slider */}
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="variationIntensity">
            Variation Intensity:{" "}
            <span className="font-normal text-gray-600">
              {form.variationIntensity === 0
                ? "Safe"
                : form.variationIntensity >= 0.9
                ? "Experimental"
                : form.variationIntensity.toFixed(1)}
            </span>
          </label>
          <input
            id="variationIntensity"
            type="range"
            min={0}
            max={1}
            step={0.05}
            className="w-full"
            value={form.variationIntensity}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                variationIntensity: parseFloat(e.target.value),
              }))
            }
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>0 — Safe</span>
            <span>1 — Experimental</span>
          </div>
        </div>

        {/* Style text */}
        <div>
          <label className="block text-sm font-medium mb-1" htmlFor="styleText">
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

        {/* Seed display (read-only) */}
        {form.variationSeed !== null && (
          <p className="text-xs text-gray-500">
            Seed: <code className="font-mono">{form.variationSeed}</code>
          </p>
        )}

        {/* Action buttons */}
        <div className="flex gap-2">
          <button
            onClick={handleGenerate}
            disabled={isGenerating || isInProgress}
            className="flex-1 bg-blue-600 text-white py-2 rounded disabled:opacity-50"
          >
            {isGenerating ? "Requesting…" : "Generate Arrangement"}
          </button>

          <button
            onClick={handleReRoll}
            disabled={isGenerating || isInProgress}
            title="Regenerate with a new random seed"
            className="px-4 bg-indigo-500 text-white py-2 rounded disabled:opacity-50"
          >
            🎲 Re-roll
          </button>
        </div>

        {generateError && (
          <p className="text-red-600 text-sm">{generateError}</p>
        )}
      </section>

      {/* Section timeline preview */}
      {sectionPreview.length > 0 && (
        <section className="border rounded p-4 space-y-2">
          <h2 className="font-semibold text-lg">Section Timeline</h2>
          <div className="flex flex-wrap gap-1">
            {(sectionPreview as Array<{ name: string; bars: number; energy: number }>).map(
              (section, idx) => {
                const sectionKey = section.name
                  .toLowerCase()
                  .replace(/\s+\d+$/, "")
                  .replace(/\s+/g, "_");
                const colorClass =
                  SECTION_ENERGY_COLORS[sectionKey] ?? "bg-gray-100 text-gray-700";
                return (
                  <div
                    key={idx}
                    className={`flex flex-col items-center px-2 py-1 rounded text-xs ${colorClass}`}
                    title={`Energy: ${(section.energy * 100).toFixed(0)}%`}
                  >
                    <span className="font-semibold">{section.name}</span>
                    <span className="opacity-70">{section.bars}b</span>
                  </div>
                );
              }
            )}
          </div>
          <p className="text-xs text-gray-500">
            Color: <span className="text-blue-700">■ low</span>{" "}
            <span className="text-yellow-700">■ medium</span>{" "}
            <span className="text-red-700">■ high (hook)</span>
          </p>
        </section>
      )}

      {/* Job status */}
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

              {isInProgress && expectedDurationLabel && (
                <p className="text-sm text-gray-500">
                  Expected duration: {expectedDurationLabel}
                </p>
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
      {isCompleted && (
        <section className="space-y-3">
          {audioSrc && (
            <div>
              <p className="text-sm font-medium mb-1">
                Preview{expectedDurationLabel ? ` (${expectedDurationLabel})` : ""}
              </p>
              <audio
                controls
                src={audioSrc}
                className="w-full"
                preload="metadata"
              >
                Your browser does not support the audio element.
              </audio>
            </div>
          )}

          <button
            onClick={handleDownload}
            disabled={isDownloading}
            className="w-full bg-green-600 text-white py-2 rounded disabled:opacity-50"
          >
            {isDownloading ? "Downloading…" : "Download Arrangement (WAV)"}
          </button>
          {downloadError && (
            <p className="text-sm text-red-600">{downloadError}</p>
          )}

          <button
            onClick={handleDawExport}
            disabled={isDawExporting}
            className="w-full bg-purple-600 text-white py-2 rounded disabled:opacity-50"
          >
            {isDawExporting
              ? "Preparing DAW export…"
              : "Download DAW Export (ZIP)"}
          </button>
          {dawExportError && (
            <p className="text-sm text-red-600">{dawExportError}</p>
          )}
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
