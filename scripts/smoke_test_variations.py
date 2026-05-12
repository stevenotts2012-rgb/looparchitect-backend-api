#!/usr/bin/env python3
"""Production smoke test for 3-variation render pipeline."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Dict, List

import requests

TERMINAL = {"succeeded", "failed", "timeout", "missing_output", "completed"}


def _log(event: str, **fields) -> None:
    kv = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"{event} {kv}".strip())


def run(base_url: str, loop_id: int, timeout_seconds: int, poll_interval: float) -> int:
    _log("PRODUCTION_VARIATION_SMOKE_STARTED", base_url=base_url, loop_id=loop_id, variation_count=3)
    r = requests.post(
        f"{base_url.rstrip('/')}/api/v1/loops/{loop_id}/render-async",
        json={"variation_count": 3},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    jobs: List[Dict] = payload.get("jobs") or []
    if len(jobs) < 3:
        _log("PRODUCTION_VARIATION_SMOKE_FAILED", reason="fewer_than_3_jobs", returned_jobs=len(jobs))
        return 2

    start = time.time()
    final: Dict[str, Dict] = {}
    while time.time() - start <= timeout_seconds:
        remaining = []
        for j in jobs:
            jid = j["job_id"]
            jr = requests.get(f"{base_url.rstrip('/')}/api/v1/jobs/{jid}", timeout=30)
            jr.raise_for_status()
            st = (jr.json().get("status") or "").lower()
            if st in TERMINAL:
                final[jid] = {"status": st, "variation_index": j.get("variation_index"), "personality": j.get("personality")}
                _log("PRODUCTION_VARIATION_SMOKE_JOB_TERMINAL", job_id=jid, variation_index=j.get("variation_index"), personality=j.get("personality"), status=st)
            else:
                remaining.append(j)
        if not remaining:
            _log("PRODUCTION_VARIATION_SMOKE_PASSED", terminal_jobs=len(final))
            for item in sorted(final.values(), key=lambda x: x.get("variation_index", 99)):
                print(f"variation_index={item['variation_index']} personality={item['personality']} status={item['status']}")
            return 0
        jobs = remaining
        time.sleep(poll_interval)

    _log("PRODUCTION_VARIATION_SMOKE_FAILED", reason="processing_timeout", non_terminal_jobs=len(jobs), timeout_seconds=timeout_seconds)
    return 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--loop-id", required=True, type=int)
    ap.add_argument("--timeout-seconds", type=int, default=900)
    ap.add_argument("--poll-interval", type=float, default=5.0)
    args = ap.parse_args()
    try:
        return run(args.base_url, args.loop_id, args.timeout_seconds, args.poll_interval)
    except Exception as exc:
        _log("PRODUCTION_VARIATION_SMOKE_FAILED", reason="exception", error=str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
