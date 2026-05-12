from app.services.producer_intelligence.planner import ProducerIntelligencePlanner


def _plan():
    planner = ProducerIntelligencePlanner()
    return planner.generate(
        sections=["intro", "verse_1", "pre_hook", "hook_1", "verse_2", "hook_2", "bridge", "hook_3", "outro"],
        stems=["drums", "bass", "music", "fx", "vocal"],
        style="aggressive_club",
    )


def test_hook_2_bigger_than_hook_1():
    plan = _plan()
    assert plan["hooks"]["hook_2"] > plan["hooks"]["hook_1"]


def test_transitions_vary_and_silence_exists():
    plan = _plan()
    fps = [t["fx"] for t in plan["transitions"]]
    assert len(set(fps)) > 1
    assert any("silence_moment" in fx for fx in fps)


def test_stem_maps_evolve_and_density_changes_over_time():
    plan = _plan()
    stem_fingerprints = [tuple(v) for v in plan["stems"].values()]
    assert len(set(stem_fingerprints)) > 1
    densities = [d[1] for d in plan["state"].section_density_history]
    assert len(set(densities)) > 1


def test_fatigue_prevention_and_narrative_progression():
    plan = _plan()
    assert plan["phrases"]["intro"] == "support_phrase"
    assert "verse" in plan["phrases"]["verse_1"]
    assert "hook" in plan["phrases"]["hook_1"]
    assert "bridge" in plan["phrases"]["bridge"]
    assert "outro" in plan["phrases"]["outro"]


def test_no_flat_energy_curve():
    plan = _plan()
    assert len(set(plan["energy"].values())) > 2
