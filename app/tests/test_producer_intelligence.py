import pytest

from app.services.producer_intelligence.planner import ProducerIntelligencePlanner


def _plan():
    planner = ProducerIntelligencePlanner()
    return planner.generate(
        sections=["intro", "verse_1", "pre_hook", "hook_1", "verse_2", "hook_2", "bridge", "hook_3", "outro"],
        stems=["drums", "bass", "melody", "pad", "vocal"],
        style="aggressive_club",
    )


def test_melody_role_stays_active_and_hooks_include_melodic_role():
    plan = _plan()
    melodic = ("melody", "pad", "harmony", "vocal", "synth", "arp")
    for sec, roles in plan["stems"].items():
        assert any(m in r.lower() for r in roles for m in melodic)
    assert any(m in r.lower() for r in plan["stems"]["hook_1"] for m in melodic)


def test_bridge_features_melodic_texture_and_hook2_bigger():
    plan = _plan()
    assert any(t in plan["phrases"]["bridge"] for t in ("bridge", "melodic"))
    assert plan["hooks"]["hook_2"] > plan["hooks"]["hook_1"]


def test_drum_bass_dominance_metrics_and_presence_score():
    plan = _plan()
    assert plan["melody_presence_score"] > 0
    assert plan["drum_bass_dominance_score"] >= 0
    assert plan["mix_balance_guard_applied"] is True


def test_transitions_vary_and_silence_exists_density_changes():
    plan = _plan()
    fps = [t["fx"] for t in plan["transitions"]]
    assert len(set(fps)) > 1
    assert any("silence_moment" in fx for fx in fps)
    densities = [d[1] for d in plan["state"].section_density_history]
    assert len(set(densities)) > 1


def test_generic_arrangement_with_buried_melody_rejected():
    planner = ProducerIntelligencePlanner()
    with pytest.raises(ValueError):
        planner.generate(
            sections=["intro", "verse_1", "hook_1", "bridge", "outro"],
            stems=["drums", "bass", "kick", "808"],
            style="dark_atl",
        )
