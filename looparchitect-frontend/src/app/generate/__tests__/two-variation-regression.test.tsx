import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import React from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({ get: () => null }),
}));

vi.mock("@/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/api/client")>("@/api/client");
  return {
    ...actual,
    renderAsync: vi.fn(),
    getJobStatus: vi.fn(),
  };
});

import GeneratePage from "../page";
import * as client from "@/api/client";

describe("2-variation production lock", () => {
  it("sends variation_count=2 and renders exactly two cards", async () => {
    vi.mocked(client.renderAsync).mockResolvedValue({
      loop_id: 1,
      variation_count: 2,
      requested_length_seconds: 60,
      actual_length_seconds: 60,
      section_sequence: ["intro", "verse"],
      jobs: [
        { job_id: "job-1", variation_index: 0, variation_seed: 10, status: "queued", poll_url: "/api/v1/jobs/job-1", deduplicated: false },
        { job_id: "job-2", variation_index: 1, variation_seed: 11, status: "failed", poll_url: "/api/v1/jobs/job-2", deduplicated: false },
      ],
    });
    vi.mocked(client.getJobStatus).mockResolvedValue({
      job_id: "job-1", loop_id: 1, job_type: "render", status: "failed", progress: 100,
      progress_message: "Failed", created_at: new Date().toISOString(), started_at: null, finished_at: null,
      output_files: [], error_message: "boom", retry_count: 0,
    });

    render(<GeneratePage />);
    expect(screen.getByRole("button", { name: /generate 2 new variations/i })).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/loop id/i), { target: { value: "1" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /generate 2 new variations/i }));
    });

    await waitFor(() => expect(client.renderAsync).toHaveBeenCalled());
    expect(vi.mocked(client.renderAsync).mock.calls[0][1]).toMatchObject({ variation_count: 2 });

    expect(screen.getByText(/variation 1/i)).toBeInTheDocument();
    expect(screen.getByText(/variation 2/i)).toBeInTheDocument();
    expect(screen.queryByText(/variation 3/i)).not.toBeInTheDocument();
    expect(screen.getByText(/status: failed/i)).toBeInTheDocument();
  });
});
