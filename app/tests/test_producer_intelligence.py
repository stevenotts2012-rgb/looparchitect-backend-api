from app.services.producer_intelligence.planner import ProducerIntelligencePlanner


def _plan():
    planner = ProducerIntelligencePlanner()
    return planner.generate(
        sections=["intro", "verse_1", "hook_1", "verse_2", "hook_2", "bridge", "hook_3", "outro"],
        stems=["drums", "bass", "music", "fx", "vocal"],
        style="edm",
    )


def test_hooks_escalate():
    plan = _plan()
    assert plan["hooks"]["hook_2"] > plan["hooks"]["hook_1"]


def test_verse_2_differs_from_verse_1():
    plan = _plan()
    assert plan["phrases"]["verse_2"] != plan["phrases"]["verse_1"]


def test_bridge_lowers_energy_and_outro_simplifies():
    plan = _plan()
    assert plan["energy"]["bridge"] < plan["energy"]["hook_2"]
    assert plan["energy"]["outro"] < plan["energy"]["hook_3"]


def test_transitions_and_density_evolve_and_no_identical_stem_maps():
    plan = _plan()
    assert len(plan["transitions"]) == 7
    densities = [d[1] for d in plan["state"].section_density_history]
    assert len(set(densities)) > 1
    stem_fingerprints = [tuple(v) for v in plan["stems"].values()]
    assert len(set(stem_fingerprints)) > 1


def test_energy_curve_not_flat():
    plan = _plan()
    assert len(set(plan["energy"].values())) > 2
