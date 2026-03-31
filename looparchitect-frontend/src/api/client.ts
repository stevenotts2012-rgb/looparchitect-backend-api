/**
 * LoopArchitect API Client
 *
 * Handles all communication with the backend API.
 *
 * Request routing:
 *   - In development (NEXT_PUBLIC_API_URL unset) all paths are sent as
 *     relative URLs (e.g. /api/v1/…) so Next.js's catch-all proxy at
 *     src/app/api/[...path]/route.ts forwards them to the FastAPI backend.
 *   - When NEXT_PUBLIC_API_URL is explicitly set (e.g. in production
 *     without a proxy), requests go directly to that origin.
 *
 * Upload flow:
 *   browser → POST /api/v1/loops/with-file (relative)
 *          → Next.js proxy (src/app/api/[...path]/route.ts)
 *          → FastAPI POST /api/v1/loops/with-file
 *
 * Polling for job status uses GET /api/v1/jobs/{job_id} — the real render-job
 * endpoint — rather than guessing state from the arrangements list.
 */

/**
 * Base URL for all API calls.
 *
 * If NEXT_PUBLIC_API_URL is set, requests go directly to that origin.
 * When it is empty / unset, the empty string causes fetch to send
 * relative URLs (e.g. /api/v1/…) which are handled by the Next.js
 * catch-all proxy and forwarded to the FastAPI backend.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

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
}

/**
 * UI-facing job status.
 *
 * The backend stores terminal success as "succeeded" internally; the API
 * response normalises this to "completed" so the frontend only needs to
 * handle: queued | processing | completed | failed
 */
export type JobStatus = "queued" | "processing" | "completed" | "failed";

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
// Arrangement generation
// ---------------------------------------------------------------------------

/**
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
  return status === "completed" || status === "failed";
}

// ---------------------------------------------------------------------------
// Loop upload
// ---------------------------------------------------------------------------

/**
 * Upload an audio file and create a Loop record.
 *
 * Sends a multipart/form-data POST to POST /api/v1/loops/with-file.
 *
 * Request path: browser → Next.js proxy (/api/v1/loops/with-file)
 *               → FastAPI POST /api/v1/loops/with-file
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

  const response = await fetch(`${API_BASE}/api/v1/loops/with-file`, {
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
 * Download the generated arrangement WAV as a Blob.
 */
export async function downloadArrangement(arrangementId: number): Promise<Blob> {
  const response = await fetch(
    `${API_BASE}/api/v1/arrangements/${arrangementId}/download`
  );
  if (!response.ok) {
    throw new Error(
      `Download failed: ${response.status} ${response.statusText}`
    );
  }
  return response.blob();
}
