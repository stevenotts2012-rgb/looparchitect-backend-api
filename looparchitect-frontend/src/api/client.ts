/**
 * LoopArchitect API Client
 *
 * Handles all communication with the backend API.
 *
 * Request routing
 * ───────────────
 * LOCAL DEV (NEXT_PUBLIC_API_URL unset — recommended):
 *   All non-upload paths are sent as relative URLs (e.g. /api/v1/…) so
 *   Next.js's catch-all proxy at src/app/api/[...path]/route.ts forwards them
 *   to the FastAPI backend at http://127.0.0.1:8000.
 *   The browser never contacts the backend directly; CORS is not an issue.
 *
 * PRODUCTION (NEXT_PUBLIC_API_URL set):
 *   Requests go directly from the browser to the configured backend origin.
 *   The backend must include the frontend origin in its CORS allowlist.
 *
 * Upload flow:
 *   Multipart file uploads ALWAYS go directly to the Railway backend to avoid
 *   Vercel's 4.5 MB body-size limit (HTTP 413 Content Too Large).
 *   browser → POST https://web-production-3afc5.up.railway.app/api/v1/loops/with-file
 *          → FastAPI POST /api/v1/loops/with-file
 *
 * Polling for job status uses GET /api/v1/jobs/{job_id} — the real
 * render-job endpoint — rather than guessing state from the arrangements list.
 */

/**
 * Base URL for all non-file API calls.
 *
 * LOCAL DEV: Leave NEXT_PUBLIC_API_URL unset.  The empty string causes fetch
 * to send relative URLs (e.g. /api/v1/…) which are forwarded to the FastAPI
 * backend (http://127.0.0.1:8000) by the Next.js catch-all proxy.
 *
 * PRODUCTION: Set NEXT_PUBLIC_API_URL to the deployed backend origin so the
 * browser contacts it directly (e.g. https://web-production-3afc5.up.railway.app).
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

/**
 * Base URL used exclusively for multipart file uploads.
 *
 * File uploads must bypass the Vercel deployment to avoid the 4.5 MB
 * request-body limit (HTTP 413 Content Too Large).  This constant always
 * resolves to an absolute backend origin so the browser sends the multipart
 * POST directly to Railway.
 *
 * Resolution order (first non-empty value wins):
 *   1. NEXT_PUBLIC_UPLOAD_URL  — dedicated upload override (recommended for
 *      production; set to https://web-production-3afc5.up.railway.app)
 *   2. NEXT_PUBLIC_API_URL     — shared backend origin (also works)
 *   3. "https://web-production-3afc5.up.railway.app"  — hard-coded fallback
 *      so uploads work even when neither env var is set in the Vercel build.
 *
 * Note: In local development where both env vars are unset, uploads will go
 * directly to the Railway backend (not through the Next.js proxy).  Set
 * NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 in .env.local to route local
 * uploads to your local FastAPI instance instead.
 */
const UPLOAD_BACKEND_URL =
  process.env.NEXT_PUBLIC_UPLOAD_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://web-production-3afc5.up.railway.app";

/**
 * Absolute backend URL used for large-body downloads (DAW export ZIP, audio
 * files) that must bypass the Vercel 4.5 MB response-body limit.
 *
 * Same resolution order as UPLOAD_BACKEND_URL so both always point to the
 * same Railway instance.
 */
export const BACKEND_BASE_URL: string = UPLOAD_BACKEND_URL;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Mirrors the backend LoopResponse Pydantic schema (app/schemas/loop.py).
 *
 * Field naming notes:
 *   tempo / bpm         — Both carry the beats-per-minute value. `tempo` is the
 *                         legacy field; `bpm` is the analysed value populated by
 *                         the audio analyser.  Either may be populated depending
 *                         on how the loop was created.
 *   key / musical_key   — Both carry the musical key (e.g. "C minor"). `key` is
 *                         the legacy field; `musical_key` is set by the analyser.
 */
export interface LoopResponse {
  id: number;
  name: string;
  filename: string | null;
  file_url: string | null;
  file_key: string | null;
  title: string | null;
  /** Legacy BPM field (user-supplied). */
  tempo: number | null;
  /** Analysed BPM (populated by the audio analyser on upload). */
  bpm: number | null;
  bars: number | null;
  /** Legacy musical key field (user-supplied). */
  key: string | null;
  /** Analysed musical key (populated by the audio analyser on upload). */
  musical_key: string | null;
  genre: string | null;
  duration_seconds: number | null;
  status: string | null;
  processed_file_url: string | null;
  analysis_json: string | null;
  stem_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface UploadLoopMetadata {
  name: string;
  tempo?: number;
  key?: string;
  genre?: string;
}

export interface GenerateArrangementRequest {
  loop_id: number;
  target_seconds?: number;
  genre?: string;
  intensity?: string;
  style_text_input?: string;
  use_ai_parsing?: boolean;
  style_params?: Record<string, number | string>;
  producer_moves?: string[];
  variation_count?: number;
  seed?: number | string;
  /** Explicit genre for template selection: trap | drill | rnb | rage */
  genre_override?: string;
  /** Vibe/mood modifier: dark | emotional | hype | pain | rage | ambient | cinematic */
  vibe_override?: string;
  /** Deterministic seed for template, vibe, and variation engines */
  variation_seed?: number;
  /** Variation intensity 0.0 (safe) → 1.0 (experimental) */
  variation_intensity?: number;
}

export interface GenerateArrangementResponse {
  arrangement_id: number | null;
  loop_id: number;
  status: string | null;
  /** Primary render job ID — use this with getJobStatus() to poll progress. */
  job_id: string | null;
  /** Convenience URL: /api/v1/jobs/{job_id} */
  poll_url: string | null;
  render_job_ids: string[];
  candidates: {
    arrangement_id: number;
    status: string;
    render_job_id: string | null;
  }[];
  structure_preview: unknown[];
  /**
   * Target duration in seconds (mirrors the generate request's target_seconds).
   * Present in all responses so the preview player can show an expected duration
   * immediately — before the render job completes and returns an audioUrl.
   */
  target_seconds: number | null;
  /**
   * Tempo of the source loop in BPM.
   * Combined with structure_preview bar counts this allows per-section timestamps
   * to be calculated client-side.
   */
  bpm: number | null;
}

/**
 * UI-facing job status.
 *
 * The backend stores terminal success as "succeeded" internally; the API
 * response normalises this to "completed" so the frontend only needs to
 * handle: queued | processing | completed | failed
 */
export type JobStatus = "queued" | "running" | "processing" | "success" | "done" | "completed" | "failed" | "error" | "cancelled";

export interface JobStatusResponse {
  job_id: string;
  loop_id: number;
  job_type: string;
  /** queued | processing | completed | failed */
  status: JobStatus;
  progress: number;
  progress_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  output_files: {
    name: string;
    s3_key: string;
    content_type: string;
    signed_url: string | null;
  }[] | null;
  error_message: string | null;
  retry_count: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`API ${path} returned ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Async render job  (primary generate path)
// ---------------------------------------------------------------------------

/**
 * Configuration body for POST /api/v1/loops/{loop_id}/render-async.
 *
 * Maps to the backend `RenderConfig` Pydantic model.
 */
export interface RenderAsyncConfig {
  genre?: string;
  length_seconds?: number;
  energy?: string;
  variations?: number;
  variation_styles?: string[];
  custom_style?: string;
}

/**
 * Response from POST /api/v1/loops/{loop_id}/render-async.
 *
 * Maps to the backend `RenderJobResponse` Pydantic model.
 * Use `job_id` with `getJobStatus()` to poll for progress.
 */
export interface RenderAsyncVariationJob {
  job_id: string;
  variation_index: number;
  variation_seed: number;
  status: string;
  poll_url: string;
  deduplicated: boolean;
}

export interface RenderAsyncResponse {
  loop_id: number;
  variation_count: number;
  requested_length_seconds: number | null;
  actual_length_seconds: number | null;
  section_sequence: string[];
  jobs: RenderAsyncVariationJob[];
}

/**
 * Enqueue an async render job for a loop.
 *
 * Calls POST /api/v1/loops/{loop_id}/render-async and returns immediately
 * with a `job_id`.  Use `getJobStatus(job_id)` to poll for progress.
 *
 * Debug events emitted in non-production environments:
 *   render_async_request_sent  — before the POST is sent
 *   render_job_id_received     — after the POST returns with a job_id
 */
export async function renderAsync(
  loopId: number,
  config?: RenderAsyncConfig
): Promise<RenderAsyncResponse> {
  if (process.env.NODE_ENV !== "production") {
    console.debug("[render_async_request_sent]", { loopId, config });
  }
  const response = await apiFetch<RenderAsyncResponse>(
    `/api/v1/loops/${loopId}/render-async`,
    {
      method: "POST",
      body: JSON.stringify(config ?? {}),
    }
  );
  if (process.env.NODE_ENV !== "production") {
    console.debug("[render_job_id_received]", {
      job_id: response.job_id,
      loop_id: response.loop_id,
      status: response.status,
    });
  }
  return response;
}

// ---------------------------------------------------------------------------
// Arrangement generation  (legacy — kept for reference; use renderAsync)
// ---------------------------------------------------------------------------

/**
 * @deprecated Use renderAsync() instead.
 *
 * Trigger arrangement generation for a loop.
 *
 * The returned `job_id` (and `poll_url`) should be used with `getJobStatus()`
 * to track progress.  Do NOT poll `/arrangements/{id}` for status — use the
 * real job endpoint instead.
 */
export async function generateArrangement(
  request: GenerateArrangementRequest
): Promise<GenerateArrangementResponse> {
  return apiFetch<GenerateArrangementResponse>(
    "/api/v1/arrangements/generate",
    {
      method: "POST",
      body: JSON.stringify(request),
    }
  );
}

// ---------------------------------------------------------------------------
// Job status polling  ← real endpoint, not arrangements list
// ---------------------------------------------------------------------------

/**
 * Fetch the current status of a render job.
 *
 * Endpoint: GET /api/v1/jobs/{job_id}
 *
 * Terminal states that should stop polling:
 *   - "completed"  (previously "succeeded" in DB; normalised by backend)
 *   - "failed"
 */
export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
  return apiFetch<JobStatusResponse>(`/api/v1/jobs/${jobId}`);
}

/**
 * Returns true when a job has reached a terminal state and polling should stop.
 */
export function isTerminalJobStatus(status: JobStatus): boolean {
  return ["success", "done", "completed", "failed", "error", "cancelled"].includes(status);
}

// ---------------------------------------------------------------------------
// Loop upload
// ---------------------------------------------------------------------------

/**
 * Upload an audio file and create a Loop record.
 *
 * Sends a multipart/form-data POST directly to the Railway backend.
 * The request bypasses the Vercel/Next.js proxy to avoid the 4.5 MB
 * body-size limit (HTTP 413 Content Too Large).
 *
 * Request path: browser → POST https://web-production-3afc5.up.railway.app/api/v1/loops/with-file
 *                       → FastAPI POST /api/v1/loops/with-file
 *
 * The `Content-Type` header is intentionally omitted so the browser
 * can set the correct multipart boundary automatically.
 *
 * @param file     Audio file (WAV or MP3)
 * @param metadata Loop metadata — at minimum `name` is required
 * @returns        Created Loop record including the new `id`
 */
export async function uploadLoop(
  file: File,
  metadata: UploadLoopMetadata
): Promise<LoopResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("loop_in", JSON.stringify(metadata));

  const response = await fetch(`${UPLOAD_BACKEND_URL}/api/v1/loops/with-file`, {
    method: "POST",
    body: formData,
    // Do NOT set Content-Type — the browser sets it automatically,
    // including the required multipart boundary parameter.
  });

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText);
    throw new Error(`Upload failed (${response.status}): ${text}`);
  }

  return response.json() as Promise<LoopResponse>;
}

// ---------------------------------------------------------------------------
// Arrangement download
// ---------------------------------------------------------------------------

/**
 * Milliseconds before a download fetch is aborted and an error is shown.
 * Large audio files can take time; 60 s is generous while still preventing
 * an infinite spinner.
 */
export const DOWNLOAD_TIMEOUT_MS = 60_000;

/**
 * Download the generated arrangement WAV as a Blob.
 *
 * Uses BACKEND_BASE_URL directly to bypass Vercel's 4.5 MB response-body
 * limit for large audio files.
 *
 * Enforces a 60-second timeout via AbortController so the loading state
 * is always cleared even if the backend stalls.
 */
export async function downloadArrangement(arrangementId: number): Promise<Blob> {
  const url = `${BACKEND_BASE_URL}/api/v1/arrangements/${arrangementId}/download`;
  console.log("[download] endpoint called:", url);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    console.warn("[download] timeout reached – aborting fetch");
    controller.abort();
  }, DOWNLOAD_TIMEOUT_MS);

  try {
    const response = await fetch(url, { signal: controller.signal });
    console.log("[download] response status:", response.status, response.statusText);

    if (!response.ok) {
      throw new Error(
        `Download failed: ${response.status} ${response.statusText}`
      );
    }

    const blob = await response.blob();
    console.log("[download] blob received, size:", blob.size, "bytes");
    return blob;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        "Download timed out after 60 seconds. Check your connection and try again."
      );
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// DAW export
// ---------------------------------------------------------------------------

/**
 * Response from GET /api/v1/arrangements/{id}/daw-export
 *
 * When ready_for_export is true the ZIP has been generated (or was already
 * cached) and download_url points to the download endpoint.
 */
export interface DawExportInfoResponse {
  arrangement_id: number;
  ready_for_export: boolean;
  /** Present when arrangement is not yet done. */
  status?: string;
  message?: string;
  supported_daws?: string[];
  /** Relative path to the download endpoint, e.g. /api/v1/arrangements/1/daw-export/download */
  download_url?: string;
  export_s3_key?: string;
  contents?: {
    stems: string[];
    midi: string[];
    metadata: string[];
  };
  sections?: unknown[];
  midi_note?: string;
}

/**
 * Trigger DAW export ZIP generation and return metadata.
 *
 * Calling this endpoint causes the backend to build and cache the ZIP if it
 * does not already exist.  Call downloadDawExport() afterwards to fetch the
 * file.
 */
export async function getDawExportInfo(
  arrangementId: number
): Promise<DawExportInfoResponse> {
  return apiFetch<DawExportInfoResponse>(
    `/api/v1/arrangements/${arrangementId}/daw-export`
  );
}

/**
 * Download the DAW export ZIP as a Blob.
 *
 * Uses BACKEND_BASE_URL directly (bypasses Vercel's 4.5 MB response-body
 * limit — the same reason uploads bypass the proxy).
 *
 * Always call getDawExportInfo() first so the backend generates the ZIP.
 *
 * Enforces a 60-second timeout via AbortController so the loading state
 * is always cleared even if the backend stalls.
 */
export async function downloadDawExport(arrangementId: number): Promise<Blob> {
  const url = `${BACKEND_BASE_URL}/api/v1/arrangements/${arrangementId}/daw-export/download`;
  console.log("[daw-export] endpoint called:", url);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    console.warn("[daw-export] timeout reached – aborting fetch");
    controller.abort();
  }, DOWNLOAD_TIMEOUT_MS);

  try {
    const response = await fetch(url, { signal: controller.signal });
    console.log("[daw-export] response status:", response.status, response.statusText);

    if (!response.ok) {
      throw new Error(
        `DAW export download failed: ${response.status} ${response.statusText}`
      );
    }

    const blob = await response.blob();
    console.log("[daw-export] blob received, size:", blob.size, "bytes");
    return blob;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        "DAW export download timed out after 60 seconds. Check your connection and try again."
      );
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}
