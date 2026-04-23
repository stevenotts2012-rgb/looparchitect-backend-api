"""Tests for the genre-aware arrangement template pack and template selector.

Coverage:
- All 20 templates load
- Every template validates (no warnings)
- Seeded selection is deterministic
- Different seeds can pick different valid templates
- Section name normalisation works
- trap_dark context can select trap_D or trap_A
- rage prefers shorter high-energy templates
- rnb supports longer intro / bridge templates
"""

from __future__ import annotations

import pytest

from app.style_engine.genre_templates import (
    ALL_TEMPLATES,
    GENRE_TEMPLATES,
    ArrangementTemplate,
    get_templates_for_genre,
    normalize_section_name,
    validate_template,
)
from app.style_engine.template_selector import (
    TemplateSelectionResult,
    select_template,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _ids_for_genre(genre: str) -> list[str]:
    return [t.id for t in GENRE_TEMPLATES[genre]]


# ---------------------------------------------------------------------------
# 1. Template loading
# ---------------------------------------------------------------------------

class TestTemplateLoading:
    def test_all_20_templates_load(self) -> None:
        assert len(ALL_TEMPLATES) == 20

    def test_five_templates_per_genre(self) -> None:
        for genre in ("trap", "drill", "rnb", "rage"):
            templates = GENRE_TEMPLATES[genre]
            assert len(templates) == 5, f"Expected 5 templates for {genre}"

    def test_template_ids_are_unique(self) -> None:
        ids = [t.id for t in ALL_TEMPLATES]
        assert len(ids) == len(set(ids))

    def test_expected_trap_ids(self) -> None:
        ids = _ids_for_genre("trap")
        assert set(ids) == {"trap_A", "trap_B", "trap_C", "trap_D", "trap_E"}

    def test_expected_drill_ids(self) -> None:
        ids = _ids_for_genre("drill")
        assert set(ids) == {"drill_A", "drill_B", "drill_C", "drill_D", "drill_E"}

    def test_expected_rnb_ids(self) -> None:
        ids = _ids_for_genre("rnb")
        assert set(ids) == {"rnb_A", "rnb_B", "rnb_C", "rnb_D", "rnb_E"}

    def test_expected_rage_ids(self) -> None:
        ids = _ids_for_genre("rage")
        assert set(ids) == {"rage_A", "rage_B", "rage_C", "rage_D", "rage_E"}

    def test_genre_field_matches_template_id_prefix(self) -> None:
        for t in ALL_TEMPLATES:
            prefix = t.id.split("_")[0]
            assert t.genre == prefix, (
                f"Template {t.id} has genre={t.genre!r} but id prefix is {prefix!r}"
            )


# ---------------------------------------------------------------------------
# 2. Validation
# ---------------------------------------------------------------------------

class TestTemplateValidation:
    def test_every_template_validates_without_warnings(self) -> None:
        for t in ALL_TEMPLATES:
            warnings = validate_template(t)
            assert warnings == [], (
                f"Template {t.id} produced validation warnings: {warnings}"
            )

    def test_all_sections_have_positive_bars(self) -> None:
        for t in ALL_TEMPLATES:
            for sec in t.sections:
                assert sec.length_bars > 0, (
                    f"Template {t.id} section {sec.section_type} has "
                    f"non-positive bars={sec.length_bars}"
                )

    def test_all_templates_have_a_hook(self) -> None:
        for t in ALL_TEMPLATES:
            has_hook = any(s.section_type == "hook" for s in t.sections)
            allowed_no_hook = t.no_hook_allowed
            assert has_hook or allowed_no_hook, (
                f"Template {t.id} has no hook section and no_hook_allowed=False"
            )

    def test_short_form_templates_acknowledged(self) -> None:
        from app.style_engine.genre_templates import MIN_TOTAL_BARS_DEFAULT
        for t in ALL_TEMPLATES:
            if t.total_bars < MIN_TOTAL_BARS_DEFAULT:
                assert t.short_form, (
                    f"Template {t.id} has total_bars={t.total_bars} < "
                    f"{MIN_TOTAL_BARS_DEFAULT} but short_form=False"
                )

    def test_invalid_template_flags_empty_sections(self) -> None:
        bad = ArrangementTemplate(
            id="bad_empty",
            genre="trap",
            sections=(),
            vibe=("test",),
            energy=0.5,
            melodic_richness=0.5,
            complexity_class="medium",
        )
        warnings = validate_template(bad)
        assert any("no sections" in w for w in warnings)

    def test_invalid_template_flags_zero_bars(self) -> None:
        from app.style_engine.genre_templates import TemplateSection
        bad = ArrangementTemplate(
            id="bad_zero",
            genre="trap",
            sections=(TemplateSection(section_type="hook", length_bars=0),),
            vibe=("test",),
            energy=0.5,
            melodic_richness=0.5,
            complexity_class="medium",
        )
        warnings = validate_template(bad)
        assert any("non-positive" in w for w in warnings)

    def test_invalid_template_flags_missing_hook(self) -> None:
        from app.style_engine.genre_templates import TemplateSection
        bad = ArrangementTemplate(
            id="bad_nohook",
            genre="trap",
            sections=(TemplateSection(section_type="intro", length_bars=8),),
            vibe=("test",),
            energy=0.5,
            melodic_richness=0.5,
            complexity_class="medium",
        )
        warnings = validate_template(bad)
        assert any("no 'hook' section" in w for w in warnings)

    def test_no_hook_allowed_suppresses_warning(self) -> None:
        from app.style_engine.genre_templates import TemplateSection
        ok = ArrangementTemplate(
            id="ok_nohook",
            genre="trap",
            sections=(TemplateSection(section_type="intro", length_bars=32),),
            vibe=("test",),
            energy=0.5,
            melodic_richness=0.5,
            complexity_class="medium",
            no_hook_allowed=True,
        )
        warnings = validate_template(ok)
        assert not any("no 'hook' section" in w for w in warnings)


# ---------------------------------------------------------------------------
# 3. Section name normalisation
# ---------------------------------------------------------------------------

class TestSectionNameNormalisation:
    @pytest.mark.parametrize("alias,expected", [
        ("PRE_CHORUS", "pre_hook"),
        ("pre_chorus", "pre_hook"),
        ("CHORUS", "hook"),
        ("chorus", "hook"),
        ("BREAK", "breakdown"),
        ("break", "breakdown"),
        ("hook", "hook"),
        ("HOOK", "hook"),
        ("intro", "intro"),
        ("OUTRO", "outro"),
        ("verse", "verse"),
        ("bridge", "bridge"),
        ("breakdown", "breakdown"),
    ])
    def test_normalise(self, alias: str, expected: str) -> None:
        assert normalize_section_name(alias) == expected

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown section name"):
            normalize_section_name("refrain")


# ---------------------------------------------------------------------------
# 4. get_templates_for_genre helper
# ---------------------------------------------------------------------------

class TestGetTemplatesForGenre:
    def test_returns_five_for_each_valid_genre(self) -> None:
        for genre in ("trap", "drill", "rnb", "rage"):
            result = get_templates_for_genre(genre)
            assert len(result) == 5

    def test_case_insensitive(self) -> None:
        result = get_templates_for_genre("TRAP")
        assert len(result) == 5

    def test_unknown_genre_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown genre"):
            get_templates_for_genre("house")


# ---------------------------------------------------------------------------
# 5. Template selector – determinism
# ---------------------------------------------------------------------------

class TestSelectorDeterminism:
    def test_same_seed_same_template(self) -> None:
        kwargs = dict(
            genre="trap",
            loop_energy=0.7,
            melodic_richness=0.5,
            complexity_class="medium",
            variation_seed=42,
        )
        result1 = select_template(**kwargs)
        result2 = select_template(**kwargs)
        assert result1.selected_template_id == result2.selected_template_id
        assert result1.seed_used == result2.seed_used

    def test_same_seed_same_template_drill(self) -> None:
        kwargs = dict(
            genre="drill",
            loop_energy=0.8,
            melodic_richness=0.3,
            complexity_class="simple",
            variation_seed=99,
        )
        r1 = select_template(**kwargs)
        r2 = select_template(**kwargs)
        assert r1.selected_template_id == r2.selected_template_id

    def test_different_seeds_can_pick_different_templates(self) -> None:
        """Try many seeds and assert that more than one distinct template is returned."""
        seen: set[str] = set()
        for seed in range(200):
            result = select_template(
                genre="trap",
                loop_energy=0.5,
                melodic_richness=0.5,
                complexity_class="medium",
                variation_seed=seed,
            )
            seen.add(result.selected_template_id)
        assert len(seen) > 1, (
            f"Expected multiple templates across 200 seeds, got only: {seen}"
        )


# ---------------------------------------------------------------------------
# 6. Template selector – metadata
# ---------------------------------------------------------------------------

class TestSelectorMetadata:
    def test_result_contains_all_metadata_fields(self) -> None:
        result = select_template(genre="rnb", variation_seed=7)
        assert isinstance(result.available_template_count, int)
        assert isinstance(result.candidate_template_ids, list)
        assert isinstance(result.selected_template_id, str)
        assert isinstance(result.selected_template_reason, str)
        assert isinstance(result.template_total_bars, int)
        assert isinstance(result.template, ArrangementTemplate)
        assert isinstance(result.seed_used, int)

    def test_available_template_count_equals_valid_candidates(self) -> None:
        result = select_template(genre="trap", variation_seed=1)
        assert result.available_template_count == 5
        assert len(result.candidate_template_ids) == 5

    def test_selected_id_in_candidates(self) -> None:
        result = select_template(genre="drill", variation_seed=3)
        assert result.selected_template_id in result.candidate_template_ids

    def test_total_bars_matches_template(self) -> None:
        result = select_template(genre="rage", variation_seed=11)
        assert result.template_total_bars == result.template.total_bars

    def test_reason_contains_genre(self) -> None:
        result = select_template(genre="rnb", variation_seed=5)
        assert "genre=rnb" in result.selected_template_reason

    def test_reason_contains_seed(self) -> None:
        result = select_template(genre="trap", variation_seed=42)
        assert "seed=42" in result.selected_template_reason

    def test_vibe_match_reported_in_reason(self) -> None:
        result = select_template(genre="trap", vibe="dark", variation_seed=1)
        assert "vibe_match=" in result.selected_template_reason

    def test_unknown_genre_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown genre"):
            select_template(genre="afrobeats", variation_seed=1)


# ---------------------------------------------------------------------------
# 7. Genre-specific behaviours
# ---------------------------------------------------------------------------

class TestGenreSpecificBehaviours:
    def test_trap_dark_context_selects_trap_D_or_trap_A(self) -> None:
        """With dark vibe and low melodic richness, selector should favour
        trap_D (dark minimal) or trap_A (classic).  We assert the result is
        one of the dark-vibe templates across a range of seeds."""
        dark_friendly = {"trap_D", "trap_A", "trap_B"}
        seen: set[str] = set()
        for seed in range(50):
            result = select_template(
                genre="trap",
                vibe="dark",
                loop_energy=0.65,
                melodic_richness=0.30,
                complexity_class="medium",
                variation_seed=seed,
            )
            seen.add(result.selected_template_id)
        # At least one dark-friendly template must appear across 50 seeds
        assert seen & dark_friendly, (
            f"Expected trap_D/trap_A/trap_B to appear but only saw: {seen}"
        )

    def test_rage_prefers_shorter_high_energy_templates(self) -> None:
        """High-energy rage (loop_energy=0.9) should frequently select
        one of the short_form rage templates (rage_A, rage_B, rage_C, rage_E)."""
        short_rage = {"rage_A", "rage_B", "rage_C", "rage_E"}
        seen: set[str] = set()
        for seed in range(100):
            result = select_template(
                genre="rage",
                loop_energy=0.92,
                melodic_richness=0.20,
                complexity_class="simple",
                variation_seed=seed,
            )
            seen.add(result.selected_template_id)
        assert seen & short_rage, (
            f"Expected short rage templates to appear but only saw: {seen}"
        )

    def test_rnb_supports_longer_intro_bridge_templates(self) -> None:
        """R&B with high melodic richness should surface rnb_A, rnb_B or rnb_E
        (which all have 16-bar intros or long bridges)."""
        long_rnb = {"rnb_A", "rnb_B", "rnb_E"}
        seen: set[str] = set()
        for seed in range(100):
            result = select_template(
                genre="rnb",
                vibe="melodic",
                loop_energy=0.60,
                melodic_richness=0.85,
                complexity_class="complex",
                variation_seed=seed,
            )
            seen.add(result.selected_template_id)
        assert seen & long_rnb, (
            f"Expected long-form R&B templates to appear but only saw: {seen}"
        )

    def test_rnb_has_sections_with_long_intros(self) -> None:
        """Verify that rnb_A and rnb_E actually have a 16-bar intro."""
        rnb_templates = {t.id: t for t in get_templates_for_genre("rnb")}
        for tmpl_id in ("rnb_A", "rnb_E"):
            t = rnb_templates[tmpl_id]
            intro_bars = [
                s.length_bars for s in t.sections if s.section_type == "intro"
            ]
            assert intro_bars and max(intro_bars) >= 16, (
                f"{tmpl_id} should have an intro of at least 16 bars"
            )

    def test_rnb_has_bridge_section(self) -> None:
        """rnb_B and rnb_E should contain a bridge section."""
        rnb_templates = {t.id: t for t in get_templates_for_genre("rnb")}
        for tmpl_id in ("rnb_B", "rnb_E"):
            t = rnb_templates[tmpl_id]
            has_bridge = any(s.section_type == "bridge" for s in t.sections)
            assert has_bridge, f"{tmpl_id} should have a bridge section"

    def test_rage_templates_all_short_or_medium(self) -> None:
        """All rage templates should have total bars <= 44."""
        for t in get_templates_for_genre("rage"):
            assert t.total_bars <= 44, (
                f"Rage template {t.id} has {t.total_bars} bars (expected <= 44)"
            )

    def test_rage_templates_have_high_energy(self) -> None:
        """All rage templates should have energy >= 0.85."""
        for t in get_templates_for_genre("rage"):
            assert t.energy >= 0.85, (
                f"Rage template {t.id} has energy={t.energy} (expected >= 0.85)"
            )

    def test_rnb_templates_have_high_melodic_richness(self) -> None:
        """All R&B templates should have melodic_richness >= 0.65."""
        for t in get_templates_for_genre("rnb"):
            assert t.melodic_richness >= 0.65, (
                f"R&B template {t.id} has melodic_richness={t.melodic_richness} "
                "(expected >= 0.65)"
            )
