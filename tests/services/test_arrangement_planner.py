from app.schemas.arrangement import ArrangementPlannerConfig, ArrangementPlannerInput
from app.services.arrangement_planner import (
    build_fallback_arrangement_plan,
    validate_arrangement_plan,
)


def test_fallback_plan_excludes_full_mix_when_multiple_roles_exist() -> None:
    planner_input = ArrangementPlannerInput(
        bpm=140,
        detected_roles=["full_mix", "drums", "bass", "melody"],
        target_total_bars=64,
        source_type="stem_pack",
    )
    plan = build_fallback_arrangement_plan(
        planner_input=planner_input,
        user_request="Make it energetic and club-ready",
        planner_config=ArrangementPlannerConfig(strict=True, allow_full_mix=True),
    )

    assert len(plan.sections) > 0
    assert all("full_mix" not in section.active_roles for section in plan.sections)


def test_plan_validation_requires_hook_energy_not_below_verse() -> None:
    planner_input = ArrangementPlannerInput(
        bpm=120,
        detected_roles=["drums", "bass", "melody"],
        source_type="loop",
    )
    plan = build_fallback_arrangement_plan(
        planner_input=planner_input,
        user_request=None,
        planner_config=ArrangementPlannerConfig(strict=True),
    )

    verse_index = next(i for i, section in enumerate(plan.sections) if section.type == "verse")
    hook_index = next(i for i, section in enumerate(plan.sections) if section.type == "hook")
    plan.sections[verse_index].energy = 5
    plan.sections[hook_index].energy = 3

    validation = validate_arrangement_plan(plan, planner_input.detected_roles)

    assert validation.valid is False
    assert any("hooks must have energy" in message for message in validation.errors)


def test_empty_roles_returns_empty_valid_plan() -> None:
    planner_input = ArrangementPlannerInput(
        bpm=128,
        detected_roles=[],
        source_type="unknown",
    )
    plan = build_fallback_arrangement_plan(
        planner_input=planner_input,
        user_request="Do your best",
        planner_config=ArrangementPlannerConfig(strict=True),
    )

    validation = validate_arrangement_plan(plan, planner_input.detected_roles)

    assert plan.structure == []
    assert plan.total_bars == 0
    assert plan.sections == []
    assert validation.valid is True
