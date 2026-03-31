/**
 * LoopArchitect API Client
 *
 * Handles all communication with the backend API.
 * Polling for job status uses GET /api/v1/jobs/{job_id} — the real render-job
 * endpoint — rather than guessing state from the arrangements list.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
