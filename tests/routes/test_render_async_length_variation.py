"""
Tests for render-async length and variation-count behaviour.

Covers:
- requested length changes total bars / actual_length_seconds
- variation_count=3 creates 3 distinct jobs
- seeds differ per variation
- section sequence fills the full target length (sum of bars == total_bars)
- repeated sections (verse_2 / hook_2) are not identical to their first instance
- AsyncRenderRequest / AsyncRenderBatchResponse schema validation
- _layout_sections produces the expected structure
- _compute_target_bars resolves length correctly
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
from app.models.job import RenderJob
from app.models.loop import Loop
from main import app


pytestmark = pytest.mark.usefixtures("fresh_sqlite_integration_db")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def loop_120bpm(db):
    """Loop at 120 BPM (common test fixture)."""
    loop = Loop(
        name="Length Test Loop 120 BPM",
        file_key="uploads/length_test.wav",
        bpm=120,
        bars=8,
    )
    db.add(loop)
    db.commit()
    db.refresh(loop)
    return loop


def _make_fake_job(loop_id: int, job_id: str | None = None) -> RenderJob:
    """Return a minimal queued RenderJob for mocking."""
    return RenderJob(
        id=job_id or str(uuid.uuid4()),
        loop_id=loop_id,
        job_type="render_arrangement",
        status="queued",
        progress=0.0,
        created_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Unit: _layout_sections
# ---------------------------------------------------------------------------


class TestLayoutSections:
    """Unit tests for the _layout_sections helper."""

    def test_single_section_for_less_than_4_bars(self):
        from app.routes.render_jobs import _layout_sections

        sections = _layout_sections(3)
        assert len(sections) == 1
        assert sections[0]["name"] == "verse"
        assert sections[0]["bars"] == 3

    def test_two_sections_for_4_to_7_bars(self):
        from app.routes.render_jobs import _layout_sections

        sections = _layout_sections(6)
        names = [s["name"] for s in sections]
        assert "verse" in names
        assert "hook" in names
        assert len(sections) == 2

    def test_four_sections_for_8_to_15_bars(self):
        from app.routes.render_jobs import _layout_sections

        sections = _layout_sections(12)
        names = [s["name"] for s in sections]
        assert "intro" in names
        assert "verse" in names
        assert "hook" in names
        assert "outro" in names
        assert len(sections) == 4

    def test_six_sections_for_16_to_31_bars(self):
        from app.routes.render_jobs import _layout_sections

        sections = _layout_sections(24)
        names = [s["name"] for s in sections]
        assert "intro" in names
        assert "verse" in names
        assert "hook" in names
        assert "verse_2" in names
        assert "hook_2" in names
        assert "outro" in names
        assert len(sections) == 6

    def test_seven_sections_for_32_or_more_bars(self):
        from app.routes.render_jobs import _layout_sections

        sections = _layout_sections(64)
        names = [s["name"] for s in sections]
        assert "intro" in names
        assert "verse" in names
        assert "hook" in names
        assert "verse_2" in names
        assert "hook_2" in names
        assert "bridge" in names
        assert "outro" in names
        assert len(sections) == 7

    def test_section_bars_sum_equals_total(self):
        from app.routes.render_jobs import _layout_sections

        for total in (4, 8, 16, 32, 64, 96, 128):
            sections = _layout_sections(total)
            assert sum(s["bars"] for s in sections) == total, (
                f"Sections bars must sum to {total} (got {sum(s['bars'] for s in sections)})"
            )

    def test_all_sections_have_positive_bars(self):
        from app.routes.render_jobs import _layout_sections

        for total in (4, 8, 16, 32, 64):
            for s in _layout_sections(total):
                assert s["bars"] >= 1, (
                    f"Section '{s['name']}' has {s['bars']} bars for total={total}"
                )

    def test_bar_start_end_continuous(self):
        from app.routes.render_jobs import _layout_sections

        sections = _layout_sections(64)
        cursor = 0
        for s in sections:
            assert s["bar_start"] == cursor
            assert s["bar_end"] == cursor + s["bars"]
            cursor += s["bars"]


# ---------------------------------------------------------------------------
# Unit: _compute_target_bars
# ---------------------------------------------------------------------------


class TestComputeTargetBars:
    """Unit tests for the _compute_target_bars helper."""

    def _make_loop(self, bpm=120, bars=8):
        loop = MagicMock()
        loop.bpm = bpm
        loop.tempo = None
        loop.bars = bars
        return loop

    def test_target_bars_takes_priority(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        loop = self._make_loop()
        req = AsyncRenderRequest(target_bars=48)
        assert _compute_target_bars(loop, req) == 48

    def test_target_length_seconds_converts_to_bars(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        # At 120 BPM: bars = round(60s / 60min * 120bpm / 4) = round(30) = 30
        loop = self._make_loop(bpm=120)
        req = AsyncRenderRequest(target_length_seconds=60)
        result = _compute_target_bars(loop, req)
        assert result == 30

    def test_duration_alias_works(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        loop = self._make_loop(bpm=120)
        req = AsyncRenderRequest(duration=60)
        result = _compute_target_bars(loop, req)
        assert result == 30

    def test_length_alias_works(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        loop = self._make_loop(bpm=120)
        req = AsyncRenderRequest(length=60)
        result = _compute_target_bars(loop, req)
        assert result == 30

    def test_falls_back_to_loop_bars(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        loop = self._make_loop(bars=16)
        req = AsyncRenderRequest()  # nothing specified
        assert _compute_target_bars(loop, req) == 16

    def test_target_bars_overrides_target_length_seconds(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        loop = self._make_loop(bpm=120)
        req = AsyncRenderRequest(target_bars=48, target_length_seconds=180)
        assert _compute_target_bars(loop, req) == 48

    def test_longer_length_produces_more_bars(self):
        from app.routes.render_jobs import AsyncRenderRequest, _compute_target_bars

        loop = self._make_loop(bpm=120)
        bars_60s = _compute_target_bars(loop, AsyncRenderRequest(target_length_seconds=60))
        bars_180s = _compute_target_bars(loop, AsyncRenderRequest(target_length_seconds=180))
        assert bars_180s > bars_60s


# ---------------------------------------------------------------------------
# Unit: _SECTION_ENERGY and section differentiation
# ---------------------------------------------------------------------------


class TestSectionDifferentiation:
    """Verify that verse_2 / hook_2 differ from verse / hook in energy."""

    def test_verse_2_has_higher_energy_than_verse(self):
        from app.routes.render_jobs import _SECTION_ENERGY

        assert _SECTION_ENERGY["verse_2"] > _SECTION_ENERGY["verse"]

    def test_hook_2_has_higher_energy_than_hook(self):
        from app.routes.render_jobs import _SECTION_ENERGY

        assert _SECTION_ENERGY["hook_2"] >= _SECTION_ENERGY["hook"]

    def test_verse_2_has_full_role_policy(self):
        from app.routes.render_jobs import _SECTION_ROLE_POLICY

        # verse uses "moderate"; verse_2 must use "full" or a richer policy
        assert _SECTION_ROLE_POLICY["verse_2"] != _SECTION_ROLE_POLICY["verse"], (
            "verse_2 must have a different (richer) role policy than verse"
        )

    def test_verse_2_has_boundary_events(self):
        from app.routes.render_jobs import _SECTION_BOUNDARY_EVENTS

        events = _SECTION_BOUNDARY_EVENTS.get("verse_2", [])
        assert len(events) >= 2, (
            "verse_2 must have at least 2 boundary events to differ audibly from verse"
        )

    def test_hook_2_has_boundary_events(self):
        from app.routes.render_jobs import _SECTION_BOUNDARY_EVENTS

        events = _SECTION_BOUNDARY_EVENTS.get("hook_2", [])
        assert len(events) >= 2, (
            "hook_2 must have at least 2 boundary events to differ audibly from hook"
        )

    def test_minimal_plan_verse_2_has_boundary_events_in_variations(self):
        """_build_minimal_render_plan must inject boundary events into verse_2."""
        from app.routes.render_jobs import _build_minimal_render_plan

        loop = MagicMock()
        loop.id = 1
        loop.bpm = 120
        loop.tempo = None
        loop.bars = None
        loop.stem_roles = {}

        # 32 bars → 7-section layout containing verse_2
        plan = _build_minimal_render_plan(loop, {}, target_bars=32)
        verse_2_sections = [s for s in plan["sections"] if s["name"] == "verse_2"]
        assert verse_2_sections, "32-bar plan must contain a verse_2 section"
        assert len(verse_2_sections[0]["variations"]) >= 2, (
            "verse_2 section in minimal plan must have at least 2 variation events"
        )

    def test_minimal_plan_hook_2_has_boundary_events_in_variations(self):
        """_build_minimal_render_plan must inject boundary events into hook_2."""
        from app.routes.render_jobs import _build_minimal_render_plan

        loop = MagicMock()
        loop.id = 1
        loop.bpm = 120
        loop.tempo = None
        loop.bars = None
        loop.stem_roles = {}

        plan = _build_minimal_render_plan(loop, {}, target_bars=32)
        hook_2_sections = [s for s in plan["sections"] if s["name"] == "hook_2"]
        assert hook_2_sections, "32-bar plan must contain a hook_2 section"
        assert len(hook_2_sections[0]["variations"]) >= 2, (
            "hook_2 section in minimal plan must have at least 2 variation events"
        )


# ---------------------------------------------------------------------------
# Integration: POST /api/v1/loops/{loop_id}/render-async
# ---------------------------------------------------------------------------


class TestRenderAsyncLengthHandling:
    """Verify requested length is honored in the async render endpoint."""

    def test_target_length_seconds_reflected_in_response(self, client, loop_120bpm):
        """requested_length_seconds in response must match the request."""
        fake_job = _make_fake_job(loop_120bpm.id)
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"target_length_seconds": 120, "variation_count": 1},
            )
        assert response.status_code == 202, response.text
        data = response.json()
        assert data["requested_length_seconds"] == 120

    def test_duration_alias_reflected_in_response(self, client, loop_120bpm):
        """Frontend 'duration' alias must be accepted and reflected."""
        fake_job = _make_fake_job(loop_120bpm.id)
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"duration": 90, "variation_count": 1},
            )
        assert response.status_code == 202, response.text
        assert response.json()["requested_length_seconds"] == 90

    def test_length_alias_reflected_in_response(self, client, loop_120bpm):
        """Frontend 'length' alias must be accepted and reflected."""
        fake_job = _make_fake_job(loop_120bpm.id)
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"length": 60, "variation_count": 1},
            )
        assert response.status_code == 202, response.text
        assert response.json()["requested_length_seconds"] == 60

    def test_longer_length_produces_more_sections(self, client, loop_120bpm):
        """A longer target length must produce a richer section sequence."""
        captured_short: list = []
        captured_long: list = []

        def capture_short(db, loop_id, params, **kwargs):
            captured_short.append(params)
            return _make_fake_job(loop_id), False

        def capture_long(db, loop_id, params, **kwargs):
            captured_long.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_short):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"target_length_seconds": 10, "variation_count": 1},
            )

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_long):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"target_length_seconds": 180, "variation_count": 1},
            )

        short_bars = captured_short[0]["target_bars"]
        long_bars = captured_long[0]["target_bars"]
        assert long_bars > short_bars, (
            f"Longer target length must produce more bars (got {short_bars} vs {long_bars})"
        )

    def test_actual_length_seconds_in_response(self, client, loop_120bpm):
        """actual_length_seconds must be present and positive."""
        fake_job = _make_fake_job(loop_120bpm.id)
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"target_length_seconds": 60, "variation_count": 1},
            )
        data = response.json()
        assert data["actual_length_seconds"] is not None
        assert data["actual_length_seconds"] > 0

    def test_target_bars_in_job_params(self, client, loop_120bpm):
        """target_bars must be passed to create_render_job params."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"target_bars": 48, "variation_count": 1},
            )

        assert captured[0]["target_bars"] == 48

    def test_section_sequence_fills_target_length(self, client, loop_120bpm):
        """section_sequence must contain at least 1 section for any valid length."""
        fake_job = _make_fake_job(loop_120bpm.id)
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", return_value=(fake_job, False)):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"target_length_seconds": 180, "variation_count": 1},
            )
        data = response.json()
        assert "section_sequence" in data
        assert len(data["section_sequence"]) >= 1


# ---------------------------------------------------------------------------
# Integration: variation_count handling
# ---------------------------------------------------------------------------


class TestVariationCount:
    """Verify that variation_count controls the number of enqueued jobs."""

    def test_variation_count_3_creates_3_jobs(self, client, loop_120bpm):
        """variation_count=3 (default) must produce exactly 3 jobs in the response."""
        jobs_created: list = []

        def make_job(db, loop_id, params, **kwargs):
            job = _make_fake_job(loop_id)
            jobs_created.append(job)
            return job, False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=make_job):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3},
            )
        assert response.status_code == 202, response.text
        data = response.json()
        assert data["variation_count"] == 3
        assert len(data["jobs"]) == 3
        assert len(jobs_created) == 3, "create_render_job must be called exactly 3 times"

    def test_variation_count_1_creates_1_job(self, client, loop_120bpm):
        """variation_count=1 must produce exactly 1 job."""
        jobs_created: list = []

        def make_job(db, loop_id, params, **kwargs):
            job = _make_fake_job(loop_id)
            jobs_created.append(job)
            return job, False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=make_job):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 1},
            )
        assert response.status_code == 202, response.text
        assert len(response.json()["jobs"]) == 1
        assert len(jobs_created) == 1

    def test_variation_count_default_is_3(self, client, loop_120bpm):
        """When variation_count is omitted the default (3) must be applied."""
        jobs_created: list = []

        def make_job(db, loop_id, params, **kwargs):
            job = _make_fake_job(loop_id)
            jobs_created.append(job)
            return job, False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=make_job):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async", json={}
            )
        assert response.status_code == 202, response.text
        assert len(response.json()["jobs"]) == 3

    def test_each_job_has_unique_variation_index(self, client, loop_120bpm):
        """Each job entry must have a distinct variation_index (0-based)."""
        def make_job(db, loop_id, params, **kwargs):
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=make_job):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3},
            )
        jobs = response.json()["jobs"]
        indices = [j["variation_index"] for j in jobs]
        assert sorted(indices) == [0, 1, 2], (
            f"Expected variation indices [0, 1, 2], got {indices}"
        )

    def test_variation_count_in_params_passed_to_job_service(self, client, loop_120bpm):
        """variation_count must be forwarded in each job's params."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 5},
            )
        assert len(captured) == 5
        for p in captured:
            assert p["variation_count"] == 5


# ---------------------------------------------------------------------------
# Integration: seed handling
# ---------------------------------------------------------------------------


class TestVariationSeeds:
    """Verify that seeds are deterministic and differ across variations."""

    def test_seeds_differ_per_variation(self, client, loop_120bpm):
        """Each variation must receive a different seed."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3},
            )
        assert response.status_code == 202
        seeds = [p["variation_seed"] for p in captured]
        assert len(set(seeds)) == 3, (
            f"All 3 variation seeds must be distinct, got {seeds}"
        )

    def test_job_response_includes_variation_seed(self, client, loop_120bpm):
        """Each job entry in the response must include a variation_seed field."""
        def make_job(db, loop_id, params, **kwargs):
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=make_job):
            response = client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3},
            )
        jobs = response.json()["jobs"]
        for job in jobs:
            assert "variation_seed" in job, "variation_seed must be present in each job entry"
            assert isinstance(job["variation_seed"], int)

    def test_supplied_variation_seed_used_as_base(self, client, loop_120bpm):
        """When variation_seed is provided it must be used as the base."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        base_seed = 1000
        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3, "variation_seed": base_seed},
            )
        seeds = [p["variation_seed"] for p in captured]
        # Seeds must be base_seed + 0, base_seed + 1, base_seed + 2
        assert seeds == [base_seed, base_seed + 1, base_seed + 2], (
            f"Expected seeds {[base_seed, base_seed + 1, base_seed + 2]}, got {seeds}"
        )

    def test_same_seed_produces_same_render_plan(self):
        """Determinism check: same seed + same params produce identical render_plan_json."""
        from app.routes.render_jobs import _build_minimal_render_plan

        loop = MagicMock()
        loop.id = 1
        loop.bpm = 120
        loop.tempo = None
        loop.bars = None
        loop.stem_roles = {}

        plan_a = _build_minimal_render_plan(loop, {}, target_bars=32)
        plan_b = _build_minimal_render_plan(loop, {}, target_bars=32)
        # Minimal plan is deterministic (no random component)
        assert json.dumps(plan_a, sort_keys=True) == json.dumps(plan_b, sort_keys=True)


# ---------------------------------------------------------------------------
# Integration: arrangement metadata in job params
# ---------------------------------------------------------------------------


class TestArrangementMetadata:
    """Verify that per-arrangement metadata is present in job params."""

    def test_job_params_contain_metadata_fields(self, client, loop_120bpm):
        """All required metadata fields must appear in the params sent to create_render_job."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3},
            )

        required_metadata = (
            "target_bars",
            "variation_seed",
            "variation_index",
            "variation_count",
            "actual_length_seconds",
            "section_count",
            "section_sequence",
            "render_plan_json",
        )
        for idx, params in enumerate(captured):
            for field in required_metadata:
                assert field in params, (
                    f"Job {idx}: params must contain '{field}', got keys: {list(params.keys())}"
                )

    def test_section_count_matches_section_sequence_length(self, client, loop_120bpm):
        """section_count in params must equal len(section_sequence)."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 1},
            )

        params = captured[0]
        assert params["section_count"] == len(params["section_sequence"])

    def test_render_plan_json_sections_match_section_sequence(self, client, loop_120bpm):
        """Section names in render_plan_json must match section_sequence in params."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 1},
            )

        params = captured[0]
        plan = json.loads(params["render_plan_json"])
        plan_section_names = [s["name"] for s in plan.get("sections", [])]
        # Both lists must have the same names in the same order
        assert plan_section_names == params["section_sequence"], (
            f"render_plan_json sections {plan_section_names} must match "
            f"section_sequence {params['section_sequence']}"
        )

    def test_variation_index_increments_per_job(self, client, loop_120bpm):
        """variation_index in params must be 0, 1, 2 for three jobs."""
        captured: list = []

        def capture_job_params(db, loop_id, params, **kwargs):
            captured.append(params)
            return _make_fake_job(loop_id), False

        with patch("app.routes.render_jobs.is_redis_available", return_value=True), \
             patch("app.routes.render_jobs.create_render_job", side_effect=capture_job_params):
            client.post(
                f"/api/v1/loops/{loop_120bpm.id}/render-async",
                json={"variation_count": 3},
            )

        indices = [p["variation_index"] for p in captured]
        assert indices == [0, 1, 2], f"Expected [0, 1, 2], got {indices}"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestAsyncRenderRequestSchema:
    """Pydantic validation for AsyncRenderRequest."""

    def test_default_variation_count_is_3(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest()
        assert req.variation_count == 3

    def test_variation_count_1_accepted(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest(variation_count=1)
        assert req.variation_count == 1

    def test_variation_count_10_accepted(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest(variation_count=10)
        assert req.variation_count == 10

    def test_target_length_seconds_accepted(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest(target_length_seconds=180)
        assert req.target_length_seconds == 180

    def test_duration_alias_accepted(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest(duration=120)
        assert req.duration == 120

    def test_length_alias_accepted(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest(length=90)
        assert req.length == 90

    def test_variation_seed_optional(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest()
        assert req.variation_seed is None

    def test_variation_seed_set(self):
        from app.routes.render_jobs import AsyncRenderRequest

        req = AsyncRenderRequest(variation_seed=42)
        assert req.variation_seed == 42


class TestAsyncRenderBatchResponseSchema:
    """Pydantic validation for AsyncRenderBatchResponse."""

    def test_response_roundtrip(self):
        from app.routes.render_jobs import AsyncRenderBatchResponse, VariationJobInfo

        resp = AsyncRenderBatchResponse(
            loop_id=1,
            variation_count=3,
            requested_length_seconds=180,
            actual_length_seconds=182.0,
            section_sequence=["intro", "verse", "hook", "verse_2", "hook_2", "outro"],
            jobs=[
                VariationJobInfo(
                    job_id=str(uuid.uuid4()),
                    variation_index=i,
                    variation_seed=1000 + i,
                    status="queued",
                    poll_url=f"/api/v1/jobs/job-{i}",
                    deduplicated=False,
                )
                for i in range(3)
            ],
        )
        data = json.loads(resp.model_dump_json())
        assert data["loop_id"] == 1
        assert data["variation_count"] == 3
        assert len(data["jobs"]) == 3
        assert data["jobs"][1]["variation_index"] == 1
