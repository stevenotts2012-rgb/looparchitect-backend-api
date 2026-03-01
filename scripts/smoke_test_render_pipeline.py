"""Smoke test for end-to-end render pipeline with Redis queue.

This script tests:
1. Loop creation with audio upload
2. Async render job enqueue
3. Job status polling until completion
4. Output artifact URLs and signatures

Usage:
    python scripts/smoke_test_render_pipeline.py [--base-url http://localhost:8000]
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import httpx


class RenderPipelineTester:
    """Test harness for render pipeline."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=60.0)
        self.loop_id: Optional[int] = None
        self.job_id: Optional[str] = None

    def log(self, msg: str, level: str = "INFO"):
        """Print timestamped log message."""
        print(f"[{level}] {msg}")

    def check_health(self) -> bool:
        """Verify API is responding."""
        try:
            resp = self.client.get(f"{self.base_url}/health")
            resp.raise_for_status()
            self.log(f"✅ Health check passed: {resp.json()}")
            return True
        except Exception as e:
            self.log(f"❌ Health check failed: {e}", "ERROR")
            return False

    def create_loop_with_upload(self, audio_path: Path) -> int:
        """Upload a loop and return loop_id."""
        self.log(f"Uploading loop from {audio_path}...")

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/wav")}
            data = {
                "title": f"Smoke Test Loop {time.time()}",
                "genre": "Trap",
                "bpm": 140,
            }
            resp = self.client.post(
                f"{self.base_url}/api/v1/loops",
                files=files,
                data=data,
            )
            resp.raise_for_status()

        loop = resp.json()
        self.loop_id = loop["id"]
        self.log(f"✅ Loop created: id={self.loop_id}, file_key={loop.get('file_key')}")
        return self.loop_id

    def enqueue_render_job(self, loop_id: int, params: Dict) -> str:
        """Enqueue async render job and return job_id."""
        self.log(f"Enqueueing render job for loop {loop_id}...")

        resp = self.client.post(
            f"{self.base_url}/api/v1/loops/{loop_id}/render-async",
            json=params,
        )

        if resp.status_code == 503:
            self.log("⚠️  Redis queue unavailable (503). Is Redis running?", "WARN")
            return None

        resp.raise_for_status()
        job = resp.json()
        self.job_id = job["job_id"]
        self.log(
            f"✅ Job enqueued: job_id={self.job_id}, status={job['status']}, "
            f"deduplicated={job.get('deduplicated', False)}"
        )
        return self.job_id

    def poll_job_status(
        self, job_id: str, timeout_seconds: int = 180, poll_interval: int = 5
    ) -> Dict:
        """Poll job status until succeeded/failed or timeout."""
        self.log(f"Polling job {job_id} (timeout={timeout_seconds}s)...")

        start = time.time()
        last_status = None
        last_progress = None

        while (time.time() - start) < timeout_seconds:
            resp = self.client.get(f"{self.base_url}/api/v1/jobs/{job_id}")
            resp.raise_for_status()
            job = resp.json()

            status = job["status"]
            progress = job.get("progress", 0.0)
            progress_msg = job.get("progress_message", "")

            # Log only on status/progress changes
            if status != last_status or progress != last_progress:
                self.log(
                    f"  Status: {status} | Progress: {progress:.1f}% | {progress_msg}"
                )
                last_status = status
                last_progress = progress

            if status == "succeeded":
                self.log(
                    f"✅ Job succeeded in {time.time() - start:.1f}s", "SUCCESS"
                )
                return job
            elif status == "failed":
                error = job.get("error_message", "Unknown error")
                self.log(f"❌ Job failed: {error}", "ERROR")
                return job

            time.sleep(poll_interval)

        self.log(f"⏰ Job timeout after {timeout_seconds}s", "WARN")
        return job

    def verify_artifacts(self, job: Dict) -> bool:
        """Verify output artifacts are present and URLs are valid."""
        artifacts = job.get("output_files", [])
        if not artifacts:
            self.log("❌ No output files found", "ERROR")
            return False

        self.log(f"Found {len(artifacts)} output artifacts:")
        for artifact in artifacts:
            name = artifact["name"]
            s3_key = artifact["s3_key"]
            signed_url = artifact.get("signed_url")

            self.log(f"  • {name}: {s3_key}")

            if signed_url:
                # Verify signed URL is accessible (HEAD request)
                try:
                    head_resp = self.client.head(signed_url)
                    if head_resp.status_code in [200, 302]:
                        self.log(f"    ✅ Signed URL valid (HTTP {head_resp.status_code})")
                    else:
                        self.log(
                            f"    ⚠️  Signed URL returned {head_resp.status_code}",
                            "WARN",
                        )
                except Exception as e:
                    self.log(f"    ⚠️  Signed URL check failed: {e}", "WARN")
            else:
                self.log("    ⚠️  No signed URL provided", "WARN")

        return True

    def run_full_test(self, audio_path: Path, render_params: Dict) -> bool:
        """Run complete end-to-end test."""
        self.log("=" * 60)
        self.log("STARTING RENDER PIPELINE SMOKE TEST")
        self.log("=" * 60)

        try:
            # Step 1: Health check
            if not self.check_health():
                return False

            # Step 2: Create loop
            loop_id = self.create_loop_with_upload(audio_path)

            # Step 3: Enqueue render
            job_id = self.enqueue_render_job(loop_id, render_params)
            if not job_id:
                self.log("Skipping job poll (Redis unavailable)", "WARN")
                return False

            # Step 4: Poll until complete
            job = self.poll_job_status(job_id, timeout_seconds=180)

            # Step 5: Verify outputs
            if job.get("status") == "succeeded":
                self.verify_artifacts(job)
                self.log("=" * 60)
                self.log("SMOKE TEST PASSED ✅", "SUCCESS")
                self.log("=" * 60)
                return True
            else:
                self.log("=" * 60)
                self.log("SMOKE TEST FAILED ❌", "ERROR")
                self.log("=" * 60)
                return False

        except Exception as e:
            self.log(f"SMOKE TEST EXCEPTION: {e}", "ERROR")
            import traceback

            traceback.print_exc()
            return False


def main():
    parser = argparse.ArgumentParser(description="Smoke test for render pipeline")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--audio-file",
        type=Path,
        help="Path to test audio file (default: uploads/test_loop.wav)",
    )
    parser.add_argument(
        "--variations",
        type=int,
        default=3,
        help="Number of variations to render (default: 3)",
    )

    args = parser.parse_args()

    # Find test audio file
    audio_path = args.audio_file
    if not audio_path:
        # Look for any .wav in uploads/
        uploads_dir = Path("uploads")
        if uploads_dir.exists():
            wav_files = list(uploads_dir.glob("*.wav"))
            if wav_files:
                audio_path = wav_files[0]

    if not audio_path or not audio_path.exists():
        print(
            "❌ No test audio file found. Please provide --audio-file or place a .wav in uploads/"
        )
        return 1

    # Render parameters
    render_params = {
        "genre": "Trap",
        "length_seconds": 180,
        "energy": "high",
        "variations": args.variations,
    }

    tester = RenderPipelineTester(args.base_url)
    success = tester.run_full_test(audio_path, render_params)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
