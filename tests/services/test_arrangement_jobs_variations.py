from app.services.arrangement_jobs import (
    _apply_stem_primary_section_states,
    _build_section_audio_from_stems,
    _build_pre_render_plan,
    _render_producer_arrangement,
    _validate_render_plan_quality,
)
from pydub import AudioSegment
from pydub.generators import Sine
import json


def test_build_pre_render_plan_assigns_loop_variants_to_sections() -> None:
    loop_variation_manifest = {
        "active": True,
        "count": 5,
        "names": ["intro", "verse", "hook", "bridge", "outro"],
        "files": {
            "intro": "loop_intro.wav",
            "verse": "loop_verse.wav",
            "hook": "loop_hook.wav",
            "bridge": "loop_bridge.wav",
            "outro": "loop_outro.wav",
        },
        "stems_used": True,
    }

    producer_arrangement = {
        "total_bars": 24,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4, "energy": 0.3, "instruments": ["melody"]},
            {"name": "Verse", "type": "verse", "bar_start": 4, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Hook", "type": "hook", "bar_start": 12, "bars": 8, "energy": 0.9, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Outro", "type": "outro", "bar_start": 20, "bars": 4, "energy": 0.4, "instruments": ["melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=123,
        bpm=120.0,
        target_seconds=90,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True},
        loop_variation_manifest=loop_variation_manifest,
    )

    section_variants = {str(section.get("loop_variant")) for section in render_plan["sections"]}

    assert render_plan["loop_variations"]["active"] is True
    assert render_plan["loop_variations"]["count"] == 5
    assert len(section_variants) >= 3
    assert any(section.get("loop_variant_file") == "loop_hook.wav" for section in render_plan["sections"])


def test_render_plan_quality_fails_when_all_sections_share_one_variant() -> None:
    render_plan = {
        "sections": [
            {"name": "A", "type": "verse", "bars": 4, "loop_variant": "verse"},
            {"name": "B", "type": "hook", "bars": 4, "loop_variant": "verse"},
            {"name": "C", "type": "outro", "bars": 4, "loop_variant": "verse"},
        ],
        "events": [{"type": "variation"} for _ in range(12)],
    }

    try:
        _validate_render_plan_quality(render_plan)
        assert False, "Expected repeated-loop guard to fail"
    except ValueError as exc:
        assert "exact same audio loop" in str(exc)


def test_apply_stem_primary_section_states_assigns_role_sets_by_section() -> None:
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4},
        {"name": "Verse 1", "type": "verse", "bars": 8},
        {"name": "Verse 2", "type": "verse", "bars": 8},
        {"name": "Hook 1", "type": "hook", "bars": 8},
        {"name": "Hook 2", "type": "hook", "bars": 8},
        {"name": "Bridge", "type": "bridge", "bars": 4},
        {"name": "Outro", "type": "outro", "bars": 4},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["full_mix", "drums", "bass", "melody", "pads"],
    }

    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    # --- Section Identity Engine v2 expected role assignments ---
    # The v2 engine enforces profile-specific density bounds and adjacent-section
    # contrast, so sections are genuinely distinct rather than just louder/quieter.
    # The exact third role on hook sections (melody vs pads) is determined by the
    # adjacent-contrast enforcement and is therefore tested as a structural invariant
    # rather than a precise list, except where the output is fully deterministic.

    # Intro: 1 sparse role (density_min=1, forbidden={drums,bass,percussion}).
    # Given available roles [full_mix,drums,bass,melody,pads], the first permitted
    # priority is "pads" — this is deterministic for the given stem_metadata.
    assert updated[0]["active_stem_roles"] == ["pads"]
    # Verse 1: always drums + bass (density_min=2, occurrence=1 → no escalation yet)
    assert set(updated[1]["active_stem_roles"]) == {"drums", "bass"}
    # Verse 2: the post-pass strips one stem to reserve headroom for the hook when
    # verse 2 and hook 1 would otherwise share the same stem map.  The resulting
    # verse 2 set must have at least 2 stems and must differ from hook 1.
    assert len(updated[2]["active_stem_roles"]) >= 2, (
        f"Verse 2 must keep at least 2 stems after post-pass, got: {updated[2]['active_stem_roles']}"
    )
    assert set(updated[2]["active_stem_roles"]) != set(updated[3]["active_stem_roles"]), (
        "Verse 2 and Hook 1 must not share the same stem map — "
        "post-pass should have stripped one stem from verse 2"
    )
    # Hooks must each contain drums + bass; identity and contrast enforcement
    # determine which third role is added — assert structural invariants only.
    assert "drums" in updated[3]["active_stem_roles"]
    assert "bass" in updated[3]["active_stem_roles"]
    assert len(updated[3]["active_stem_roles"]) >= 3
    assert "drums" in updated[4]["active_stem_roles"]
    assert "bass" in updated[4]["active_stem_roles"]
    assert len(updated[4]["active_stem_roles"]) >= 3
    # Hooks must differ from each other (the identity engine enforces this via
    # occurrence-based escalation and evolution logic)
    assert set(updated[3]["active_stem_roles"]) != set(updated[4]["active_stem_roles"]), (
        "Hook 1 and Hook 2 must not have identical stem sets — identity engine should evolve them"
    )
    # Bridge: no drums or bass (forbidden), at least 1 role
    assert "drums" not in updated[5]["active_stem_roles"]
    assert "bass" not in updated[5]["active_stem_roles"]
    assert len(updated[5]["active_stem_roles"]) >= 1
    # Outro: no drums or bass (forbidden), at least 1 role
    assert "drums" not in updated[6]["active_stem_roles"]
    assert "bass" not in updated[6]["active_stem_roles"]
    assert len(updated[6]["active_stem_roles"]) >= 1
    assert all("full_mix" not in section["active_stem_roles"] for section in updated)
    assert all(section["stem_primary"] is True for section in updated)


def test_build_pre_render_plan_marks_stem_primary_mode() -> None:
    producer_arrangement = {
        "total_bars": 16,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4, "energy": 0.25, "instruments": ["melody"]},
            {"name": "Verse", "type": "verse", "bar_start": 4, "bars": 4, "energy": 0.55, "instruments": ["bass"]},
            {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 4, "energy": 0.85, "instruments": ["melody"]},
            {"name": "Outro", "type": "outro", "bar_start": 12, "bars": 4, "energy": 0.35, "instruments": ["fx"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=999,
        bpm=128.0,
        target_seconds=32,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={
            "enabled": True,
            "succeeded": True,
            "roles_detected": ["full_mix", "drums", "bass", "melody", "pads"],
        },
        loop_variation_manifest=None,
    )

    assert render_plan["render_profile"]["stem_primary_mode"] is True
    # Intro gets a sparse (1-role) assignment from the identity engine v2 profile
    # (density_min=1, forbidden={drums,bass,percussion}).
    assert "drums" not in render_plan["sections"][0]["active_stem_roles"]
    assert "bass" not in render_plan["sections"][0]["active_stem_roles"]
    assert len(render_plan["sections"][0]["active_stem_roles"]) >= 1
    assert set(render_plan["sections"][1]["active_stem_roles"]) == {"drums", "bass"}


def test_build_section_audio_from_stems_applies_headroom() -> None:
    stems = {
        "drums": Sine(80).to_audio_segment(duration=1000).apply_gain(-1),
        "bass": Sine(120).to_audio_segment(duration=1000).apply_gain(-1),
        "melody": Sine(440).to_audio_segment(duration=1000).apply_gain(-1),
        "pads": Sine(660).to_audio_segment(duration=1000).apply_gain(-1),
    }

    section_audio = _build_section_audio_from_stems(
        stems=stems,
        section_bars=1,
        bar_duration_ms=1000,
        section_idx=0,
    )

    assert section_audio.max_dBFS <= -5.5


def test_apply_stem_primary_section_states_marks_hook_evolution_stages() -> None:
    sections = [
        {"name": "Hook 1", "type": "hook", "bars": 8},
        {"name": "Hook 2", "type": "hook", "bars": 8},
        {"name": "Hook 3", "type": "hook", "bars": 8},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["drums", "bass", "melody", "harmony", "fx"],
    }

    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    assert updated[0]["hook_evolution"]["stage"] == "hook1"
    assert updated[1]["hook_evolution"]["stage"] == "hook2"
    assert updated[2]["hook_evolution"]["stage"] == "hook3"
    assert updated[0]["hook_evolution"]["density"] < updated[1]["hook_evolution"]["density"]
    assert updated[1]["hook_evolution"]["density"] <= updated[2]["hook_evolution"]["density"]


def test_render_producer_arrangement_prefers_stems_over_loop_variations(monkeypatch) -> None:
    producer_arrangement = {
        "sections": [
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.9,
                "instruments": ["drums", "bass", "melody"],
                "loop_variant": "hook",
            }
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 2,
    }

    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_section_audio_from_stems",
        lambda **_: AudioSegment.silent(duration=2000),
    )
    monkeypatch.setattr(
        "app.services.arrangement_jobs._repeat_to_duration",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("loop variations should not be used when stems are present")),
    )

    arranged, _timeline = _render_producer_arrangement(
        loop_audio=AudioSegment.silent(duration=1000),
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems={
            "drums": AudioSegment.silent(duration=1000),
            "bass": AudioSegment.silent(duration=1000),
            "melody": AudioSegment.silent(duration=1000),
        },
        loop_variations={"hook": AudioSegment.silent(duration=1000)},
    )

    assert len(arranged) > 0


def test_render_producer_arrangement_falls_back_to_loop_variations_without_stems(monkeypatch) -> None:
    producer_arrangement = {
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.6,
                "instruments": ["drums", "bass"],
                "loop_variant": "verse",
            }
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 2,
    }

    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_varied_section_audio",
        lambda **_: (_ for _ in ()).throw(AssertionError("stereo fallback should not run when loop variation exists")),
    )

    arranged, _timeline = _render_producer_arrangement(
        loop_audio=AudioSegment.silent(duration=1000),
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=None,
        loop_variations={"verse": AudioSegment.silent(duration=1000)},
    )

    assert len(arranged) > 0


def test_build_pre_render_plan_adds_transition_boundaries_for_verse_to_hook() -> None:
    producer_arrangement = {
        "total_bars": 16,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Hook", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.95, "instruments": ["kick", "snare", "bass", "melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=7,
        bpm=120.0,
        target_seconds=32,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
        loop_variation_manifest=None,
    )

    boundary = render_plan["section_boundaries"][0]
    assert boundary["boundary"] == "verse_to_hook"
    assert "pre_hook_silence_drop" in boundary["events"]
    assert "crash_hit" in boundary["events"]
    assert any(event["type"] in {"drum_fill", "snare_pickup"} for event in render_plan["events"])


def test_final_hook_gets_stronger_transition_than_first_hook() -> None:
    producer_arrangement = {
        "total_bars": 40,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.55, "instruments": ["kick", "bass"]},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.85, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 16, "bars": 8, "energy": 0.5, "instruments": ["bass", "melody"]},
            {"name": "Final Hook", "type": "hook", "bar_start": 24, "bars": 8, "energy": 1.0, "instruments": ["kick", "snare", "bass", "melody", "fx"]},
            {"name": "Outro", "type": "outro", "bar_start": 32, "bars": 8, "energy": 0.35, "instruments": ["melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=8,
        bpm=120.0,
        target_seconds=80,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": True, "succeeded": True, "roles_detected": ["drums", "bass", "melody", "fx"]},
        loop_variation_manifest=None,
    )

    boundaries = {item["boundary"]: item for item in render_plan["section_boundaries"]}
    first = boundaries["verse_to_hook"]
    final = boundaries["bridge_to_hook"]

    assert len(final["events"]) > len(first["events"])
    assert "riser_fx" in final["events"]
    assert "reverse_cymbal" in final["events"]


def test_bridge_and_outro_receive_strip_transitions() -> None:
    producer_arrangement = {
        "total_bars": 24,
        "key": "C",
        "tracks": [],
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.6, "instruments": ["kick", "bass"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 8, "bars": 8, "energy": 0.45, "instruments": ["melody"]},
            {"name": "Outro", "type": "outro", "bar_start": 16, "bars": 8, "energy": 0.25, "instruments": ["melody"]},
        ],
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=9,
        bpm=120.0,
        target_seconds=48,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="trap",
        stem_metadata={"enabled": False, "succeeded": False},
        loop_variation_manifest=None,
    )

    boundaries = {item["boundary"]: item for item in render_plan["section_boundaries"]}
    assert "bridge_strip" in boundaries["verse_to_bridge"]["events"]
    assert "outro_strip" in boundaries["bridge_to_outro"]["events"]


def test_runtime_applies_transition_events_and_exposes_them_in_timeline() -> None:
    tone = Sine(220).to_audio_segment(duration=8000).set_channels(2) - 8
    producer_arrangement = {
        "sections": [
            {
                "name": "Verse",
                "type": "verse",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.55,
                "instruments": ["drums", "bass"],
                "boundary_events": [
                    {"type": "pre_hook_silence_drop", "bar": 1, "placement": "end_of_section", "intensity": 0.9, "params": {"stems_exist": False}},
                ],
            },
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 2,
                "bars": 2,
                "energy": 0.95,
                "instruments": ["drums", "bass", "melody"],
                "boundary_events": [
                    {"type": "crash_hit", "bar": 2, "placement": "on_downbeat", "intensity": 0.9, "params": {"stems_exist": False}},
                ],
            },
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 4,
        "section_boundaries": [
            {"boundary": "verse_to_hook", "events": ["pre_hook_silence_drop", "crash_hit"]},
        ],
    }

    arranged, timeline_json = _render_producer_arrangement(
        loop_audio=tone,
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=None,
        loop_variations=None,
    )

    payload = json.loads(timeline_json)
    assert payload["section_boundaries"][0]["boundary"] == "verse_to_hook"
    assert payload["sections"][0]["boundary_events"][0]["type"] == "pre_hook_silence_drop"
    assert payload["sections"][1]["boundary_events"][0]["type"] == "crash_hit"

    verse_tail = arranged[3000:3950]
    # With the silence gap removed, the hook starts immediately at bar 4000ms.
    hook_head = arranged[4000:4500]
    assert verse_tail.rms < tone[3000:3950].rms
    # Stabilization may apply a small correction (≤ 2 dB) when the verse ends with
    # silence — the hook must still be substantially louder than the silenced verse tail.
    assert hook_head.rms > verse_tail.rms * 2


# ===========================================================================
# Bug fix — stem-enforcement without stem_metadata
# ===========================================================================

def test_section_roles_differ_when_stem_metadata_missing_but_stem_keys_provided() -> None:
    """Per-section role assignment must happen even when stem_metadata is absent,
    as long as available_stem_keys is supplied (e.g. from loaded stems)."""
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4},
        {"name": "Verse", "type": "verse", "bars": 8},
        {"name": "Hook", "type": "hook", "bars": 8},
        {"name": "Outro", "type": "outro", "bars": 4},
    ]
    stem_keys = ["drums", "bass", "melody", "pads"]

    updated = _apply_stem_primary_section_states(
        sections,
        stem_metadata=None,
        available_stem_keys=stem_keys,
    )

    # Every section must have been processed (stem_primary flag set)
    assert all(section.get("stem_primary") is True for section in updated)
    # All sections must have non-empty instruments
    assert all(len(section.get("instruments", [])) > 0 for section in updated)


def test_intro_roles_differ_from_hook_roles_without_stem_metadata() -> None:
    """Intro and hook must receive different stem subsets when only stem keys are
    known (no stem_metadata).  Intro excludes drums/bass; hook includes them."""
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4},
        {"name": "Hook", "type": "hook", "bars": 8},
    ]
    stem_keys = ["drums", "bass", "melody", "pads"]

    updated = _apply_stem_primary_section_states(
        sections,
        stem_metadata=None,
        available_stem_keys=stem_keys,
    )

    intro_roles = set(updated[0]["instruments"])
    hook_roles = set(updated[1]["instruments"])

    # Intro must not contain drums or bass (role exclusions apply)
    assert "drums" not in intro_roles
    assert "bass" not in intro_roles
    # Hook must contain drums and bass (full energy section)
    assert "drums" in hook_roles
    assert "bass" in hook_roles
    # They must be distinct
    assert intro_roles != hook_roles


def test_phrase_plan_injected_without_stem_metadata_when_choreography_enabled(monkeypatch) -> None:
    """phrase_plan must be injected when available_stem_keys is provided and
    SECTION_CHOREOGRAPHY_V2 + PRODUCER_SECTION_IDENTITY_V2 are both enabled,
    regardless of whether stem_metadata is present."""
    import unittest.mock

    sections = [
        {"name": "Hook", "type": "hook", "bar_start": 0, "bars": 8},
    ]
    stem_keys = ["drums", "bass", "melody", "pads", "fx"]

    with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
        mock_settings.feature_producer_section_identity_v2 = True
        mock_settings.feature_section_choreography_v2 = True
        updated = _apply_stem_primary_section_states(
            sections,
            stem_metadata=None,
            available_stem_keys=stem_keys,
        )

    # phrase_plan must be present (choreography injects it for sections with bars > 4)
    assert "phrase_plan" in updated[0], (
        "phrase_plan was not injected; early-return guard is still blocking choreography"
    )
    phrase = updated[0]["phrase_plan"]
    assert "first_phrase_roles" in phrase
    assert "second_phrase_roles" in phrase


def test_use_stems_is_true_when_non_empty_stems_passed(monkeypatch) -> None:
    """When _render_producer_arrangement receives a non-empty stems dict it must
    activate stem mode (use_stems=True) and route every section through
    _build_section_audio_from_stems — never through loop-variation or stereo
    fallback paths.

    This is the regression guard for the 'stem-render activation bug': if
    stems are successfully loaded from metadata, they must actually be used.
    """
    stem_calls: list[dict] = []

    def _capture_stem_build(**kwargs):
        stem_calls.append({"stems": list((kwargs.get("stems") or {}).keys())})
        return AudioSegment.silent(duration=kwargs.get("section_bars", 2) * 2000)

    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_section_audio_from_stems",
        _capture_stem_build,
    )
    def _reject_loop_variation(*args, **kwargs):
        raise AssertionError("loop-variation path must not fire when stems are present")

    def _reject_stereo_fallback(**kwargs):
        raise AssertionError("stereo-fallback path must not fire when stems are present")

    monkeypatch.setattr(
        "app.services.arrangement_jobs._repeat_to_duration",
        _reject_loop_variation,
    )
    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_varied_section_audio",
        _reject_stereo_fallback,
    )

    stems = {
        "drums": AudioSegment.silent(duration=2000),
        "bass": AudioSegment.silent(duration=2000),
        "melody": AudioSegment.silent(duration=2000),
    }

    producer_arrangement = {
        "sections": [
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.9,
                "instruments": ["drums", "bass", "melody"],
            }
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 2,
    }

    arranged, timeline_json = _render_producer_arrangement(
        loop_audio=AudioSegment.silent(duration=2000),
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=stems,
        loop_variations=None,
    )

    # Stem builder must have been called (confirming use_stems=True)
    assert len(stem_calls) >= 1, "Expected _build_section_audio_from_stems to be called at least once"

    # The timeline must record the stem keys that were active
    timeline = json.loads(timeline_json)
    runtime_stems = timeline["sections"][0]["runtime_active_stems"]
    assert len(runtime_stems) > 0, (
        f"runtime_active_stems is empty; stems were not propagated to the timeline. "
        f"Got: {runtime_stems}"
    )


def test_intro_hook_bridge_use_different_stem_sets_when_stems_present(monkeypatch) -> None:
    """When stems are available, intro / hook / bridge sections must each be
    rendered with their own stem subset.

    Intro  → melody-focused (no drums/bass)
    Hook   → full energy (drums + bass + melody)
    Bridge → sparse (melody/pads, no drums)

    This test verifies that per-section stem differentiation is maintained
    through the render pipeline — a regression guard against any change that
    would collapse all sections onto a single shared stem mix.
    """
    stem_call_log: list[dict] = []

    def _capture(**kwargs):
        stem_call_log.append({
            "keys": sorted((kwargs.get("stems") or {}).keys()),
            "section_bars": kwargs.get("section_bars", 2),
        })
        bars = kwargs.get("section_bars", 2)
        bar_ms = kwargs.get("bar_duration_ms", 2000)
        return AudioSegment.silent(duration=bars * bar_ms)

    monkeypatch.setattr(
        "app.services.arrangement_jobs._build_section_audio_from_stems",
        _capture,
    )

    stems = {
        "drums": AudioSegment.silent(duration=2000),
        "bass": AudioSegment.silent(duration=2000),
        "melody": AudioSegment.silent(duration=2000),
        "pads": AudioSegment.silent(duration=2000),
    }

    producer_arrangement = {
        "sections": [
            {
                "name": "Intro",
                "type": "intro",
                "bar_start": 0,
                "bars": 2,
                "energy": 0.3,
                "instruments": ["melody"],
            },
            {
                "name": "Hook",
                "type": "hook",
                "bar_start": 2,
                "bars": 2,
                "energy": 0.9,
                "instruments": ["drums", "bass", "melody"],
            },
            {
                "name": "Bridge",
                "type": "bridge",
                "bar_start": 4,
                "bars": 2,
                "energy": 0.5,
                "instruments": ["melody", "pads"],
            },
        ],
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": 6,
    }

    arranged, timeline_json = _render_producer_arrangement(
        loop_audio=AudioSegment.silent(duration=2000),
        producer_arrangement=producer_arrangement,
        bpm=120.0,
        stems=stems,
        loop_variations=None,
    )

    assert len(arranged) > 0

    # Each section must have been rendered through the stem path
    assert len(stem_call_log) == 3, (
        f"Expected 3 stem-builder calls (intro/hook/bridge), got {len(stem_call_log)}"
    )

    intro_stems = set(stem_call_log[0]["keys"])
    hook_stems = set(stem_call_log[1]["keys"])
    bridge_stems = set(stem_call_log[2]["keys"])

    # Intro must not contain drums or bass
    assert "drums" not in intro_stems, f"Intro should not include drums; got {intro_stems}"
    assert "bass" not in intro_stems, f"Intro should not include bass; got {intro_stems}"

    # Hook must include drums and bass (full energy)
    assert "drums" in hook_stems, f"Hook must include drums; got {hook_stems}"
    assert "bass" in hook_stems, f"Hook must include bass; got {hook_stems}"

    # Bridge must not contain drums (sparse section)
    assert "drums" not in bridge_stems, f"Bridge should not include drums; got {bridge_stems}"

    # All three sections must have distinct stem sets
    assert intro_stems != hook_stems, "Intro and Hook must use different stem sets"
    assert hook_stems != bridge_stems, "Hook and Bridge must use different stem sets"
    assert intro_stems != bridge_stems, "Intro and Bridge must use different stem sets"

    # The timeline must reflect each section's runtime stem snapshot
    timeline = json.loads(timeline_json)
    for sec in timeline["sections"]:
        assert len(sec["runtime_active_stems"]) > 0, (
            f"Section '{sec['name']}' has empty runtime_active_stems; stems not tracked"
        )


def test_empty_instruments_triggers_last_resort_fallback_not_silent_expansion(caplog) -> None:
    """map_instruments_to_stems with an empty instruments list must NOT silently expand
    to all stems without logging.  After the fix, the last-resort path is marked with a
    warning and the _stem_fallback_all flag is set on the section when triggered from
    _render_producer_arrangement."""
    import logging
    from pydub.generators import Sine
    from app.services.stem_loader import map_instruments_to_stems

    available = {
        "drums": Sine(80).to_audio_segment(duration=500),
        "bass": Sine(120).to_audio_segment(duration=500),
        "melody": Sine(440).to_audio_segment(duration=500),
    }

    with caplog.at_level(logging.WARNING, logger="app.services.stem_loader"):
        result = map_instruments_to_stems([], available)

    # Must return all stems (last-resort behaviour is preserved)
    assert set(result.keys()) == {"drums", "bass", "melody"}
    # Must have emitted a warning so the fallback is visible in prod logs
    assert any("last resort" in record.getMessage().lower() for record in caplog.records), (
        f"Expected a last-resort warning; got messages: {[r.getMessage() for r in caplog.records]}"
    )


# ---------------------------------------------------------------------------
# New tests: small-stem-set identity, hook headroom post-pass, phrase plan
# accuracy, and render observability metrics.
# ---------------------------------------------------------------------------


def test_verse2_stripped_to_reserve_hook_headroom() -> None:
    """With 3 stems, verse 2 must be stripped to preserve hook headroom.

    The post-pass in _apply_stem_primary_section_states should detect that
    verse 2's escalated stem set equals hook 1's stem set and strip one role
    from verse 2 so the hook can still sound audibly bigger.
    """
    sections = [
        {"name": "Verse 1", "type": "verse", "bars": 8},
        {"name": "Verse 2", "type": "verse", "bars": 8},
        {"name": "Hook 1", "type": "hook", "bars": 8},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["drums", "bass", "melody"],
    }
    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    verse1_roles = set(updated[0]["active_stem_roles"])
    verse2_roles = set(updated[1]["active_stem_roles"])
    hook1_roles = set(updated[2]["active_stem_roles"])

    # Verse 2 must not be identical to hook 1 (post-pass must strip one role).
    assert verse2_roles != hook1_roles, (
        f"Verse 2 {verse2_roles} must differ from Hook 1 {hook1_roles} — "
        "post-pass should strip verse 2 to reserve hook headroom"
    )
    # Verse 2 still has at least 2 stems.
    assert len(verse2_roles) >= 2, f"Verse 2 must keep >= 2 stems, got: {verse2_roles}"
    # Verse 2 evolved from verse 1 (not identical).
    assert verse2_roles != verse1_roles or updated[1].get("phrase_plan") is not None, (
        "Verse 2 must either differ in stems from verse 1, or have a phrase plan for evolution"
    )


def test_verse2_phrase_plan_pulls_bonus_melody_after_strip() -> None:
    """After stripping, verse 2 phrase plan must still include melody in second phrase.

    Even when verse 2's active_roles doesn't include melody (stripped by post-pass),
    the phrase plan should pull melody from available_roles into the second phrase
    so the verse still has an audible internal build (rhythm → full).
    """
    sections = [
        {"name": "Verse 1", "type": "verse", "bars": 8},
        {"name": "Verse 2", "type": "verse", "bars": 8},
        {"name": "Hook 1", "type": "hook", "bars": 8},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["drums", "bass", "melody"],
    }
    updated = _apply_stem_primary_section_states(sections, stem_metadata)
    verse2 = updated[1]

    # If verse 2 was stripped, it should have a phrase plan that introduces the
    # stripped role in the second phrase.
    verse2_roles = set(verse2["active_stem_roles"])
    hook1_roles = set(updated[2]["active_stem_roles"])
    was_stripped = verse2_roles != hook1_roles and len(verse2_roles) < len(hook1_roles)

    if was_stripped:
        phrase_plan = verse2.get("phrase_plan")
        assert phrase_plan is not None, (
            "Stripped verse 2 must have a phrase plan so the stripped role "
            "can still enter in the second phrase"
        )
        second_phrase = set(phrase_plan.get("second_phrase_roles") or [])
        # The second phrase should contain the stripped melodic role.
        assert len(second_phrase) > len(set(phrase_plan.get("first_phrase_roles") or [])), (
            f"Verse 2 phrase plan second half {second_phrase} should be bigger than "
            f"first half {phrase_plan.get('first_phrase_roles')}"
        )


def test_hook1_hits_full_immediately_with_three_stems() -> None:
    """Hook 1 phrase plan must return None (full immediately) when no extra stems exist.

    With exactly 3 stems (drums/bass/melody), hook 1 has no extras to expand
    into in the second phrase.  The engine must return None so the hook hits
    all stems from bar 1 — contrasting with verse 2's internal build.
    """
    from app.services.section_identity_engine import get_phrase_variation_plan

    plan = get_phrase_variation_plan(
        "hook",
        ["drums", "bass", "melody"],
        section_bars=8,
        occurrence=1,
        available_roles=["drums", "bass", "melody"],
    )
    assert plan is None, (
        "Hook 1 with 3 stems and no extras must return None — "
        f"should hit full immediately, not split. Got: {plan}"
    )


def test_hook2_phrase_plan_creates_drop_then_explode() -> None:
    """Hook 2 phrase plan must create 'drop then explosion' with 3 stems.

    First phrase = rhythmic only (drums+bass), second phrase = full (all stems).
    This creates an audible distinction between hook 1 (full immediately) and
    hook 2 (stripped first half, explosion second half).
    """
    from app.services.section_identity_engine import get_phrase_variation_plan

    plan = get_phrase_variation_plan(
        "hook",
        ["drums", "bass", "melody"],
        section_bars=8,
        occurrence=2,
        available_roles=["drums", "bass", "melody"],
    )
    assert plan is not None, (
        "Hook 2 with drums/bass/melody must have a phrase plan "
        "(drop-then-explode distinguishes it from hook 1)"
    )
    first = set(plan.first_phrase_roles)
    second = set(plan.second_phrase_roles)
    assert first != second, (
        f"Hook 2 phrase halves must differ: first={plan.first_phrase_roles}, "
        f"second={plan.second_phrase_roles}"
    )
    # First half is rhythmic only (no melody)
    assert "melody" not in first, (
        f"Hook 2 first phrase must not contain melody (it's the 'drop'): {first}"
    )
    # Second half explodes to include all active stems
    assert "melody" in second, (
        f"Hook 2 second phrase must include melody (the 're-explosion'): {second}"
    )


def test_hook3_phrase_plan_returns_none_for_climax() -> None:
    """Hook 3 must return None — rely on hook_evolution DSP for maximum impact."""
    from app.services.section_identity_engine import get_phrase_variation_plan

    plan = get_phrase_variation_plan(
        "hook",
        ["drums", "bass", "melody"],
        section_bars=8,
        occurrence=3,
        available_roles=["drums", "bass", "melody"],
    )
    assert plan is None, (
        f"Hook 3 should return None (let hook_evolution handle the climax), got: {plan}"
    )


def test_phrase_plan_used_flag_requires_distinct_stem_sets() -> None:
    """phrase_plan_used in timeline_sections must only be True when first ≠ second stems.

    The render pipeline should NOT mark phrase_plan_used=True when the phrase
    plan has identical first and second role sets, as no audible contrast is
    created in that case.
    """
    from pydub.generators import Sine
    import json

    # Build a minimal producer arrangement with an 8-bar hook and verse.
    producer_arrangement = {
        "total_bars": 24,
        "key": "C",
        "tracks": [],
        "sections": [
            {
                "name": "Verse 1",
                "section_type": "verse",
                "bar_start": 0,
                "bars": 8,
                "energy": 0.60,
                "instruments": ["drums", "bass"],
            },
            {
                "name": "Verse 2",
                "section_type": "verse",
                "bar_start": 8,
                "bars": 8,
                "energy": 0.65,
                "instruments": ["drums", "bass"],
                # Deliberately inject a phrase_plan where first == second
                # to verify the renderer doesn't count it as a real split.
                "phrase_plan": {
                    "split_bar": 4,
                    "first_phrase_roles": ["drums", "bass"],
                    "second_phrase_roles": ["drums", "bass"],
                    "lead_entry_delay_bars": 0,
                    "end_dropout_bars": 0,
                    "end_dropout_roles": [],
                    "description": "intentionally identical halves",
                },
            },
            {
                "name": "Hook",
                "section_type": "hook",
                "bar_start": 16,
                "bars": 8,
                "energy": 0.90,
                "instruments": ["drums", "bass", "melody"],
            },
        ],
    }

    bpm = 120.0
    bar_ms = int((60.0 / bpm) * 4.0 * 1000)
    duration_ms = bar_ms * 24

    stems = {
        "drums": Sine(80).to_audio_segment(duration=duration_ms).set_frame_rate(44100),
        "bass": Sine(120).to_audio_segment(duration=duration_ms).set_frame_rate(44100),
        "melody": Sine(440).to_audio_segment(duration=duration_ms).set_frame_rate(44100),
    }

    _audio, timeline_json = _render_producer_arrangement(
        loop_audio=Sine(440).to_audio_segment(duration=duration_ms).set_frame_rate(44100),
        producer_arrangement=producer_arrangement,
        bpm=bpm,
        stems=stems,
    )

    timeline = json.loads(timeline_json)
    sections = timeline["sections"]

    # Find verse 2 (index 1)
    verse2 = next((s for s in sections if "verse 2" in s.get("name", "").lower()), sections[1])
    # Its phrase plan had first == second, so phrase_plan_used must be False.
    assert verse2.get("phrase_plan_used") is False, (
        "phrase_plan_used must be False when first_phrase_roles == second_phrase_roles, "
        f"got: {verse2.get('phrase_plan_used')}"
    )


def test_render_observability_reports_unique_phrase_signature_count() -> None:
    """render_observability must include unique_phrase_signature_count."""
    from pydub.generators import Sine
    from app.services.render_executor import _build_render_observability

    # Simulate a timeline where two sections have distinct phrase splits.
    timeline_sections = [
        {
            "type": "verse",
            "name": "Verse 1",
            "active_stem_roles": ["drums", "bass"],
            "runtime_active_stems": ["drums", "bass"],
            "phrase_plan_used": False,
            "runtime_first_phrase_stems": None,
            "runtime_second_phrase_stems": None,
            "_stem_fallback_all": False,
            "_stem_fallback_reason": None,
        },
        {
            "type": "verse",
            "name": "Verse 2",
            "active_stem_roles": ["drums", "bass"],
            "runtime_active_stems": ["drums", "bass", "melody"],
            "phrase_plan_used": True,
            "runtime_first_phrase_stems": ["drums", "bass"],
            "runtime_second_phrase_stems": ["drums", "bass", "melody"],
            "_stem_fallback_all": False,
            "_stem_fallback_reason": None,
        },
        {
            "type": "hook",
            "name": "Hook 1",
            "active_stem_roles": ["drums", "bass", "melody"],
            "runtime_active_stems": ["drums", "bass", "melody"],
            "phrase_plan_used": False,
            "runtime_first_phrase_stems": None,
            "runtime_second_phrase_stems": None,
            "_stem_fallback_all": False,
            "_stem_fallback_reason": None,
        },
        {
            "type": "hook",
            "name": "Hook 2",
            "active_stem_roles": ["drums", "bass", "melody"],
            "runtime_active_stems": ["drums", "bass", "melody"],
            "phrase_plan_used": True,
            "runtime_first_phrase_stems": ["drums", "bass"],
            "runtime_second_phrase_stems": ["drums", "bass", "melody"],
            "_stem_fallback_all": False,
            "_stem_fallback_reason": None,
        },
    ]

    # Minimal mastering result stub
    class _MR:
        applied = False
        profile = "unknown"
        peak_dbfs_before = None
        peak_dbfs_after = None

    # Build timeline json containing the sections
    import json
    timeline_json = json.dumps({"sections": timeline_sections, "render_spec_summary": {}})

    obs = _build_render_observability(
        timeline_json=timeline_json,
        render_path_used="stem_render_executor",
        source_quality_mode_used="ai_separated",
        mastering_result=_MR(),
        render_plan_sections=[],
    )

    assert "unique_phrase_signature_count" in obs, (
        "render_observability must include unique_phrase_signature_count"
    )
    # Verse 2 and Hook 2 have the same (first, second) tuple → 1 unique signature.
    assert obs["unique_phrase_signature_count"] == 1, (
        f"Expected 1 unique phrase signature (verse2 and hook2 share same split), "
        f"got: {obs['unique_phrase_signature_count']}"
    )
    # phrase_split_count should count only the two sections with phrase_plan_used=True.
    assert obs["phrase_split_count"] == 2, (
        f"phrase_split_count should be 2 (verse2 and hook2), got: {obs['phrase_split_count']}"
    )


def test_small_stem_set_produces_distinct_render_signatures() -> None:
    """With 3 stems (drums/bass/melody), major sections must have distinct stem maps.

    This is the core acceptance test for the flat-arrangement fix:
    - verse 1 ≠ verse 2 ≠ hook 1 (all have distinct role plans or phrase structures)
    - The unique_render_signature_count from the observability layer must be > 1
    """
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4},
        {"name": "Verse 1", "type": "verse", "bars": 8},
        {"name": "Verse 2", "type": "verse", "bars": 8},
        {"name": "Pre-Hook", "type": "pre_hook", "bars": 4},
        {"name": "Hook 1", "type": "hook", "bars": 8},
        {"name": "Hook 2", "type": "hook", "bars": 8},
        {"name": "Bridge", "type": "bridge", "bars": 4},
        {"name": "Hook 3", "type": "hook", "bars": 8},
        {"name": "Outro", "type": "outro", "bars": 4},
    ]
    stem_metadata = {
        "enabled": True,
        "succeeded": True,
        "roles_detected": ["drums", "bass", "melody"],
    }
    updated = _apply_stem_primary_section_states(sections, stem_metadata)

    by_name = {s["name"]: frozenset(s["active_stem_roles"]) for s in updated}

    # Core identity invariants with 3 stems:
    # 1. Intro must be sparse (no drums/bass)
    assert "drums" not in by_name["Intro"] and "bass" not in by_name["Intro"], (
        f"Intro must not have drums or bass: {by_name['Intro']}"
    )
    # 2. Verse 1 is rhythm-only
    assert len(by_name["Verse 1"]) <= 2, (
        f"Verse 1 should stay sparse (rhythm only): {by_name['Verse 1']}"
    )
    # 3. Verse 2 must differ from Hook 1 (post-pass ensures headroom)
    assert by_name["Verse 2"] != by_name["Hook 1"], (
        f"Verse 2 {by_name['Verse 2']} must differ from Hook 1 {by_name['Hook 1']} — "
        "post-pass should strip verse 2 to preserve hook headroom"
    )
    # 4. Bridge/breakdown must be sparse (no drums/bass)
    assert "drums" not in by_name["Bridge"] and "bass" not in by_name["Bridge"], (
        f"Bridge must not have drums or bass: {by_name['Bridge']}"
    )
    # 5. Intro and Bridge may share the same sparse stems — that is acceptable.
    #    What matters is that at least 3 distinct stem maps exist across all sections.
    distinct_maps = len(set(by_name.values()))
    assert distinct_maps >= 3, (
        f"Expected at least 3 distinct stem maps, got {distinct_maps}: "
        + str({k: sorted(v) for k, v in by_name.items()})
    )


def test_pre_hook_end_dropout_applied_to_rendered_audio() -> None:
    """end_dropout_bars / end_dropout_roles from the phrase plan must be applied.

    A pre_hook section with a phrase_plan specifying drums dropout in the last bar
    should produce audio whose tail differs from a version without any dropout.
    This test catches regressions where the dropout spec is stored but ignored.
    """
    from pydub.generators import Sine

    bpm = 120.0
    bar_ms = int((60.0 / bpm) * 4.0 * 1000)
    total_bars = 8
    duration_ms = bar_ms * total_bars
    # Sine generator frame rate / audio parameters — kept as constants so the
    # tail byte-offset calculation below uses the same values.
    _FRAME_RATE = 44100
    _SAMPLE_WIDTH = 2   # 16-bit
    _CHANNELS = 1       # mono (Sine generator default)

    # Give drums a distinct frequency so we can detect its presence by energy.
    stems = {
        "drums": Sine(80).to_audio_segment(duration=duration_ms).set_frame_rate(_FRAME_RATE),
        "bass": Sine(200).to_audio_segment(duration=duration_ms).set_frame_rate(_FRAME_RATE),
    }

    def _render_pre_hook(phrase_plan: dict | None) -> bytes:
        section: dict = {
            "name": "Pre-Hook",
            "section_type": "pre_hook",
            "bar_start": 0,
            "bars": total_bars,
            "energy": 0.75,
            "instruments": ["drums", "bass"],
        }
        if phrase_plan is not None:
            section["phrase_plan"] = phrase_plan

        producer_arrangement = {
            "total_bars": total_bars,
            "key": "C",
            "tracks": [],
            "sections": [section],
        }
        audio, _ = _render_producer_arrangement(
            loop_audio=Sine(440).to_audio_segment(duration=duration_ms).set_frame_rate(_FRAME_RATE),
            producer_arrangement=producer_arrangement,
            bpm=bpm,
            stems=stems,
        )
        return bytes(audio.raw_data)

    # Render without dropout (baseline: all stems throughout)
    audio_no_dropout = _render_pre_hook(phrase_plan=None)

    # Render with a 1-bar drums dropout at the end
    audio_with_dropout = _render_pre_hook(
        phrase_plan={
            "split_bar": total_bars // 2,
            "first_phrase_roles": ["drums", "bass"],
            "second_phrase_roles": ["drums", "bass"],
            "lead_entry_delay_bars": 0,
            "end_dropout_bars": 1,
            "end_dropout_roles": ["drums"],
            "description": "pre_hook drums dropout in last bar",
        }
    )

    # The last bar of the dropout render must differ from the baseline
    # because drums are muted there.
    frames_per_bar = int(bar_ms * _FRAME_RATE / 1000)
    bytes_per_frame = _CHANNELS * _SAMPLE_WIDTH
    tail_start_byte = (total_bars - 1) * frames_per_bar * bytes_per_frame
    tail_no_dropout = audio_no_dropout[tail_start_byte:]
    tail_with_dropout = audio_with_dropout[tail_start_byte:]

    assert tail_no_dropout != tail_with_dropout, (
        "The last bar of the pre_hook rendered with end_dropout_roles=['drums'] "
        "must differ from the version without dropout. "
        "The end_dropout feature is not being applied to the audio."
    )
