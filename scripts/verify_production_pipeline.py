"""Production verification script for LoopArchitect API readiness and downloads."""

import os
import sys
from pathlib import Path
import urllib.error
import urllib.request
import json


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TEST_LOOP_ID = os.getenv("TEST_LOOP_ID")
TEST_ARRANGEMENT_ID = os.getenv("TEST_ARRANGEMENT_ID")


def call_json(path: str, expected_status: int = 200) -> dict:
    url = f"{BASE_URL}{path}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status_code = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        body = exc.read().decode("utf-8", errors="ignore")

    if status_code != expected_status:
        print(f"❌ {path} -> {status_code}: {body}")
        raise RuntimeError(f"Request failed: {path}")

    data = json.loads(body)
    print(f"✅ {path} -> {status_code}")
    return data


def verify_download(arrangement_id: str) -> None:
    path = f"/api/v1/arrangements/{arrangement_id}/download"
    url = f"{BASE_URL}{path}"

    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                body = response.read().decode("utf-8", errors="ignore")
                print(f"❌ {path} -> {response.status}: {body}")
                raise RuntimeError("Download verification failed")

            output_dir = Path("scripts") / "artifacts"
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"arrangement_{arrangement_id}.bin"

            size = 0
            with open(out_path, "wb") as f:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(f"❌ {path} -> {exc.code}: {body}")
        raise RuntimeError("Download verification failed") from exc

    print(f"✅ {path} -> downloaded {size} bytes to {out_path}")


def main() -> int:
    print(f"Using BASE_URL={BASE_URL}")

    try:
        # Prefer granular health endpoints when available, but gracefully
        # fall back to /api/v1/health for environments that only expose one.
        try:
            live = call_json("/api/v1/health/live")
            ready = call_json("/api/v1/health/ready")

            if not live.get("ok"):
                raise RuntimeError("Live check returned ok=false")
            if not ready.get("ok"):
                raise RuntimeError("Ready check returned ok=false")
        except Exception:
            health = call_json("/api/v1/health")
            status_ok = health.get("ok") is True or health.get("status") == "ok"
            if not status_ok:
                raise RuntimeError("Health check returned non-ok status")

        if TEST_LOOP_ID:
            call_json(f"/api/v1/loops/{TEST_LOOP_ID}")
            call_json("/api/v1/loops/")

        if TEST_ARRANGEMENT_ID:
            verify_download(TEST_ARRANGEMENT_ID)

    except Exception as exc:
        print(f"❌ Verification failed: {exc}")
        return 1

    print("✅ Production pipeline verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
