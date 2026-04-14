"""Feature completeness + integration acceptance tests."""

from __future__ import annotations

import io
import json
import wave
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydub import AudioSegment

from app.main import app
import app.db as db_module
from app.models.arrangement import Arrangement
from app.services.arrangement_jobs import run_arrangement_job
from app.services.arrangement_engine import render_phase_b_arrangement
from app.services.storage import storage
from app.config import settings


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


def _make_wav_bytes(duration_ms: int = 4000) -> bytes:
    """Build a valid WAV payload for upload tests."""
    buf = io.BytesIO()
    frame_rate = 44100
    channels = 1
    sample_width = 2
    frame_count = int(frame_rate * (duration_ms / 1000))

    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(frame_rate)
        wf.writeframes(b"\x00\x00" * frame_count)

    return buf.getvalue()


def test_api_create_loop_arrange_render_job_completes_and_plan_has_events():
    """API flow: create loop -> arrange -> generate -> worker completes with rich render plan."""
    client = TestClient(app)

    loop_meta = json.dumps({"name": "Audit Loop", "tempo": 120, "genre": "Trap"})
    upload_response = client.post(
        "/api/v1/loops/with-file",
        data={"loop_in": loop_meta},
        files={"file": ("audit.wav", _make_wav_bytes(), "audio/wav")},
        headers={"x-correlation-id": "test-audit-cid-1"},
    )
    assert upload_response.status_code == 201, upload_response.text
    loop_id = upload_response.json()["id"]

    arrange_response = client.post(
        f"/api/v1/arrange/{loop_id}",
        json={"duration_seconds": 180},
    )
    assert arrange_response.status_code == 200, arrange_response.text

    # Mock Redis enqueue path so test remains deterministic without external Redis.
    with patch(
        "app.routes.arrangements.is_redis_available",
        return_value=True,
    ), patch(
        "app.routes.arrangements.create_render_job",
        return_value=(SimpleNamespace(id="test-job-1"), False),
    ):
        generate_response = client.post(
            "/api/v1/arrangements/generate",
            json={
                "loop_id": loop_id,
                "target_seconds": 180,
                "style_text_input": "Southside type, aggressive trap",
                "use_ai_parsing": False,
            },
            headers={"x-correlation-id": "test-audit-cid-1"},
        )
    assert generate_response.status_code == 202, generate_response.text
    arrangement_id = generate_response.json()["arrangement_id"]
    assert generate_response.json()["render_job_ids"] == ["test-job-1"]

    # Run worker directly for deterministic completion assertion.
    run_arrangement_job(arrangement_id)

    db = db_module.SessionLocal()
    try:
        arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
        assert arrangement is not None
        assert arrangement.status == "done"
        assert arrangement.arrangement_json

        timeline = json.loads(arrangement.arrangement_json)
        assert len(timeline.get("sections", [])) >= 3
        assert len(timeline.get("events", [])) >= 10

        # In dev/local backend we also expect debug render plan artifact.
        if not storage.use_s3:
            from pathlib import Path

            debug_plan = Path.cwd() / "uploads" / f"{arrangement_id}_render_plan.json"
            assert debug_plan.exists()
            debug_payload = json.loads(debug_plan.read_text(encoding="utf-8"))
            assert debug_payload.get("events_count", 0) >= 10
    finally:
        db.close()


def test_style_direction_changes_render_plan_signature():
    """A/B style direction should produce different render plan signatures/profiles."""
    loop_audio = AudioSegment.silent(duration=4000)

    _, trap_timeline_json = render_phase_b_arrangement(
        loop_audio=loop_audio,
        bpm=120,
        target_seconds=150,
        style_params={"__archetype": "melodic_trap", "__raw_input": "Southside style"},
    )
    _, rnb_timeline_json = render_phase_b_arrangement(
        loop_audio=loop_audio,
        bpm=120,
        target_seconds=150,
        style_params={"__genre_hint": "R&B", "__raw_input": "smooth contemporary rnb"},
    )

    trap_timeline = json.loads(trap_timeline_json)
    rnb_timeline = json.loads(rnb_timeline_json)

    assert trap_timeline.get("render_profile", {}).get("genre_profile") != rnb_timeline.get("render_profile", {}).get("genre_profile")
    assert trap_timeline.get("render_profile", {}).get("style_signature") != rnb_timeline.get("render_profile", {}).get("style_signature")


def test_storage_backend_and_phase2_flags_do_not_block_core_flow():
    """S3 vs local selection is env-driven, and Phase 2 toggles off do not break core arrangement."""
    backend = settings.get_storage_backend()
    if settings.has_s3_config() and settings.is_production:
        assert backend == "s3"
    else:
        assert backend in {"local", "s3"}

    # Disable optional Phase 2-ish features and ensure core render still works.
    original_style_engine = settings.feature_style_engine
    original_pattern_generation = settings.feature_pattern_generation
    try:
        settings.feature_style_engine = False
        settings.feature_pattern_generation = False

        loop_audio = AudioSegment.silent(duration=3000)
        rendered_audio, timeline_json = render_phase_b_arrangement(
            loop_audio=loop_audio,
            bpm=120,
            target_seconds=120,
        )

        timeline = json.loads(timeline_json)
        assert len(rendered_audio) > 0
        assert len(timeline.get("sections", [])) >= 3
    finally:
        settings.feature_style_engine = original_style_engine
        settings.feature_pattern_generation = original_pattern_generation
