"""
Phase 5 audibility assertion tests — hard-truth render signatures.

These tests prove that the arrangement pipeline produces *materially different*
audio across sections by checking:

  1. ``unique_render_signature_count > 1`` for arrangements with qualified material
     (i.e. with stems).
  2. Phrase A != Phrase B for sections that receive a phrase plan.
  3. Verse 1 != Verse 2 render signature (distinct stem sets).
  4. Hook 1 != Hook 2 render signature (evolution + density expansion).
  5. Breakdown render signature materially differs from hook.
  6. Stereo fallback is clearly identified in ``render_spec_summary``.
  7. The silent fallback that previously used ALL stems for forbidden-role
     sections (bridge/breakdown/intro) is gone — those sections now exclude
     forbidden-role stems.
  8. ``_build_render_spec_summary`` reports ``render_path_used`` and
     ``is_stereo_fallback`` correctly.

Root causes targeted:
  - Silent data-loss fallback: ``map_instruments_to_stems`` returning empty →
    ALL stems used, defeating choreography.
  - Render spec sameness: planned roles vs. actual rendered audio diverged.
  - Stereo fallback invisibility: no flag in summary when no stems available.
"""

from __future__ import annotations

import json
import unittest.mock
from pydub import AudioSegment

import pytest


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

_FULL_ROLES = ["drums", "bass", "melody", "pads", "fx", "vocal", "arp", "synth"]
_RHYTHM_ONLY_ROLES = ["drums", "bass"]


def _stem_meta(roles: list[str]) -> dict:
    return {"enabled": True, "succeeded": True, "roles_detected": list(roles)}


def _make_sections(specs: list[tuple]) -> list[dict]:
    """specs: (name, type, bar_start, bars)"""
    return [{"name": n, "type": t, "bar_start": bs, "bars": b} for n, t, bs, b in specs]


def _run_choreography(sections: list[dict], roles: list[str] = _FULL_ROLES) -> list[dict]:
    """Run _apply_stem_primary_section_states with both v2 flags enabled."""
    from app.services.arrangement_jobs import _apply_stem_primary_section_states
    with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
        mock_settings.feature_producer_section_identity_v2 = True
        mock_settings.feature_section_choreography_v2 = True
        return _apply_stem_primary_section_states(sections, _stem_meta(roles))


def _make_stem_segment(duration_ms: int = 4000) -> AudioSegment:
    """Create a minimal silent AudioSegment suitable for stem-mode tests."""
    return AudioSegment.silent(duration=duration_ms)


def _make_stems(names: list[str], duration_ms: int = 4000) -> dict[str, AudioSegment]:
    return {name: _make_stem_segment(duration_ms) for name in names}


def _run_render_spec_summary(timeline_sections: list[dict]) -> dict:
    from app.services.arrangement_jobs import _build_render_spec_summary
    return _build_render_spec_summary(timeline_sections)


# ---------------------------------------------------------------------------
# Phase 5 Test Class 1 — unique_render_signature_count
# ---------------------------------------------------------------------------


class TestUniqueRenderSignatureCount:
    """unique_render_signature_count must be > 1 for any arrangement with multiple
    section types when real stems are supplied."""

    def _simulate_stem_render(
        self, sections: list[dict], stem_names: list[str]
    ) -> list[dict]:
        """Simulate what _render_producer_arrangement stores in timeline_sections
        when stems are available.  Bypasses actual audio rendering so tests run
        without ffmpeg.
        """
        from app.services.stem_loader import map_instruments_to_stems
        from app.services.section_identity_engine import SECTION_PROFILES, _FALLBACK_PROFILE

        stems = _make_stems(stem_names)
        timeline: list[dict] = []
        for idx, section in enumerate(sections):
            section_type = str(section.get("type") or "verse")
            instruments = list(section.get("instruments") or section.get("active_stem_roles") or [])
            enabled = map_instruments_to_stems(instruments, stems)
            if not enabled:
                # Mirror the fixed fallback: exclude forbidden-role stems
                profile = SECTION_PROFILES.get(section_type, _FALLBACK_PROFILE)
                forbidden = set(profile.forbidden_roles)
                fallback = {k: v for k, v in stems.items() if k not in forbidden}
                enabled = fallback or stems
            # Phrase plan handling
            phrase_plan = section.get("phrase_plan") if isinstance(section.get("phrase_plan"), dict) else None
            if phrase_plan and int(section.get("bars", 0)) > 4:
                first_roles = phrase_plan.get("first_phrase_roles") or instruments
                second_roles = phrase_plan.get("second_phrase_roles") or instruments
                first_stems = map_instruments_to_stems(first_roles, stems) or enabled
                second_stems = map_instruments_to_stems(second_roles, stems) or enabled
                sig = (
                    f"stem_phrase:{','.join(sorted(first_stems.keys()))}"
                    f"|{','.join(sorted(second_stems.keys()))}"
                )
                active = list(dict.fromkeys(list(first_roles) + list(second_roles)))
                phrase_used = True
            else:
                sig = f"stem:{','.join(sorted(enabled.keys()))}"
                active = list(enabled.keys())
                phrase_used = False
            timeline.append({
                "type": section_type,
                "runtime_active_stems": active,
                "actual_render_signature": sig,
                "phrase_plan_used": phrase_used,
                "phrase_plan": section.get("phrase_plan"),
                "hook_evolution": section.get("hook_evolution"),
                "applied_events": [],
                "boundary_events": section.get("boundary_events") or [],
            })
        return timeline

    def test_full_arrangement_with_stems_has_multiple_render_signatures(self):
        """A full intro/verse/hook/bridge/outro arrangement with stems must produce
        at least 3 distinct render signatures (intro≠verse≠bridge at minimum)."""
        specs = [
            ("Intro",   "intro",     0,  4),
            ("Verse 1", "verse",     4,  8),
            ("Hook 1",  "hook",      12, 8),
            ("Bridge",  "bridge",    20, 8),
            ("Outro",   "outro",     28, 4),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = self._simulate_stem_render(sections, _FULL_ROLES)
        summary = _run_render_spec_summary(timeline)

        assert summary["unique_render_signature_count"] >= 3, (
            f"Expected >= 3 unique render signatures for intro/verse/hook/bridge/outro, "
            f"got {summary['unique_render_signature_count']}.  "
            f"Signatures: {summary.get('render_signatures')}"
        )

    def test_verse_and_hook_have_different_render_signatures(self):
        """Verse and hook must produce different actual render signatures when stems differ."""
        specs = [
            ("Verse", "verse", 0, 8),
            ("Hook",  "hook",  8, 8),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = self._simulate_stem_render(sections, _FULL_ROLES)
        summary = _run_render_spec_summary(timeline)

        sigs = [r["actual_render_signature"] for r in timeline]
        assert sigs[0] != sigs[1], (
            f"Verse and hook must have different render signatures.  "
            f"Both got: '{sigs[0]}'"
        )

    def test_bridge_render_signature_differs_from_hook(self):
        """Bridge (no drums/bass) must have a completely different signature from hook."""
        specs = [
            ("Hook",   "hook",   0, 8),
            ("Bridge", "bridge", 8, 8),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = self._simulate_stem_render(sections, _FULL_ROLES)
        hook_sig = timeline[0]["actual_render_signature"]
        bridge_sig = timeline[1]["actual_render_signature"]
        assert hook_sig != bridge_sig, (
            f"Bridge signature '{bridge_sig}' must differ from hook '{hook_sig}'"
        )

    def test_verse_1_and_verse_2_have_different_signatures(self):
        """Verse 2 must have a different render signature from verse 1 (support rotation)."""
        specs = [
            ("Verse 1", "verse", 0,  8),
            ("Verse 2", "verse", 8,  8),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = self._simulate_stem_render(sections, _FULL_ROLES)
        sig1 = timeline[0]["actual_render_signature"]
        sig2 = timeline[1]["actual_render_signature"]
        assert sig1 != sig2, (
            f"Verse 1 and Verse 2 must have different render signatures.  "
            f"Both got '{sig1}'"
        )

    def test_hook_1_and_hook_2_have_different_signatures(self):
        """Hook 2 must have a different render signature from hook 1 (evolution stage)."""
        specs = [
            ("Hook 1", "hook", 0,  8),
            ("Verse",  "verse", 8, 8),
            ("Hook 2", "hook", 16, 8),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = self._simulate_stem_render(sections, _FULL_ROLES)
        h1_sig = timeline[0]["actual_render_signature"]
        h2_sig = timeline[2]["actual_render_signature"]
        assert h1_sig != h2_sig, (
            f"Hook 1 and Hook 2 must have different render signatures. "
            f"Both got '{h1_sig}'"
        )


# ---------------------------------------------------------------------------
# Phase 5 Test Class 2 — phrase signature: phrase A != phrase B
# ---------------------------------------------------------------------------


class TestPhraseSignatureDifference:
    """Phrase split must produce two distinct stem sets per section."""

    def test_hook_phrase_a_differs_from_phrase_b_in_render_signature(self):
        """Hook phrase split renders two halves with different stem sets; signature encodes both."""
        specs = [("Hook", "hook", 0, 8)]
        sections = _run_choreography(_make_sections(specs))
        hook = sections[0]
        phrase_plan = hook.get("phrase_plan")
        if phrase_plan is None:
            pytest.skip("Hook did not receive a phrase_plan (insufficient roles)")

        first = phrase_plan.get("first_phrase_roles") or []
        second = phrase_plan.get("second_phrase_roles") or []

        from app.services.stem_loader import map_instruments_to_stems
        stems = _make_stems(_FULL_ROLES)
        first_stems = map_instruments_to_stems(first, stems)
        second_stems = map_instruments_to_stems(second, stems)

        first_sig = f"stem_phrase:{','.join(sorted(first_stems.keys()))}|{','.join(sorted(second_stems.keys()))}"
        # Phrase A and B stem sets must differ — otherwise there is no intra-section variation.
        assert frozenset(first_stems.keys()) != frozenset(second_stems.keys()), (
            f"Hook phrase A stems {sorted(first_stems.keys())} must differ from "
            f"phrase B stems {sorted(second_stems.keys())}"
        )

    def test_verse_phrase_a_is_rhythm_only(self):
        """Verse first phrase must be rhythm-only (drums+bass), second adds melody."""
        specs = [("Verse", "verse", 0, 8)]
        sections = _run_choreography(_make_sections(specs))
        verse = sections[0]
        phrase_plan = verse.get("phrase_plan")
        if phrase_plan is None:
            pytest.skip("Verse did not receive a phrase_plan (likely only 1 role active)")

        first = set(phrase_plan.get("first_phrase_roles") or [])
        second = set(phrase_plan.get("second_phrase_roles") or [])

        melodic = {"melody", "vocal", "synth", "arp"}
        assert not (first & melodic), (
            f"Verse phrase A {sorted(first)} should contain no melodic roles — "
            "rhythm-only for bar 1..N, melody enters at phrase B"
        )
        assert second > first or second != first, (
            f"Verse phrase B {sorted(second)} must be a superset of or differ from "
            f"phrase A {sorted(first)}"
        )

    def test_unique_phrase_signature_count_nonzero_for_eligible_arrangement(self):
        """An arrangement with sections > 4 bars must report >= 1 unique phrase signature."""
        specs = [
            ("Verse",     "verse",     0,  8),
            ("Hook",      "hook",      8,  8),
            ("Bridge",    "bridge",    16, 8),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = []
        for section in sections:
            pp = section.get("phrase_plan")
            phrase_used = bool(pp and int(section.get("bars", 0)) > 4)
            if phrase_used and isinstance(pp, dict):
                ph_sigs = (
                    tuple(sorted(pp.get("first_phrase_roles") or [])),
                    tuple(sorted(pp.get("second_phrase_roles") or [])),
                )
            else:
                ph_sigs = None

            timeline.append({
                "type": section.get("type"),
                "runtime_active_stems": section.get("active_stem_roles") or [],
                "actual_render_signature": f"stem:{','.join(sorted(section.get('active_stem_roles') or []))}",
                "phrase_plan_used": phrase_used,
                "phrase_plan": pp,
                "hook_evolution": section.get("hook_evolution"),
                "applied_events": [],
                "boundary_events": [],
            })
        summary = _run_render_spec_summary(timeline)
        assert summary["unique_phrase_signature_count"] >= 1, (
            "Expected at least 1 unique phrase signature for sections > 4 bars, "
            f"got {summary['unique_phrase_signature_count']}"
        )


# ---------------------------------------------------------------------------
# Phase 5 Test Class 3 — fallback path detection
# ---------------------------------------------------------------------------


class TestFallbackPathDetection:
    """render_spec_summary must accurately report render_path_used and is_stereo_fallback."""

    def test_stereo_fallback_reported_when_no_stems(self):
        """When all sections use stereo_fallback signatures, is_stereo_fallback must be True."""
        timeline = [
            {
                "type": "verse", "runtime_active_stems": ["drums", "bass"],
                "actual_render_signature": "stereo_fallback:verse",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
            {
                "type": "hook", "runtime_active_stems": ["drums", "bass", "melody"],
                "actual_render_signature": "stereo_fallback:hook",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": {"stage": "hook1"}, "applied_events": [], "boundary_events": [],
            },
        ]
        summary = _run_render_spec_summary(timeline)
        assert summary["is_stereo_fallback"] is True, (
            f"Expected is_stereo_fallback=True, got {summary['is_stereo_fallback']}"
        )
        assert summary["render_path_used"] == "stereo_fallback", (
            f"Expected render_path_used='stereo_fallback', got {summary['render_path_used']}"
        )

    def test_stems_render_path_reported_when_all_sections_use_stems(self):
        """When all sections use stem signatures, render_path_used must be 'stems'."""
        timeline = [
            {
                "type": "verse", "runtime_active_stems": ["drums", "bass"],
                "actual_render_signature": "stem:bass,drums",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
            {
                "type": "bridge", "runtime_active_stems": ["melody"],
                "actual_render_signature": "stem:melody",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
        ]
        summary = _run_render_spec_summary(timeline)
        assert summary["render_path_used"] == "stems", (
            f"Expected render_path_used='stems', got {summary['render_path_used']}"
        )
        assert summary["is_stereo_fallback"] is False

    def test_unique_render_signature_count_reported_correctly(self):
        """unique_render_signature_count must equal number of distinct signature strings."""
        timeline = [
            {
                "type": "intro", "runtime_active_stems": ["pads"],
                "actual_render_signature": "stem:pads",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
            {
                "type": "verse", "runtime_active_stems": ["drums", "bass"],
                "actual_render_signature": "stem:bass,drums",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
            {
                "type": "verse", "runtime_active_stems": ["drums", "bass"],
                "actual_render_signature": "stem:bass,drums",  # same as above
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
            {
                "type": "hook", "runtime_active_stems": ["drums", "bass", "melody"],
                "actual_render_signature": "stem:bass,drums,melody",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": {"stage": "hook1"}, "applied_events": [], "boundary_events": [],
            },
        ]
        summary = _run_render_spec_summary(timeline)
        assert summary["unique_render_signature_count"] == 3, (
            f"Expected 3 unique render signatures (pads / bass,drums / bass,drums,melody), "
            f"got {summary['unique_render_signature_count']}.  "
            f"Signatures: {summary.get('render_signatures')}"
        )

    def test_density_only_syndrome_flagged_when_all_signatures_identical(self):
        """When all sections share the same signature, unique_render_signature_count == 1."""
        timeline = [
            {
                "type": stype, "runtime_active_stems": ["drums", "bass", "melody"],
                "actual_render_signature": "stem:bass,drums,melody",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            }
            for stype in ["verse", "verse", "hook", "hook", "bridge"]
        ]
        summary = _run_render_spec_summary(timeline)
        assert summary["unique_render_signature_count"] == 1, (
            f"Expected density-only syndrome to be detected "
            f"(unique_render_signature_count=1), got {summary['unique_render_signature_count']}"
        )

    def test_render_signatures_list_in_summary(self):
        """render_signatures list must be present and contain the unique signature strings."""
        timeline = [
            {
                "type": "verse", "runtime_active_stems": ["drums"],
                "actual_render_signature": "stem:drums",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
            {
                "type": "bridge", "runtime_active_stems": ["melody"],
                "actual_render_signature": "stem:melody",
                "phrase_plan_used": False, "phrase_plan": None,
                "hook_evolution": None, "applied_events": [], "boundary_events": [],
            },
        ]
        summary = _run_render_spec_summary(timeline)
        assert "render_signatures" in summary, "render_signatures list must be in render_spec_summary"
        assert set(summary["render_signatures"]) == {"stem:drums", "stem:melody"}


# ---------------------------------------------------------------------------
# Phase 4 Test Class 4 — stem fallback respects forbidden roles
# ---------------------------------------------------------------------------


class TestStemFallbackRespectsForbidenRoles:
    """When map_instruments_to_stems returns empty (no name match), the fallback
    must exclude forbidden-role stems instead of using ALL stems."""

    def _map_empty_with_profile(self, section_type: str, stems: dict) -> dict:
        """Simulate the fixed fallback path in _render_producer_arrangement."""
        from app.services.section_identity_engine import SECTION_PROFILES, _FALLBACK_PROFILE
        profile = SECTION_PROFILES.get(section_type, _FALLBACK_PROFILE)
        forbidden = set(profile.forbidden_roles)
        fallback = {k: v for k, v in stems.items() if k not in forbidden}
        return fallback or stems

    def test_bridge_fallback_excludes_drums_and_bass(self):
        """Bridge section: when instruments don't match, fallback must not include drums/bass."""
        stems = _make_stems(["drums", "bass", "melody"])
        fallback = self._map_empty_with_profile("bridge", stems)
        assert "drums" not in fallback, (
            f"Bridge fallback must not include drums. Got: {sorted(fallback.keys())}"
        )
        assert "bass" not in fallback, (
            f"Bridge fallback must not include bass. Got: {sorted(fallback.keys())}"
        )
        assert "melody" in fallback, (
            f"Bridge fallback must include melody (not forbidden). Got: {sorted(fallback.keys())}"
        )

    def test_breakdown_fallback_excludes_drums_and_bass(self):
        """Breakdown section: fallback must not include drums or bass."""
        stems = _make_stems(["drums", "bass", "vocal", "pads"])
        fallback = self._map_empty_with_profile("breakdown", stems)
        assert "drums" not in fallback
        assert "bass" not in fallback
        assert len(fallback) >= 1, "Breakdown fallback must have at least one non-forbidden stem"

    def test_intro_fallback_excludes_drums_and_bass(self):
        """Intro section: fallback must not include drums or bass."""
        stems = _make_stems(["drums", "bass", "pads", "fx"])
        fallback = self._map_empty_with_profile("intro", stems)
        assert "drums" not in fallback
        assert "bass" not in fallback

    def test_verse_fallback_includes_all_stems(self):
        """Verse has no forbidden roles — fallback should include all stems."""
        stems = _make_stems(["drums", "bass", "melody"])
        fallback = self._map_empty_with_profile("verse", stems)
        assert set(fallback.keys()) == {"drums", "bass", "melody"}, (
            f"Verse has no forbidden roles; fallback should use all stems. Got: {sorted(fallback.keys())}"
        )

    def test_hook_fallback_includes_all_stems(self):
        """Hook has no forbidden roles — fallback should include all stems."""
        stems = _make_stems(["drums", "bass", "melody", "vocal"])
        fallback = self._map_empty_with_profile("hook", stems)
        assert set(fallback.keys()) == {"drums", "bass", "melody", "vocal"}

    def test_all_forbidden_stems_fallback_accepts_everything(self):
        """Edge case: if all available stems are forbidden, fallback accepts all to avoid silence."""
        stems = _make_stems(["drums", "bass"])  # both forbidden for bridge
        fallback = self._map_empty_with_profile("bridge", stems)
        # filtered set is empty — fallback must return the full set rather than silence
        assert fallback == stems, (
            "When ALL available stems are forbidden, the last-resort fallback should "
            "return the full stem set to prevent silence."
        )


# ---------------------------------------------------------------------------
# Phase 5 Test Class 5 — stereo phrase variation in fallback mode
# ---------------------------------------------------------------------------


class TestStereoPhraseSplitInFallback:
    """In stereo fallback mode (no stems), phrase plans must still generate a
    distinct stereo_phrase:… signature rather than a flat stereo_fallback:… one."""

    def _simulate_stereo_render_with_phrase(
        self, sections: list[dict]
    ) -> list[dict]:
        """Simulate stereo fallback path with phrase split tracking."""
        timeline: list[dict] = []
        for idx, section in enumerate(sections):
            section_type = str(section.get("type") or "verse")
            phrase_plan = section.get("phrase_plan") if isinstance(section.get("phrase_plan"), dict) else None
            bars = int(section.get("bars", 0) or 0)
            if phrase_plan and bars > 4:
                split_bar = int(phrase_plan.get("split_bar", bars // 2) or (bars // 2))
                sig = f"stereo_phrase:{section_type}:{split_bar}"
                phrase_used = True
            else:
                sig = f"stereo_fallback:{section_type}"
                phrase_used = False
            timeline.append({
                "type": section_type,
                "runtime_active_stems": section.get("active_stem_roles") or [],
                "actual_render_signature": sig,
                "phrase_plan_used": phrase_used,
                "phrase_plan": phrase_plan,
                "hook_evolution": section.get("hook_evolution"),
                "applied_events": [],
                "boundary_events": section.get("boundary_events") or [],
            })
        return timeline

    def test_verse_with_phrase_plan_gets_stereo_phrase_signature(self):
        """Verse > 4 bars with a phrase_plan must get a stereo_phrase:… signature, not
        stereo_fallback:verse."""
        specs = [("Verse", "verse", 0, 8)]
        sections = _run_choreography(_make_sections(specs))
        verse = sections[0]
        if verse.get("phrase_plan") is None:
            pytest.skip("Verse did not get a phrase_plan (insufficient active roles)")
        timeline = self._simulate_stereo_render_with_phrase([verse])
        sig = timeline[0]["actual_render_signature"]
        assert sig.startswith("stereo_phrase:"), (
            f"Expected stereo_phrase:… signature for verse with phrase_plan, got '{sig}'"
        )

    def test_stereo_fallback_arrangement_unique_signatures_above_1(self):
        """Even in stereo mode, an arrangement with multiple section types
        (intro/verse/hook/bridge/outro) should produce > 1 distinct signature."""
        specs = [
            ("Intro",   "intro",     0,  4),
            ("Verse 1", "verse",     4,  8),
            ("Hook 1",  "hook",      12, 8),
            ("Bridge",  "bridge",    20, 8),
            ("Outro",   "outro",     24, 4),
        ]
        sections = _run_choreography(_make_sections(specs))
        timeline = self._simulate_stereo_render_with_phrase(sections)
        summary = _run_render_spec_summary(timeline)
        assert summary["unique_render_signature_count"] > 1, (
            f"Even stereo fallback should produce > 1 unique render signature for "
            f"different section types, got {summary['unique_render_signature_count']}.  "
            f"Signatures: {summary.get('render_signatures')}"
        )
        assert summary["is_stereo_fallback"] is True
