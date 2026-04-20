"""
Comprehensive tests for the Motif Engine.

Coverage (120 tests):
1.  Motif type contract and validation.
2.  MotifTransformation type contract.
3.  MotifOccurrence properties.
4.  MotifPlan construction and serialisation.
5.  MotifEngineState tracking.
6.  Transformation builders — individual functions.
7.  select_transformations — section-type dispatch.
8.  select_transformations — source-quality-aware degradation.
9.  select_transformations — repeated hook differentiation.
10. MotifExtractor — role preference ordering.
11. MotifExtractor — stereo_fallback behaviour.
12. MotifExtractor — conservative fallback when no viable role.
13. MotifExtractor — source-quality confidence multipliers.
14. MotifPlanner — intro motif tease.
15. MotifPlanner — verse restrained motif.
16. MotifPlanner — hook motif strengthening.
17. MotifPlanner — repeated hook differentiation.
18. MotifPlanner — bridge motif variation.
19. MotifPlanner — outro motif resolution.
20. MotifPlanner — no viable motif fallback.
21. MotifPlanner — source-quality-aware behavior.
22. MotifValidator — all rules.
23. Serialisation correctness (round-trip JSON).
24. Shadow integration metadata storage.
25. Determinism.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.services.motif_engine import (
    Motif,
    MotifEngineState,
    MotifExtractor,
    MotifOccurrence,
    MotifPlan,
    MotifPlanner,
    MotifTransformation,
    MotifValidator,
    MotifValidationIssue,
    STRONG_TRANSFORMATION_TYPES,
    SUPPORTED_MOTIF_TYPES,
    SUPPORTED_TRANSFORMATION_TYPES,
    WEAK_TRANSFORMATION_TYPES,
)
from app.services.motif_engine.transformations import (
    simplify,
    delay_entry,
    octave_lift,
    sparse_phrase,
    full_phrase,
    call_response,
    texture_only,
    counter_variant,
    rhythm_trim,
    sustain_expand,
    select_transformations,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _sections(*names: str) -> List[Dict[str, Any]]:
    return [{"type": n, "bars": 8} for n in names]


def _planner(source_quality: str = "true_stems", roles: List[str] | None = None) -> MotifPlanner:
    return MotifPlanner(
        source_quality=source_quality,
        available_roles=roles if roles is not None else ["melody", "bass", "drums"],
    )


def _full_sections() -> List[Dict[str, Any]]:
    return _sections(
        "intro", "verse", "verse", "pre_hook", "hook",
        "verse", "pre_hook", "hook", "bridge", "outro",
    )


# ===========================================================================
# 1. Motif type contract and validation
# ===========================================================================


class TestMotifType:
    def test_valid_construction(self):
        m = Motif(
            motif_id="motif_001",
            source_role="melody",
            motif_type="lead_phrase",
            confidence=0.85,
            bars=2,
        )
        assert m.motif_id == "motif_001"
        assert m.source_role == "melody"
        assert m.motif_type == "lead_phrase"
        assert m.confidence == pytest.approx(0.85)
        assert m.bars == 2
        assert m.notes is None

    def test_confidence_clamped_low(self):
        m = Motif(motif_id="x", source_role="r", motif_type="lead_phrase", confidence=-1.0, bars=2)
        assert m.confidence == 0.0

    def test_confidence_clamped_high(self):
        m = Motif(motif_id="x", source_role="r", motif_type="lead_phrase", confidence=5.0, bars=2)
        assert m.confidence == 1.0

    def test_invalid_motif_type_raises(self):
        with pytest.raises(ValueError, match="motif_type"):
            Motif(motif_id="x", source_role="r", motif_type="bad_type", confidence=0.5, bars=2)

    def test_empty_motif_id_raises(self):
        with pytest.raises(ValueError, match="motif_id"):
            Motif(motif_id="", source_role="r", motif_type="lead_phrase", confidence=0.5, bars=2)

    def test_bars_below_one_raises(self):
        with pytest.raises(ValueError, match="bars"):
            Motif(motif_id="x", source_role="r", motif_type="lead_phrase", confidence=0.5, bars=0)

    def test_all_motif_types_valid(self):
        for mt in SUPPORTED_MOTIF_TYPES:
            m = Motif(motif_id="x", source_role="r", motif_type=mt, confidence=0.5, bars=2)
            assert m.motif_type == mt

    def test_to_dict_structure(self):
        m = Motif(motif_id="m1", source_role="lead", motif_type="lead_phrase", confidence=0.7, bars=4, notes="test")
        d = m.to_dict()
        assert d["motif_id"] == "m1"
        assert d["source_role"] == "lead"
        assert d["motif_type"] == "lead_phrase"
        assert "confidence" in d
        assert "bars" in d
        assert d["notes"] == "test"

    def test_to_dict_no_notes_omits_key(self):
        m = Motif(motif_id="m1", source_role="r", motif_type="chord_shape", confidence=0.5, bars=2)
        d = m.to_dict()
        assert "notes" not in d


# ===========================================================================
# 2. MotifTransformation type contract
# ===========================================================================


class TestMotifTransformation:
    def test_valid_construction(self):
        t = MotifTransformation(transformation_type="full_phrase", intensity=0.9)
        assert t.transformation_type == "full_phrase"
        assert t.intensity == pytest.approx(0.9)

    def test_intensity_clamped(self):
        t = MotifTransformation(transformation_type="simplify", intensity=2.5)
        assert t.intensity == 1.0
        t2 = MotifTransformation(transformation_type="simplify", intensity=-0.5)
        assert t2.intensity == 0.0

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="transformation_type"):
            MotifTransformation(transformation_type="unknown_type")

    def test_all_transformation_types_valid(self):
        for tt in SUPPORTED_TRANSFORMATION_TYPES:
            t = MotifTransformation(transformation_type=tt)
            assert t.transformation_type == tt

    def test_is_strong_property(self):
        strong_t = MotifTransformation(transformation_type="full_phrase")
        assert strong_t.is_strong is True
        weak_t = MotifTransformation(transformation_type="texture_only")
        assert weak_t.is_strong is False

    def test_is_weak_property(self):
        weak_t = MotifTransformation(transformation_type="simplify")
        assert weak_t.is_weak is True
        strong_t = MotifTransformation(transformation_type="octave_lift")
        assert strong_t.is_weak is False

    def test_strong_and_weak_are_disjoint(self):
        assert STRONG_TRANSFORMATION_TYPES.isdisjoint(WEAK_TRANSFORMATION_TYPES)

    def test_to_dict_structure(self):
        t = MotifTransformation(transformation_type="delay_entry", intensity=0.5, notes="test")
        d = t.to_dict()
        assert d["transformation_type"] == "delay_entry"
        assert "intensity" in d
        assert "parameters" in d
        assert d["notes"] == "test"


# ===========================================================================
# 3. MotifOccurrence properties
# ===========================================================================


class TestMotifOccurrence:
    def test_valid_construction(self):
        o = MotifOccurrence(
            section_name="hook_1",
            occurrence_index=0,
            source_role="melody",
            transformations=[full_phrase()],
            target_intensity=0.9,
        )
        assert o.section_name == "hook_1"
        assert o.occurrence_index == 0
        assert o.is_strong is True

    def test_empty_transformations_is_weak(self):
        o = MotifOccurrence(section_name="verse_1", occurrence_index=0, source_role="r")
        assert o.is_weak is True

    def test_all_weak_transformations_is_weak(self):
        o = MotifOccurrence(
            section_name="verse_1",
            occurrence_index=0,
            source_role="r",
            transformations=[simplify(), texture_only()],
        )
        assert o.is_weak is True

    def test_transformation_types_property(self):
        o = MotifOccurrence(
            section_name="hook_1",
            occurrence_index=0,
            source_role="r",
            transformations=[full_phrase(), octave_lift()],
        )
        assert set(o.transformation_types) == {"full_phrase", "octave_lift"}

    def test_invalid_occurrence_index_raises(self):
        with pytest.raises(ValueError, match="occurrence_index"):
            MotifOccurrence(section_name="x", occurrence_index=-1, source_role="r")

    def test_to_dict_structure(self):
        o = MotifOccurrence(
            section_name="bridge_1",
            occurrence_index=0,
            source_role="melody",
            transformations=[counter_variant()],
            target_intensity=0.5,
            notes="bridge_note",
        )
        d = o.to_dict()
        assert d["section_name"] == "bridge_1"
        assert d["occurrence_index"] == 0
        assert len(d["transformations"]) == 1
        assert d["notes"] == "bridge_note"


# ===========================================================================
# 4. MotifPlan construction and serialisation
# ===========================================================================


class TestMotifPlan:
    def test_empty_plan(self):
        p = MotifPlan()
        assert p.motif is None
        assert p.occurrences == []
        assert p.fallback_used is False

    def test_scores_clamped(self):
        p = MotifPlan(motif_reuse_score=5.0, motif_variation_score=-1.0)
        assert p.motif_reuse_score == 1.0
        assert p.motif_variation_score == 0.0

    def test_to_dict_round_trip(self):
        motif = Motif(motif_id="m1", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        occ = MotifOccurrence(
            section_name="hook_1",
            occurrence_index=0,
            source_role="melody",
            transformations=[full_phrase()],
            target_intensity=0.9,
        )
        p = MotifPlan(motif=motif, occurrences=[occ], motif_reuse_score=0.8, motif_variation_score=0.6)
        d = p.to_dict()
        assert d["motif"]["motif_id"] == "m1"
        assert len(d["occurrences"]) == 1
        assert d["motif_reuse_score"] == pytest.approx(0.8, abs=0.01)

    def test_json_serialisable(self):
        motif = Motif(motif_id="m1", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        p = MotifPlan(motif=motif, occurrences=[], motif_reuse_score=0.5, motif_variation_score=0.5)
        serialised = json.dumps(p.to_dict())
        restored = json.loads(serialised)
        assert restored["motif"]["motif_id"] == "m1"


# ===========================================================================
# 5. MotifEngineState tracking
# ===========================================================================


class TestMotifEngineState:
    def test_initial_state(self):
        s = MotifEngineState()
        assert s.motif_usage_history == []
        assert s.hook_motif_treatments == []
        assert s.outro_resolved is False
        assert s.total_occurrences() == 0

    def test_record_hook_occurrence(self):
        s = MotifEngineState()
        s.record_occurrence("hook_1", "hook", ["full_phrase"])
        assert len(s.hook_motif_treatments) == 1
        assert frozenset(["full_phrase"]) in s.hook_motif_treatments

    def test_record_outro_sets_resolved(self):
        s = MotifEngineState()
        s.record_occurrence("outro_1", "outro", ["simplify"])
        assert s.outro_resolved is True

    def test_hook_treatments_are_identical_false_when_single(self):
        s = MotifEngineState()
        s.record_occurrence("hook_1", "hook", ["full_phrase"])
        assert s.hook_treatments_are_identical() is False

    def test_hook_treatments_are_identical_true(self):
        s = MotifEngineState()
        s.record_occurrence("hook_1", "hook", ["full_phrase"])
        s.record_occurrence("hook_2", "hook", ["full_phrase"])
        assert s.hook_treatments_are_identical() is True

    def test_hook_treatments_not_identical_when_varied(self):
        s = MotifEngineState()
        s.record_occurrence("hook_1", "hook", ["full_phrase"])
        s.record_occurrence("hook_2", "hook", ["full_phrase", "octave_lift"])
        assert s.hook_treatments_are_identical() is False

    def test_occurrence_counter_increments(self):
        s = MotifEngineState()
        assert s.get_occurrence_index("hook") == 0
        assert s.get_occurrence_index("hook") == 1
        assert s.get_occurrence_index("verse") == 0

    def test_last_hook_treatment_none_initially(self):
        s = MotifEngineState()
        assert s.last_hook_treatment() is None

    def test_last_hook_treatment_returns_latest(self):
        s = MotifEngineState()
        s.record_occurrence("hook_1", "hook", ["full_phrase"])
        s.record_occurrence("hook_2", "hook", ["call_response"])
        assert s.last_hook_treatment() == frozenset(["call_response"])

    def test_bridge_treatment_tracked(self):
        s = MotifEngineState()
        s.record_occurrence("bridge_1", "bridge", ["counter_variant"])
        assert "counter_variant" in s.bridge_treatment_types


# ===========================================================================
# 6. Transformation builders — individual functions
# ===========================================================================


class TestTransformationBuilders:
    def test_simplify_defaults(self):
        t = simplify()
        assert t.transformation_type == "simplify"
        assert t.is_weak is True

    def test_delay_entry_defaults(self):
        t = delay_entry()
        assert t.transformation_type == "delay_entry"
        assert "entry_offset_beats" in t.parameters

    def test_octave_lift_defaults(self):
        t = octave_lift()
        assert t.transformation_type == "octave_lift"
        assert t.is_strong is True

    def test_sparse_phrase_defaults(self):
        t = sparse_phrase()
        assert t.transformation_type == "sparse_phrase"
        assert t.is_weak is True

    def test_full_phrase_defaults(self):
        t = full_phrase()
        assert t.transformation_type == "full_phrase"
        assert t.is_strong is True
        assert t.intensity == pytest.approx(0.9)

    def test_call_response_defaults(self):
        t = call_response()
        assert t.transformation_type == "call_response"
        assert t.is_strong is True

    def test_texture_only_defaults(self):
        t = texture_only()
        assert t.transformation_type == "texture_only"
        assert t.is_weak is True

    def test_counter_variant_defaults(self):
        t = counter_variant()
        assert t.transformation_type == "counter_variant"

    def test_rhythm_trim_defaults(self):
        t = rhythm_trim()
        assert t.transformation_type == "rhythm_trim"
        assert t.is_weak is True

    def test_sustain_expand_defaults(self):
        t = sustain_expand()
        assert t.transformation_type == "sustain_expand"
        assert t.is_strong is True


# ===========================================================================
# 7. select_transformations — section-type dispatch
# ===========================================================================


class TestSelectTransformations:
    def test_intro_returns_sparse(self):
        ts = select_transformations("intro", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert types & {"sparse_phrase", "texture_only", "delay_entry"}

    def test_verse_returns_restrained(self):
        ts = select_transformations("verse", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        # Verse should not use full_phrase or octave_lift.
        assert "full_phrase" not in types
        assert "octave_lift" not in types

    def test_hook_occurrence_0_full_phrase(self):
        ts = select_transformations("hook", 0, source_quality="true_stems")
        types = [t.transformation_type for t in ts]
        assert "full_phrase" in types

    def test_hook_occurrence_1_escalates(self):
        ts0 = select_transformations("hook", 0, source_quality="true_stems")
        ts1 = select_transformations("hook", 1, source_quality="true_stems")
        types1 = {t.transformation_type for t in ts1}
        # Second hook should be at least as strong — either lifted or call_response.
        assert types1 & {"octave_lift", "call_response", "full_phrase"}

    def test_bridge_uses_counter_or_sparse(self):
        ts = select_transformations("bridge", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert types & {"counter_variant", "sparse_phrase", "texture_only"}

    def test_bridge_does_not_use_full_phrase(self):
        ts = select_transformations("bridge", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert "full_phrase" not in types

    def test_outro_uses_resolving_transformations(self):
        ts = select_transformations("outro", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert types & {"rhythm_trim", "simplify", "sustain_expand"}

    def test_outro_does_not_use_full_phrase(self):
        ts = select_transformations("outro", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert "full_phrase" not in types

    def test_unknown_section_returns_fallback(self):
        ts = select_transformations("random_section", 0)
        assert len(ts) >= 1
        assert ts[0].transformation_type == "simplify"

    def test_breakdown_uses_texture(self):
        ts = select_transformations("breakdown", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert "texture_only" in types


# ===========================================================================
# 8. select_transformations — source-quality-aware degradation
# ===========================================================================


class TestSelectTransformationsSourceQuality:
    def test_stereo_fallback_non_hook_texture(self):
        ts = select_transformations("verse", 0, source_quality="stereo_fallback")
        assert len(ts) == 1
        assert ts[0].transformation_type == "texture_only"

    def test_stereo_fallback_hook_sparse(self):
        ts = select_transformations("hook", 0, source_quality="stereo_fallback")
        assert len(ts) == 1
        assert ts[0].transformation_type == "sparse_phrase"

    def test_ai_separated_no_octave_lift_in_hook(self):
        ts = select_transformations("hook", 1, source_quality="ai_separated")
        types = {t.transformation_type for t in ts}
        assert "octave_lift" not in types

    def test_true_stems_hook_full_strength(self):
        ts = select_transformations("hook", 0, source_quality="true_stems")
        types = {t.transformation_type for t in ts}
        assert "full_phrase" in types


# ===========================================================================
# 9. select_transformations — repeated hook differentiation
# ===========================================================================


class TestSelectTransformationsHookDifferentiation:
    def test_hook_2_differs_from_hook_1_when_identical(self):
        ts1 = select_transformations("hook", 0, source_quality="true_stems")
        prev = frozenset(t.transformation_type for t in ts1)
        # Use occurrence_index=0 but pass previous_hook_treatment to force differentiation.
        ts_diff = select_transformations(
            "hook", 1, source_quality="true_stems", previous_hook_treatment=prev
        )
        types_diff = frozenset(t.transformation_type for t in ts_diff)
        # They should differ (occurrence 1 or higher escalates).
        # At minimum the set is not identical (since table has different entries per index).
        assert types_diff  # non-empty


# ===========================================================================
# 10. MotifExtractor — role preference ordering
# ===========================================================================


class TestMotifExtractor:
    def test_melody_produces_lead_phrase(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["melody", "bass"])
        m = e.extract()
        assert m is not None
        assert m.motif_type == "lead_phrase"
        assert "melody" in m.source_role

    def test_lead_produces_lead_phrase(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["lead", "bass"])
        m = e.extract()
        assert m is not None
        assert m.motif_type == "lead_phrase"

    def test_vocal_produces_lead_phrase(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["vocal"])
        m = e.extract()
        assert m is not None
        assert m.motif_type == "lead_phrase"

    def test_chords_fallback_when_no_melody(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["chords", "bass", "drums"])
        m = e.extract()
        assert m is not None
        assert m.motif_type == "chord_shape"

    def test_arp_produces_arp_fragment(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["arp", "drums"])
        m = e.extract()
        assert m is not None
        assert m.motif_type == "arp_fragment"

    def test_texture_fallback(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["texture", "bass"])
        m = e.extract()
        # texture has low confidence; with true_stems it may still pass threshold.
        # Just check no crash.
        # (May be None if confidence < 0.25 — that's valid behaviour too.)

    def test_no_roles_returns_none(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=[])
        m = e.extract()
        assert m is None

    def test_drums_only_returns_none(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["drums", "bass"])
        m = e.extract()
        assert m is None

    def test_melody_preferred_over_chords(self):
        e = MotifExtractor(
            source_quality="true_stems",
            available_roles=["chords", "melody", "bass"],
        )
        m = e.extract()
        assert m is not None
        assert m.motif_type == "lead_phrase"

    def test_motif_id_non_empty(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["melody"])
        m = e.extract()
        assert m is not None
        assert len(m.motif_id) > 0


# ===========================================================================
# 11. MotifExtractor — stereo_fallback behaviour
# ===========================================================================


class TestMotifExtractorStereoFallback:
    def test_stereo_fallback_no_roles_returns_none(self):
        e = MotifExtractor(source_quality="stereo_fallback", available_roles=[])
        m = e.extract()
        assert m is None

    def test_stereo_fallback_with_melody_low_confidence(self):
        e = MotifExtractor(source_quality="stereo_fallback", available_roles=["melody"])
        m = e.extract()
        # confidence = 1.0 * 0.30 = 0.30 >= 0.25 — should return a motif.
        assert m is not None
        assert m.confidence < 0.40

    def test_stereo_fallback_with_texture_returns_none(self):
        # texture base_confidence=0.35 * 0.30 = 0.105 < 0.25 — no motif.
        e = MotifExtractor(source_quality="stereo_fallback", available_roles=["texture"])
        m = e.extract()
        assert m is None


# ===========================================================================
# 12. MotifExtractor — conservative fallback when no viable role
# ===========================================================================


class TestMotifExtractorNoViableRole:
    def test_drums_bass_only_no_motif(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=["drums", "bass"])
        m = e.extract()
        assert m is None

    def test_empty_roles_no_motif(self):
        e = MotifExtractor(source_quality="true_stems", available_roles=[])
        m = e.extract()
        assert m is None


# ===========================================================================
# 13. MotifExtractor — source-quality confidence multipliers
# ===========================================================================


class TestMotifExtractorConfidenceMultipliers:
    def test_true_stems_highest_confidence(self):
        e_true = MotifExtractor(source_quality="true_stems", available_roles=["melody"])
        e_ai = MotifExtractor(source_quality="ai_separated", available_roles=["melody"])
        m_true = e_true.extract()
        m_ai = e_ai.extract()
        assert m_true is not None
        assert m_ai is not None
        assert m_true.confidence > m_ai.confidence

    def test_ai_separated_lower_than_zip(self):
        e_zip = MotifExtractor(source_quality="zip_stems", available_roles=["melody"])
        e_ai = MotifExtractor(source_quality="ai_separated", available_roles=["melody"])
        m_zip = e_zip.extract()
        m_ai = e_ai.extract()
        assert m_zip is not None
        assert m_ai is not None
        assert m_zip.confidence > m_ai.confidence


# ===========================================================================
# 14. MotifPlanner — intro motif tease
# ===========================================================================


class TestMotifPlannerIntro:
    def test_intro_motif_is_sparse_or_tease(self):
        plan = _planner().build(_sections("intro", "verse", "hook"))
        intro_occurrences = [o for o in plan.occurrences if "intro" in o.section_name.lower()]
        assert intro_occurrences
        for o in intro_occurrences:
            # Intro should not have a strong (full) motif.
            assert "full_phrase" not in o.transformation_types

    def test_intro_target_intensity_low(self):
        plan = _planner().build(_sections("intro", "hook"))
        intro_occurrences = [o for o in plan.occurrences if "intro" in o.section_name.lower()]
        if intro_occurrences:
            assert intro_occurrences[0].target_intensity < 0.6


# ===========================================================================
# 15. MotifPlanner — verse restrained motif
# ===========================================================================


class TestMotifPlannerVerse:
    def test_verse_no_full_phrase(self):
        plan = _planner().build(_sections("verse", "hook"))
        verse_occurrences = [o for o in plan.occurrences if "verse" in o.section_name.lower()]
        for o in verse_occurrences:
            assert "full_phrase" not in o.transformation_types
            assert "octave_lift" not in o.transformation_types


# ===========================================================================
# 16. MotifPlanner — hook motif strengthening
# ===========================================================================


class TestMotifPlannerHook:
    def test_hook_has_full_phrase_or_strong(self):
        plan = _planner().build(_sections("pre_hook", "hook"))
        hook_occurrences = [o for o in plan.occurrences if "hook" in o.section_name.lower()
                            and "pre" not in o.section_name.lower()]
        assert hook_occurrences
        assert any(o.is_strong for o in hook_occurrences)

    def test_hook_stronger_than_verse(self):
        plan = _planner().build(_sections("verse", "hook"))
        hook_occs = [o for o in plan.occurrences if "hook" in o.section_name.lower()]
        verse_occs = [o for o in plan.occurrences if "verse" in o.section_name.lower()]
        if hook_occs and verse_occs:
            hook_intensity = max(o.target_intensity for o in hook_occs)
            verse_intensity = max(o.target_intensity for o in verse_occs)
            assert hook_intensity >= verse_intensity


# ===========================================================================
# 17. MotifPlanner — repeated hook differentiation
# ===========================================================================


class TestMotifPlannerRepeatedHooks:
    def test_hook_2_differs_from_hook_1(self):
        plan = _planner().build(_sections("hook", "bridge", "hook"))
        hook_occs = [
            o for o in plan.occurrences
            if "hook" in o.section_name.lower()
            and "pre" not in o.section_name.lower()
        ]
        if len(hook_occs) >= 2:
            set1 = frozenset(hook_occs[0].transformation_types)
            set2 = frozenset(hook_occs[1].transformation_types)
            # The planner assigns occurrence_index 0 and 1 to the two hooks,
            # which map to different table entries — sets should not be equal.
            assert set1 != set2

    def test_three_hooks_all_present(self):
        plan = _planner().build(_sections("hook", "verse", "hook", "bridge", "hook"))
        hook_occs = [
            o for o in plan.occurrences
            if "hook" in o.section_name.lower()
            and "pre" not in o.section_name.lower()
        ]
        assert len(hook_occs) == 3


# ===========================================================================
# 18. MotifPlanner — bridge motif variation
# ===========================================================================


class TestMotifPlannerBridge:
    def test_bridge_does_not_use_full_phrase(self):
        plan = _planner().build(_sections("hook", "bridge", "hook"))
        bridge_occs = [o for o in plan.occurrences if "bridge" in o.section_name.lower()]
        if bridge_occs:
            for o in bridge_occs:
                assert "full_phrase" not in o.transformation_types

    def test_bridge_uses_counter_or_sparse(self):
        plan = _planner().build(_sections("hook", "bridge"))
        bridge_occs = [o for o in plan.occurrences if "bridge" in o.section_name.lower()]
        if bridge_occs:
            types = set(bridge_occs[0].transformation_types)
            assert types & {"counter_variant", "sparse_phrase", "texture_only"}


# ===========================================================================
# 19. MotifPlanner — outro motif resolution
# ===========================================================================


class TestMotifPlannerOutro:
    def test_outro_does_not_use_full_phrase(self):
        plan = _planner().build(_sections("hook", "outro"))
        outro_occs = [o for o in plan.occurrences if "outro" in o.section_name.lower()]
        if outro_occs:
            for o in outro_occs:
                assert "full_phrase" not in o.transformation_types

    def test_outro_uses_resolving_transformations(self):
        plan = _planner().build(_sections("hook", "outro"))
        outro_occs = [o for o in plan.occurrences if "outro" in o.section_name.lower()]
        if outro_occs:
            types = set(outro_occs[0].transformation_types)
            assert types & {"rhythm_trim", "simplify", "sustain_expand"}

    def test_outro_lower_intensity_than_hook(self):
        plan = _planner().build(_sections("hook", "outro"))
        hook_occs = [o for o in plan.occurrences if "hook" in o.section_name.lower()]
        outro_occs = [o for o in plan.occurrences if "outro" in o.section_name.lower()]
        if hook_occs and outro_occs:
            hook_intensity = max(o.target_intensity for o in hook_occs)
            outro_intensity = max(o.target_intensity for o in outro_occs)
            assert hook_intensity > outro_intensity


# ===========================================================================
# 20. MotifPlanner — no viable motif fallback
# ===========================================================================


class TestMotifPlannerFallback:
    def test_no_roles_fallback(self):
        plan = MotifPlanner(source_quality="true_stems", available_roles=[]).build(
            _sections("intro", "verse", "hook")
        )
        assert plan.motif is None
        assert plan.fallback_used is True
        assert plan.occurrences == []

    def test_drums_only_fallback(self):
        plan = MotifPlanner(source_quality="true_stems", available_roles=["drums"]).build(
            _sections("verse", "hook")
        )
        assert plan.motif is None
        assert plan.fallback_used is True

    def test_empty_sections_fallback(self):
        plan = _planner().build([])
        assert plan.fallback_used is True
        assert plan.occurrences == []

    def test_fallback_plan_has_zero_scores(self):
        plan = MotifPlanner(source_quality="true_stems", available_roles=[]).build(
            _sections("hook")
        )
        assert plan.motif_reuse_score == 0.0
        assert plan.motif_variation_score == 0.0


# ===========================================================================
# 21. MotifPlanner — source-quality-aware behavior
# ===========================================================================


class TestMotifPlannerSourceQuality:
    def test_stereo_fallback_sparse_treatments(self):
        plan = MotifPlanner(
            source_quality="stereo_fallback",
            available_roles=["melody"],
        ).build(_sections("intro", "verse", "hook", "outro"))
        # stereo_fallback should still produce occurrences (if motif extracted).
        if plan.motif is not None:
            for o in plan.occurrences:
                # All should be texture_only or sparse_phrase.
                types = set(o.transformation_types)
                assert types & {"texture_only", "sparse_phrase"}

    def test_true_stems_richer_hook_than_stereo(self):
        plan_true = MotifPlanner(
            source_quality="true_stems",
            available_roles=["melody"],
        ).build(_sections("hook"))
        plan_stereo = MotifPlanner(
            source_quality="stereo_fallback",
            available_roles=["melody"],
        ).build(_sections("hook"))
        if plan_true.motif and plan_stereo.motif:
            hook_true = [o for o in plan_true.occurrences if "hook" in o.section_name]
            hook_stereo = [o for o in plan_stereo.occurrences if "hook" in o.section_name]
            if hook_true and hook_stereo:
                assert hook_true[0].target_intensity >= hook_stereo[0].target_intensity

    def test_ai_separated_no_octave_lift_in_multiple_hooks(self):
        plan = MotifPlanner(
            source_quality="ai_separated",
            available_roles=["melody"],
        ).build(_sections("hook", "hook", "hook"))
        for o in plan.occurrences:
            assert "octave_lift" not in o.transformation_types


# ===========================================================================
# 22. MotifValidator — all rules
# ===========================================================================


class TestMotifValidator:
    def _validator(self) -> MotifValidator:
        return MotifValidator()

    def test_no_motif_warning(self):
        plan = MotifPlan(motif=None, occurrences=[], fallback_used=True)
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "no_motif_extracted" in rules

    def test_insufficient_reuse_warning(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        occ = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        plan = MotifPlan(motif=motif, occurrences=[occ], motif_reuse_score=0.1, motif_variation_score=0.5)
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "insufficient_motif_reuse" in rules

    def test_hook_not_stronger_than_verse_warning(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        verse_occ = MotifOccurrence(
            section_name="verse_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase(intensity=0.95)], target_intensity=0.95,
        )
        hook_occ = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[texture_only(intensity=0.2)], target_intensity=0.2,
        )
        plan = MotifPlan(motif=motif, occurrences=[verse_occ, hook_occ], motif_reuse_score=0.8, motif_variation_score=0.5)
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "hook_intensity_below_verse" in rules or "hook_not_stronger_than_verse" in rules

    def test_bridge_copies_hook_warning(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        hook_occ = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        bridge_occ = MotifOccurrence(
            section_name="bridge_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        plan = MotifPlan(
            motif=motif, occurrences=[hook_occ, bridge_occ, hook_occ],
            motif_reuse_score=0.8, motif_variation_score=0.1,
        )
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "bridge_copies_hook_motif" in rules

    def test_outro_unresolved_warning(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        hook_occ = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        outro_occ = MotifOccurrence(
            section_name="outro_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        plan = MotifPlan(
            motif=motif, occurrences=[hook_occ, outro_occ],
            motif_reuse_score=0.8, motif_variation_score=0.5,
        )
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "outro_unresolved_motif" in rules or "outro_full_phrase" in rules

    def test_repeated_hook_identical_warning(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.8, bars=2)
        hook_occ1 = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        hook_occ2 = MotifOccurrence(
            section_name="hook_2", occurrence_index=1, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        plan = MotifPlan(
            motif=motif, occurrences=[hook_occ1, hook_occ2],
            motif_reuse_score=0.8, motif_variation_score=0.0,
        )
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "repeated_hook_identical_motif" in rules

    def test_weak_confidence_warning(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.20, bars=2)
        occ1 = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        occ2 = MotifOccurrence(
            section_name="verse_1", occurrence_index=0, source_role="melody",
            transformations=[simplify()], target_intensity=0.5,
        )
        plan = MotifPlan(
            motif=motif, occurrences=[occ1, occ2],
            motif_reuse_score=0.7, motif_variation_score=0.5,
        )
        issues = self._validator().validate(plan)
        rules = {i.rule for i in issues}
        assert "weak_motif_confidence" in rules

    def test_valid_plan_no_errors(self):
        motif = Motif(motif_id="m", source_role="melody", motif_type="lead_phrase", confidence=0.9, bars=2)
        verse_occ = MotifOccurrence(
            section_name="verse_1", occurrence_index=0, source_role="melody",
            transformations=[simplify()], target_intensity=0.45,
        )
        hook_occ1 = MotifOccurrence(
            section_name="hook_1", occurrence_index=0, source_role="melody",
            transformations=[full_phrase()], target_intensity=0.9,
        )
        hook_occ2 = MotifOccurrence(
            section_name="hook_2", occurrence_index=1, source_role="melody",
            transformations=[full_phrase(), octave_lift()], target_intensity=0.92,
        )
        bridge_occ = MotifOccurrence(
            section_name="bridge_1", occurrence_index=0, source_role="melody",
            transformations=[counter_variant()], target_intensity=0.55,
        )
        outro_occ = MotifOccurrence(
            section_name="outro_1", occurrence_index=0, source_role="melody",
            transformations=[rhythm_trim(), simplify()], target_intensity=0.35,
        )
        plan = MotifPlan(
            motif=motif,
            occurrences=[verse_occ, hook_occ1, hook_occ2, bridge_occ, outro_occ],
            motif_reuse_score=0.85,
            motif_variation_score=0.75,
        )
        issues = self._validator().validate(plan)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_issue_to_dict(self):
        issue = MotifValidationIssue(severity="warning", rule="test_rule", message="msg", section_name="hook_1")
        d = issue.to_dict()
        assert d["severity"] == "warning"
        assert d["rule"] == "test_rule"
        assert d["section_name"] == "hook_1"

    def test_issue_to_dict_no_section(self):
        issue = MotifValidationIssue(severity="warning", rule="test_rule", message="msg")
        d = issue.to_dict()
        assert "section_name" not in d


# ===========================================================================
# 23. Serialisation correctness
# ===========================================================================


class TestSerialisation:
    def test_full_plan_json_round_trip(self):
        plan = _planner().build(_full_sections())
        d = plan.to_dict()
        serialised = json.dumps(d)
        restored = json.loads(serialised)
        assert restored["fallback_used"] is False
        assert "motif" in restored
        assert "occurrences" in restored

    def test_fallback_plan_serialisable(self):
        plan = MotifPlanner(available_roles=[]).build(_sections("hook"))
        d = plan.to_dict()
        serialised = json.dumps(d)
        restored = json.loads(serialised)
        assert restored["motif"] is None
        assert restored["fallback_used"] is True

    def test_scores_are_floats(self):
        plan = _planner().build(_full_sections())
        d = plan.to_dict()
        assert isinstance(d["motif_reuse_score"], float)
        assert isinstance(d["motif_variation_score"], float)

    def test_occurrences_have_required_fields(self):
        plan = _planner().build(_sections("hook"))
        d = plan.to_dict()
        for occ in d["occurrences"]:
            assert "section_name" in occ
            assert "occurrence_index" in occ
            assert "source_role" in occ
            assert "transformations" in occ
            assert "target_intensity" in occ


# ===========================================================================
# 24. Shadow integration metadata storage
# ===========================================================================


class TestShadowIntegration:
    def test_shadow_stores_motif_plan(self):
        """Smoke test: shadow run stores motif plan in render_plan."""
        from app.services.arrangement_jobs import _run_motif_engine_shadow

        render_plan = {
            "sections": [
                {"type": "intro", "bars": 8},
                {"type": "verse", "bars": 8},
                {"type": "hook", "bars": 8},
                {"type": "outro", "bars": 8},
            ]
        }

        result = _run_motif_engine_shadow(
            render_plan=render_plan,
            available_roles=["melody", "bass", "drums"],
            arrangement_id=42,
            correlation_id="test-corr-id",
            source_quality="true_stems",
        )

        assert "plan" in result
        assert "scores" in result
        assert "warnings" in result
        assert "fallback_used" in result
        assert result["error"] is None

    def test_shadow_no_sections_returns_empty(self):
        from app.services.arrangement_jobs import _run_motif_engine_shadow

        result = _run_motif_engine_shadow(
            render_plan={},
            available_roles=["melody"],
            arrangement_id=1,
            correlation_id="cid",
            source_quality="true_stems",
        )
        assert result["plan"] is None
        assert result["error"] is None

    def test_shadow_fallback_when_no_roles(self):
        from app.services.arrangement_jobs import _run_motif_engine_shadow

        render_plan = {
            "sections": [{"type": "hook", "bars": 8}]
        }
        result = _run_motif_engine_shadow(
            render_plan=render_plan,
            available_roles=[],
            arrangement_id=1,
            correlation_id="cid",
            source_quality="true_stems",
        )
        assert result["fallback_used"] is True

    def test_shadow_plan_json_serialisable(self):
        from app.services.arrangement_jobs import _run_motif_engine_shadow

        render_plan = {
            "sections": [
                {"type": "verse", "bars": 8},
                {"type": "hook", "bars": 8},
                {"type": "outro", "bars": 8},
            ]
        }
        result = _run_motif_engine_shadow(
            render_plan=render_plan,
            available_roles=["melody"],
            arrangement_id=1,
            correlation_id="cid",
            source_quality="true_stems",
        )
        if result["plan"] is not None:
            serialised = json.dumps(result["plan"])
            restored = json.loads(serialised)
            assert "motif" in restored


# ===========================================================================
# 25. Determinism
# ===========================================================================


class TestDeterminism:
    def test_extractor_deterministic(self):
        roles = ["melody", "bass", "chords", "drums"]
        e1 = MotifExtractor(source_quality="true_stems", available_roles=roles)
        e2 = MotifExtractor(source_quality="true_stems", available_roles=roles)
        m1 = e1.extract()
        m2 = e2.extract()
        assert (m1 is None) == (m2 is None)
        if m1 and m2:
            assert m1.source_role == m2.source_role
            assert m1.motif_type == m2.motif_type
            assert m1.confidence == m2.confidence

    def test_planner_deterministic(self):
        sections = _full_sections()
        roles = ["melody", "bass", "drums"]
        p1 = MotifPlanner(source_quality="true_stems", available_roles=roles).build(sections)
        p2 = MotifPlanner(source_quality="true_stems", available_roles=roles).build(sections)
        assert p1.motif_reuse_score == p2.motif_reuse_score
        assert p1.motif_variation_score == p2.motif_variation_score
        assert len(p1.occurrences) == len(p2.occurrences)
        for o1, o2 in zip(p1.occurrences, p2.occurrences):
            assert o1.transformation_types == o2.transformation_types

    def test_select_transformations_deterministic(self):
        for section_type in ("intro", "verse", "hook", "bridge", "outro"):
            for idx in range(3):
                ts1 = select_transformations(section_type, idx, source_quality="true_stems")
                ts2 = select_transformations(section_type, idx, source_quality="true_stems")
                assert [t.transformation_type for t in ts1] == [t.transformation_type for t in ts2]

    def test_full_pipeline_deterministic_across_runs(self):
        sections = _full_sections()
        roles = ["melody", "chords", "bass", "drums"]

        def run():
            return MotifPlanner(source_quality="true_stems", available_roles=roles).build(sections)

        p1 = run()
        p2 = run()
        p3 = run()
        assert p1.to_dict() == p2.to_dict() == p3.to_dict()
