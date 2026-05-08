from app.services.arrangement_jobs import _apply_producer_taste_decisions, _variation_personality_name


def _mk_section(name, section_type, bars=8, bar_start=0, stems=None):
    return {
        "name": name,
        "type": section_type,
        "bars": bars,
        "bar_start": bar_start,
        "active_stem_roles": list(stems or []),
        "variations": [],
        "boundary_events": [],
    }


def test_variation_personalities_produce_different_event_maps():
    base = _mk_section("verse_1", "verse", stems=["drums", "bass", "melody"])
    next_hook = _mk_section("hook_1", "hook", bar_start=8, stems=["drums", "bass", "melody"])

    s1 = {**base, "variations": [], "boundary_events": []}
    s2 = {**base, "variations": [], "boundary_events": []}
    s3 = {**base, "variations": [], "boundary_events": []}

    _apply_producer_taste_decisions(s1, prev_section=None, next_section=next_hook, variation_index=1)
    _apply_producer_taste_decisions(s2, prev_section=None, next_section=next_hook, variation_index=2)
    _apply_producer_taste_decisions(s3, prev_section=None, next_section=next_hook, variation_index=3)

    v1 = {v["variation_type"] for v in s1["variations"]}
    v2 = {v["variation_type"] for v in s2["variations"]}
    v3 = {v["variation_type"] for v in s3["variations"]}

    assert _variation_personality_name(1) != _variation_personality_name(2)
    assert _variation_personality_name(2) != _variation_personality_name(3)
    assert "fake_drop" not in v1
    assert "fake_drop" in v2
    assert "fake_drop" in v3


def test_hook_payoff_enhancement_changes_hook_events():
    hook = _mk_section("hook_1", "hook", stems=["drums", "bass"])
    tags = _apply_producer_taste_decisions(hook, prev_section=_mk_section("pre", "pre_hook"), next_section=_mk_section("bridge", "bridge"), variation_index=1)
    var_types = {v["variation_type"] for v in hook["variations"]}
    boundary_types = {e["type"] for e in hook["boundary_events"]}
    assert "HOOK_PAYOFF_ENHANCED" in tags
    assert "final_hook_expansion" in var_types
    assert "re_entry_accent" in boundary_types


def test_bridge_contrast_enhancement_reduces_groove_roles_and_adds_events():
    bridge = _mk_section("bridge", "bridge", stems=["drums", "bass", "pads", "melody"])
    tags = _apply_producer_taste_decisions(bridge, prev_section=_mk_section("hook", "hook"), next_section=_mk_section("hook2", "hook"), variation_index=2)
    stems = set(bridge["active_stem_roles"])
    var_types = {v["variation_type"] for v in bridge["variations"]}
    assert "BRIDGE_CONTRAST_ENHANCED" in tags
    assert "drums" not in stems and "bass" not in stems
    assert "bridge_strip" in var_types


def test_transition_smoothing_inserts_overlap_events():
    sec = _mk_section("verse", "verse", stems=["drums", "bass"])
    _apply_producer_taste_decisions(sec, prev_section=None, next_section=_mk_section("hook", "hook"), variation_index=3)
    boundary_types = {e["type"] for e in sec["boundary_events"]}
    assert "crossfade" in boundary_types
    assert "reverse_fx" in boundary_types


def test_drop_intelligence_and_phrase_evolution_mutation_applied():
    sec = _mk_section("verse", "verse", stems=["drums", "bass", "melody"])
    tags = _apply_producer_taste_decisions(sec, prev_section=None, next_section=_mk_section("hook", "hook"), variation_index=3)
    var_types = {v["variation_type"] for v in sec["variations"]}
    assert "DROP_INTELLIGENCE_RENDERED" in tags
    assert "PRODUCER_DECISION_APPLIED" in tags
    assert "pre_hook_drum_mute" in var_types
    assert "bass_pause" in var_types
    assert "call_response_variation" in var_types
