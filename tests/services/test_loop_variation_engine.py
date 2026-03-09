from pydub import AudioSegment
from pydub.generators import Sine

from app.services.loop_variation_engine import (
    assign_section_variants,
    generate_loop_variations,
    generate_sub_variants,
    validate_variation_plan_usage,
)


def _tone(freq: int, duration_ms: int = 4000, gain_db: float = -10) -> AudioSegment:
    return Sine(freq).to_audio_segment(duration=duration_ms).apply_gain(gain_db)


def test_generate_loop_variations_creates_required_variants() -> None:
    loop_audio = _tone(220, duration_ms=4000, gain_db=-8)
    stems = {
        "drums": _tone(110, duration_ms=4000, gain_db=-10),
        "bass": _tone(90, duration_ms=4000, gain_db=-11),
        "melody": _tone(440, duration_ms=4000, gain_db=-13),
        "vocal": _tone(660, duration_ms=4000, gain_db=-15),
    }

    variants, manifest = generate_loop_variations(loop_audio=loop_audio, stems=stems, bpm=120.0)

    # Base variants
    assert "intro" in variants
    assert "verse" in variants
    assert "hook" in variants
    assert "bridge" in variants
    assert "outro" in variants
    
    # Sub-variants should be generated
    assert "hook_A" in variants
    assert "hook_B" in variants
    assert "hook_C" in variants
    assert "verse_A" in variants
    assert "verse_B" in variants
    assert "bridge_A" in variants
    assert "bridge_B" in variants
    
    assert manifest["active"] is True
    assert manifest["count"] >= 12  # 5 base + 3 hook + 2 verse + 2 bridge
    assert manifest["stems_used"] is True
    assert manifest["sub_variants_enabled"] is True
    assert manifest["files"]["intro"] == "loop_intro.wav"
    assert manifest["files"]["hook_A"] == "loop_hook_A.wav"


def test_hook_differs_from_verse_and_bridge_differs_from_hook() -> None:
    loop_audio = _tone(240, duration_ms=4000, gain_db=-8)
    stems = {
        "drums": _tone(120, duration_ms=4000, gain_db=-10),
        "bass": _tone(100, duration_ms=4000, gain_db=-11),
        "melody": _tone(480, duration_ms=4000, gain_db=-13),
    }

    variants, _ = generate_loop_variations(loop_audio=loop_audio, stems=stems, bpm=128.0)

    assert variants["hook"].raw_data != variants["verse"].raw_data
    assert variants["bridge"].raw_data != variants["hook"].raw_data


def test_assign_section_variants_and_validate_usage() -> None:
    sections = [
        {"name": "Intro", "type": "intro", "bars": 4, "bar_start": 0},
        {"name": "Verse", "type": "verse", "bars": 8, "bar_start": 4},
        {"name": "Hook", "type": "hook", "bars": 8, "bar_start": 12},
        {"name": "Bridge", "type": "bridge", "bars": 4, "bar_start": 20},
        {"name": "Outro", "type": "outro", "bars": 4, "bar_start": 24},
    ]
    manifest = {
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
        "sub_variants_enabled": False,
    }

    mapped = assign_section_variants(sections, manifest)
    unique = {str(s.get("loop_variant")) for s in mapped}

    assert len(unique) >= 3
    assert mapped[0]["loop_variant_file"] == "loop_intro.wav"

    render_plan = {"sections": mapped}
    validate_variation_plan_usage(render_plan)


def test_generate_sub_variants_creates_distinct_audio() -> None:
    """Test that sub-variant generation creates different audio."""
    base_audio = _tone(440, duration_ms=4000, gain_db=-10)
    
    sub_variants = generate_sub_variants(base_audio, "hook", count=3, bpm=120.0)
    
    assert len(sub_variants) == 3
    assert "hook_A" in sub_variants
    assert "hook_B" in sub_variants
    assert "hook_C" in sub_variants
    
    # Sub-variants should be different from each other
    assert sub_variants["hook_A"].raw_data != sub_variants["hook_B"].raw_data
    assert sub_variants["hook_B"].raw_data != sub_variants["hook_C"].raw_data
    assert sub_variants["hook_A"].raw_data != sub_variants["hook_C"].raw_data
    
    # All should have same duration as base
    assert len(sub_variants["hook_A"]) == len(base_audio)
    assert len(sub_variants["hook_B"]) == len(base_audio)
    assert len(sub_variants["hook_C"]) == len(base_audio)


def test_sub_variants_are_deterministic() -> None:
    """Test that sub-variants generate consistently with same input."""
    base_audio = _tone(440, duration_ms=4000, gain_db=-10)
    
    sub_variants_1 = generate_sub_variants(base_audio, "hook", count=3, bpm=120.0)
    sub_variants_2 = generate_sub_variants(base_audio, "hook", count=3, bpm=120.0)
    
    # Should generate identical audio
    assert sub_variants_1["hook_A"].raw_data == sub_variants_2["hook_A"].raw_data
    assert sub_variants_1["hook_B"].raw_data == sub_variants_2["hook_B"].raw_data
    assert sub_variants_1["hook_C"].raw_data == sub_variants_2["hook_C"].raw_data


def test_assign_section_variants_uses_sub_variant_rotation() -> None:
    """Test that repeated sections get different sub-variants."""
    sections = [
        {"name": "Intro", "type": "intro", "bars": 8, "bar_start": 0},
        {"name": "Hook1", "type": "hook", "bars": 8, "bar_start": 8},
        {"name": "Verse1", "type": "verse", "bars": 16, "bar_start": 16},
        {"name": "Hook2", "type": "hook", "bars": 8, "bar_start": 32},
        {"name": "Verse2", "type": "verse", "bars": 16, "bar_start": 40},
        {"name": "Bridge", "type": "bridge", "bars": 8, "bar_start": 56},
        {"name": "Hook3", "type": "hook", "bars": 8, "bar_start": 64},
        {"name": "Outro", "type": "outro", "bars": 8, "bar_start": 72},
    ]
    
    manifest = {
        "active": True,
        "count": 12,
        "names": [
            "intro", "verse", "hook", "bridge", "outro",
            "hook_A", "hook_B", "hook_C",
            "verse_A", "verse_B",
            "bridge_A", "bridge_B",
        ],
        "files": {name: f"loop_{name}.wav" for name in [
            "intro", "verse", "hook", "bridge", "outro",
            "hook_A", "hook_B", "hook_C",
            "verse_A", "verse_B",
            "bridge_A", "bridge_B",
        ]},
        "stems_used": True,
        "sub_variants_enabled": True,
    }
    
    mapped = assign_section_variants(sections, manifest)
    
    # Check intro uses base variant
    assert mapped[0]["loop_variant"] == "intro"
    assert mapped[0]["section_instance"] == 1
    
    # Check hooks use different sub-variants
    assert mapped[1]["loop_variant"] == "hook_A"  # Hook1
    assert mapped[1]["base_variant"] == "hook"
    assert mapped[1]["section_instance"] == 1
    
    assert mapped[3]["loop_variant"] == "hook_B"  # Hook2
    assert mapped[3]["base_variant"] == "hook"
    assert mapped[3]["section_instance"] == 2
    
    assert mapped[6]["loop_variant"] == "hook_C"  # Hook3
    assert mapped[6]["base_variant"] == "hook"
    assert mapped[6]["section_instance"] == 3
    
    # Check verses use different sub-variants
    assert mapped[2]["loop_variant"] == "verse_A"  # Verse1
    assert mapped[2]["section_instance"] == 1
    
    assert mapped[4]["loop_variant"] == "verse_B"  # Verse2
    assert mapped[4]["section_instance"] == 2
    
    # Check bridge uses sub-variant
    assert mapped[5]["loop_variant"] in ["bridge_A", "bridge"]
    
    # Check outro uses base variant
    assert mapped[7]["loop_variant"] == "outro"


def test_repeated_hooks_are_different() -> None:
    """Test that repeated hook sections receive different audio variants."""
    loop_audio = _tone(440, duration_ms=4000, gain_db=-8)
    stems = {
        "drums": _tone(110, duration_ms=4000, gain_db=-10),
        "bass": _tone(90, duration_ms=4000, gain_db=-11),
        "melody": _tone(440, duration_ms=4000, gain_db=-13),
    }
    
    variants, manifest = generate_loop_variations(loop_audio=loop_audio, stems=stems, bpm=120.0)
    
    # Hook sub-variants should all be different
    assert variants["hook_A"].raw_data != variants["hook_B"].raw_data
    assert variants["hook_B"].raw_data != variants["hook_C"].raw_data
    assert variants["hook_A"].raw_data != variants["hook_C"].raw_data
    
    # Verse sub-variants should be different
    assert variants["verse_A"].raw_data != variants["verse_B"].raw_data


def test_validation_warns_on_repeated_same_variant() -> None:
    """Test that validation allows repeated sections with same variant but logs warning."""
    sections = [
        {"type": "intro", "loop_variant": "intro", "name": "Intro"},
        {"type": "hook", "loop_variant": "hook", "name": "Hook1"},
        {"type": "hook", "loop_variant": "hook", "name": "Hook2"},
        {"type": "hook", "loop_variant": "hook", "name": "Hook3"},
        {"type": "outro", "loop_variant": "outro", "name": "Outro"},
    ]
    
    render_plan = {"sections": sections}
    
    # Should pass validation (3 unique variants) but logs warning about repeated hooks
    validate_variation_plan_usage(render_plan)


def test_validation_passes_with_sub_variants() -> None:
    """Test that validation passes when using sub-variants."""
    sections = [
        {"type": "intro", "loop_variant": "intro", "name": "Intro"},
        {"type": "hook", "loop_variant": "hook_A", "name": "Hook1"},
        {"type": "verse", "loop_variant": "verse_A", "name": "Verse1"},
        {"type": "hook", "loop_variant": "hook_B", "name": "Hook2"},
        {"type": "verse", "loop_variant": "verse_B", "name": "Verse2"},
        {"type": "hook", "loop_variant": "hook_C", "name": "Hook3"},
        {"type": "outro", "loop_variant": "outro", "name": "Outro"},
    ]
    
    render_plan = {"sections": sections}
    
    # Should pass validation without errors
    validate_variation_plan_usage(render_plan)
