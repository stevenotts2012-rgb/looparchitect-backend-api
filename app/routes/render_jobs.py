
"""Async render job endpoints - Redis queue-based background processing."""

import json
import logging
import random
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.queue import is_redis_available
from app.routes.render import RenderConfig
from app.schemas.job import RenderJobRequest, RenderJobResponse, RenderJobStatusResponse, RenderJobHistoryResponse
from app.services.job_service import create_render_job, get_job_status, list_loop_jobs

router = APIRouter()
logger = logging.getLogger(__name__)

# Safety limits (shared with the synchronous render route)
_MAX_TARGET_SECONDS = 21600   # 6 hours
_MAX_TARGET_BARS = 4096
# Maximum value for a random seed (fits in a 32-bit signed integer, compatible
# with downstream deterministic audio engines).
_MAX_RANDOM_SEED_OUTER = 2**31 - 1  # defined early for use in AsyncRenderRequest limits


# ---------------------------------------------------------------------------
# Request / response models for the async batch-render endpoint
# ---------------------------------------------------------------------------

class AsyncRenderRequest(BaseModel):
    """Request body for POST /loops/{loop_id}/render-async.

    Accepts several aliases for the target duration so that frontends using
    different field names are all supported:

    * ``target_length_seconds``  – primary field name
    * ``duration``               – alias (some frontends use this)
    * ``length``                 – alias (some frontends use this)

    If ``target_bars`` is given it takes precedence over every seconds-based
    field.  If nothing is given the loop's own ``bars`` value is used; if that
    is also absent, a sensible default (32 bars) is applied.
    """

    # Duration fields — the first non-None value wins (priority order below)
    target_length_seconds: Optional[int] = Field(
        None,
        ge=1,
        le=_MAX_TARGET_SECONDS,
        description="Desired arrangement length in seconds",
    )
    duration: Optional[int] = Field(
        None,
        ge=1,
        le=_MAX_TARGET_SECONDS,
        description="Alias for target_length_seconds (frontend compatibility)",
    )
    length: Optional[int] = Field(
        None,
        ge=1,
        le=_MAX_TARGET_SECONDS,
        description="Alias for target_length_seconds (frontend compatibility)",
    )
    target_bars: Optional[int] = Field(
        None,
        ge=1,
        le=_MAX_TARGET_BARS,
        description="Desired arrangement length in bars (overrides seconds fields)",
    )

    variation_count: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Number of distinct arrangement variations to enqueue",
    )
    variation_seed: Optional[int] = Field(
        None,
        ge=0,
        description="Base seed for deterministic variation generation. "
                    "Each variation N receives seed = variation_seed + N",
    )

    genre: Optional[str] = Field("Trap", description="Musical genre hint")
    energy: Optional[str] = Field("medium", description="Energy level hint")


class VariationJobInfo(BaseModel):
    """Info about one enqueued variation job."""

    job_id: str
    variation_index: int = Field(..., description="0-based index of this variation")
    variation_seed: int = Field(..., description="Deterministic seed used for this variation")
    status: str
    poll_url: str
    deduplicated: bool


class AsyncRenderBatchResponse(BaseModel):
    """Response from POST /loops/{loop_id}/render-async.

    Contains one ``VariationJobInfo`` entry per enqueued variation so the
    frontend can poll all N jobs independently.
    """

    loop_id: int
    variation_count: int
    requested_length_seconds: Optional[int] = Field(
        None, description="The target duration that was requested (seconds)"
    )
    actual_length_seconds: Optional[float] = Field(
        None, description="Computed arrangement duration based on bars + BPM"
    )
    section_sequence: List[str] = Field(
        default_factory=list,
        description="Ordered list of section names in the generated arrangement",
    )
    jobs: List[VariationJobInfo]

# ---------------------------------------------------------------------------
# Section layout templates
# ---------------------------------------------------------------------------

# Energy values per section type used when building render_plan_json from a
# ProducerPlan.  These mirror the canonical values in genre_profiles.py.
# verse_2 and hook_2 are intentionally different from their originals so that
# repeated section types are never identical.
_SECTION_ENERGY: Dict[str, float] = {
    "intro": 0.2,
    "verse": 0.5,
    "verse_2": 0.65,   # raised energy: audibly different from verse
    "pre_hook": 0.6,
    "hook": 0.9,
    "hook_2": 1.0,     # peak energy: all layers
    "bridge": 0.45,
    "breakdown": 0.3,
    "outro": 0.2,
}

# Active stem-role subsets per section type.
# verse_2 / hook_2 use a richer role policy than their first appearance.
_FULL_ROLES_SENTINEL = "__full__"
_SECTION_ROLE_POLICY: Dict[str, str] = {
    "intro": "sparse",       # melody only (no drums/bass)
    "verse": "moderate",     # melody + bass + drums
    "verse_2": "full",       # all roles — audible difference vs verse
    "pre_hook": "moderate",
    "hook": "full",          # all roles
    "hook_2": "full",        # all roles — more intense than hook via energy
    "bridge": "sparse",
    "breakdown": "sparse",
    "outro": "sparse",
}

# Additional boundary-event types injected into verse_2 / hook_2 to ensure at
# least 2 audible dimensions differ from the first instance of that section.
_SECTION_BOUNDARY_EVENTS: Dict[str, List[str]] = {
    "verse_2": ["fill", "filter_sweep"],
    "hook_2": ["fill", "chop"],
}

_ROLE_GROUPS = {
    "drums": ("drums", "percussion", "kick", "snare", "hat"),
    "bass": ("bass",),
    "melody": ("melody", "harmony", "pads", "synth", "keys", "lead"),
    "fx": ("fx", "accent", "atmos", "atmosphere"),
}

# Re-export under the shorter name used by helper functions in this module.
_MAX_RANDOM_SEED = _MAX_RANDOM_SEED_OUTER


def _classify_roles(available_roles: List[str]) -> Dict[str, List[str]]:
    """Classify available roles into drum/bass/melody/fx groups."""
    groups: Dict[str, List[str]] = {k: [] for k in _ROLE_GROUPS}
    assigned: set = set()
    for group, keywords in _ROLE_GROUPS.items():
        for role in available_roles:
            role_lower = role.lower()
            if role_lower in keywords or any(kw in role_lower for kw in keywords):
                if role not in assigned:
                    groups[group].append(role)
                    assigned.add(role)
    # Remaining unclassified roles go into melody bucket
    for role in available_roles:
        if role not in assigned:
            groups["melody"].append(role)
    return groups


def _select_roles_for_section(
    section_type: str,
    available_roles: List[str],
    role_groups: Dict[str, List[str]],
) -> List[str]:
    """Return active stem roles for *section_type* from *available_roles*.

    Avoids full_mix unless stems are not available.
    Applies musical rules:
    - intro/bridge/breakdown/outro: sparse (melody only, maybe fx)
    - verse/pre_hook: moderate (melody + bass + drums)
    - hook/hook_2: full (all roles)
    """
    if not available_roles or available_roles == ["full_mix"]:
        return available_roles

    policy = _SECTION_ROLE_POLICY.get(section_type.lower(), "moderate")

    if policy == "sparse":
        roles = role_groups["melody"] + role_groups["fx"]
        return roles if roles else available_roles

    if policy == "moderate":
        roles = role_groups["melody"] + role_groups["bass"] + role_groups["drums"]
        return roles if roles else available_roles

    # "full" — all roles except full_mix sentinel
    return [r for r in available_roles if r != "full_mix"] or available_roles


def _layout_sections(total_bars: int) -> List[Dict]:
    """Return a section layout template for *total_bars*.

    Layout strategy based on target length:

    * < 4 bars  → just ``verse``
    * 4–7 bars  → ``verse`` + ``hook``
    * 8–15 bars → ``intro`` + ``verse`` + ``hook`` + ``outro``
    * 16–31 bars → ``intro`` + ``verse`` + ``hook`` + ``verse_2`` + ``hook_2`` + ``outro``
    * ≥ 32 bars → ``intro`` + ``verse`` + ``hook`` + ``verse_2`` + ``hook_2`` + ``bridge`` + ``outro``

    The section names ``verse_2`` and ``hook_2`` are treated as *distinct* from
    ``verse`` and ``hook`` everywhere in the pipeline (different energy, different
    active roles, different boundary events).  This ensures that repeated source
    material is never rendered identically.

    Args:
        total_bars: Total bars to fill.

    Returns:
        List of section dicts with ``name``, ``bar_start``, ``bar_end``, ``bars``.
    """
    b = total_bars

    if b < 4:
        return [{"name": "verse", "bar_start": 0, "bar_end": b, "bars": b}]

    if b < 8:
        half = b // 2
        return [
            {"name": "verse", "bar_start": 0, "bar_end": half, "bars": half},
            {"name": "hook", "bar_start": half, "bar_end": b, "bars": b - half},
        ]

    if b < 16:
        # 4-section: intro + verse + hook + outro
        # Proportions: 12 / 30 / 40 / 18  (≈ but guaranteed ≥ 2 bars each)
        intro_bars  = max(2, round(b * 0.12))
        hook_bars   = max(2, round(b * 0.40))
        outro_bars  = max(2, round(b * 0.18))
        verse_bars  = b - intro_bars - hook_bars - outro_bars
        if verse_bars < 2:
            hook_bars -= (2 - verse_bars)
            verse_bars = 2
        section_spec = [
            ("intro",  intro_bars),
            ("verse",  verse_bars),
            ("hook",   hook_bars),
            ("outro",  outro_bars),
        ]

    elif b < 32:
        # 6-section: intro + verse + hook + verse_2 + hook_2 + outro
        # Proportions: 8 / 20 / 22 / 20 / 22 / 8
        intro_bars  = max(2, round(b * 0.08))
        verse_bars  = max(2, round(b * 0.20))
        hook_bars   = max(2, round(b * 0.22))
        verse2_bars = max(2, round(b * 0.20))
        outro_bars  = max(2, round(b * 0.08))
        hook2_bars  = b - intro_bars - verse_bars - hook_bars - verse2_bars - outro_bars
        if hook2_bars < 2:
            hook_bars = max(2, hook_bars - (2 - hook2_bars))
            hook2_bars = b - intro_bars - verse_bars - hook_bars - verse2_bars - outro_bars
        section_spec = [
            ("intro",   intro_bars),
            ("verse",   verse_bars),
            ("hook",    hook_bars),
            ("verse_2", verse2_bars),
            ("hook_2",  hook2_bars),
            ("outro",   outro_bars),
        ]

    else:
        # 7-section: intro + verse + hook + verse_2 + hook_2 + bridge + outro
        # Proportions: 6 / 18 / 20 / 18 / 20 / 10 / 8
        intro_bars   = max(2, round(b * 0.06))
        verse_bars   = max(2, round(b * 0.18))
        hook_bars    = max(2, round(b * 0.20))
        verse2_bars  = max(2, round(b * 0.18))
        hook2_bars   = max(2, round(b * 0.20))
        bridge_bars  = max(2, round(b * 0.10))
        outro_bars   = b - intro_bars - verse_bars - hook_bars - verse2_bars - hook2_bars - bridge_bars
        if outro_bars < 2:
            bridge_bars = max(2, bridge_bars - (2 - outro_bars))
            outro_bars = b - intro_bars - verse_bars - hook_bars - verse2_bars - hook2_bars - bridge_bars
        section_spec = [
            ("intro",   intro_bars),
            ("verse",   verse_bars),
            ("hook",    hook_bars),
            ("verse_2", verse2_bars),
            ("hook_2",  hook2_bars),
            ("bridge",  bridge_bars),
            ("outro",   outro_bars),
        ]

    # Build section list with running bar cursor
    cursor = 0
    sections: List[Dict] = []
    for name, bars in section_spec:
        sections.append({
            "name": name,
            "bar_start": cursor,
            "bar_end": cursor + bars,
            "bars": bars,
        })
        cursor += bars

    return sections


def _compute_energy_curve_score(section_names: List[str]) -> float:
    """Compute a 0–1 score expressing how much the energy varies across sections.

    Based on the variance of the per-section energy values; higher variance
    means a more dynamic arrangement.
    """
    energies = [_SECTION_ENERGY.get(name, 0.5) for name in section_names]
    if len(energies) < 2:
        return 0.0
    mean_e = sum(energies) / len(energies)
    variance = sum((e - mean_e) ** 2 for e in energies) / len(energies)
    return round(min(1.0, variance * 10), 4)


def _producer_plan_to_render_plan(
    producer_plan,
    section_templates: List[Dict],
    available_roles: List[str],
    role_groups: Dict[str, List[str]],
    bpm: float,
    loop_id: int,
    genre: str,
    key: str = "C",
) -> dict:
    """Convert a ProducerPlan + section templates into render_plan_json dict.

    The resulting structure is consumed by the worker's
    ``_build_producer_arrangement_from_render_plan`` function.

    For sections whose names appear in ``_SECTION_BOUNDARY_EVENTS`` (i.e.
    ``verse_2`` and ``hook_2``), additional variation events are prepended so
    that those sections differ in at least 2 audible dimensions from their
    first-appearance counterpart.
    """
    # Index events by section name for quick lookup
    events_by_section: Dict[str, list] = {}
    for ev in producer_plan.events:
        events_by_section.setdefault(ev.section_name, []).append(ev)

    sections: List[Dict] = []
    total_bars = 0

    for tmpl in section_templates:
        section_name = tmpl["name"]
        bar_start = tmpl["bar_start"]
        bars = tmpl["bars"]
        total_bars += bars

        energy = _SECTION_ENERGY.get(section_name, 0.5)
        active_roles = _select_roles_for_section(section_name, available_roles, role_groups)

        # Build variation events for this section from ProducerPlan events
        variations: List[Dict] = []
        for ev in events_by_section.get(section_name, []):
            variations.append({
                "bar": ev.bar_start,
                "variation_type": ev.render_action,
                "intensity": ev.intensity,
                "duration_bars": max(1, ev.bar_end - ev.bar_start),
                "description": ev.reason,
                "params": ev.parameters,
            })

        # Inject mandatory boundary events for repeated section types so they
        # differ from their first appearance in ≥ 2 audible dimensions.
        for boundary_event_type in _SECTION_BOUNDARY_EVENTS.get(section_name, []):
            variations.append({
                "bar": bar_start,
                "variation_type": boundary_event_type,
                "intensity": 0.7,
                "duration_bars": max(1, bars // 4),
                "description": f"Boundary {boundary_event_type} injected for section differentiation",
                "params": {},
            })

        sections.append({
            "name": section_name,
            "type": section_name,
            "bar_start": bar_start,
            "bars": bars,
            "energy": energy,
            "active_stem_roles": active_roles,
            "instruments": active_roles,
            "variations": variations,
        })

    # Compute energy_curve score using shared helper
    energy_curve_score = _compute_energy_curve_score([s["name"] for s in sections])

    return {
        "loop_id": loop_id,
        "bpm": bpm,
        "key": key,
        "total_bars": total_bars,
        "sections": sections,
        "events": [],
        "render_profile": {
            "genre_profile": genre or "generic",
            "source": "generative_producer",
            "energy_curve_score": energy_curve_score,
        },
        "metadata": {
            "source": "generative_producer",
            "genre": genre or "generic",
            "section_count": len(sections),
            "energy_curve_score": energy_curve_score,
            "producer_variation_score": producer_plan.section_variation_score,
            "warnings": producer_plan.warnings,
        },
    }


def _build_generative_render_plan(loop: Loop, params: Dict, target_bars: Optional[int] = None, seed: Optional[int] = None) -> dict:
    """Build a render plan using GenerativeProducerOrchestrator.

    Produces a multi-section arrangement with varying energy levels and
    active roles, following musical rules (intro sparse, hook highest energy,
    outro simplified).

    Args:
        loop: The Loop DB object.
        params: Dict with genre / energy / etc.
        target_bars: Total bars for the arrangement.  When provided this
            overrides ``loop.bars`` so the arrangement matches the requested
            duration.  When absent, ``loop.bars`` is used (with a default
            of 32 bars).
        seed: Deterministic seed for the orchestrator.  When absent a random
            seed is chosen.

    Returns a dict ready to be serialised as render_plan_json.
    Raises on failure so the caller can fall back to the minimal plan.
    """
    from app.services.generative_producer_system.orchestrator import GenerativeProducerOrchestrator

    bpm = float(loop.bpm or loop.tempo or 120.0)
    # Use caller-supplied target_bars first, then loop.bars, then safe default
    total_bars: int = target_bars or int(loop.bars or 32)
    genre = (params.get("genre") or loop.genre or "generic").lower().strip()

    # Discover stem roles
    available_roles: List[str] = []
    try:
        stem_roles = loop.stem_roles  # dict of {role: file_key}
        if stem_roles:
            available_roles = list(stem_roles.keys())
    except Exception:
        pass
    if not available_roles:
        available_roles = ["full_mix"]

    role_groups = _classify_roles(available_roles)

    # Build section layout using the target bar count (honours requested length)
    section_templates = _layout_sections(total_bars)

    orchestrator = GenerativeProducerOrchestrator(
        available_roles=available_roles,
        arrangement_id=loop.id,
        correlation_id=f"loop_{loop.id}",
    )

    effective_seed = seed if seed is not None else random.randint(0, _MAX_RANDOM_SEED)
    producer_plan = orchestrator.run(
        sections=section_templates,
        genre=genre,
        vibe=params.get("energy") or "medium",
        seed=effective_seed,
    )

    energy_curve_score = _compute_energy_curve_score([s["name"] for s in section_templates])
    logger.info(
        "producer_plan_generated: loop_id=%s genre=%s section_count=%d "
        "energy_curve_score=%.4f variation_score=%.4f warnings=%d seed=%s",
        loop.id,
        genre,
        len(section_templates),
        energy_curve_score,
        producer_plan.section_variation_score,
        len(producer_plan.warnings),
        effective_seed,
    )

    return _producer_plan_to_render_plan(
        producer_plan=producer_plan,
        section_templates=section_templates,
        available_roles=available_roles,
        role_groups=role_groups,
        bpm=bpm,
        loop_id=loop.id,
        genre=genre,
        key=getattr(loop, "key", None) or getattr(loop, "musical_key", None) or "C",
    )


def _build_minimal_render_plan(loop: Loop, params: Dict, target_bars: Optional[int] = None) -> dict:
    """Build a minimal valid render plan from a loop when no existing plan is available.

    Prefers the caller-supplied *target_bars*, then the loop's own bars value;
    falls back to safe defaults so the worker always receives a well-formed plan.
    """
    bpm = float(loop.bpm or loop.tempo or 120.0)
    total_bars: int = target_bars or int(loop.bars or 32)

    # Discover available stem roles; fall back to a sensible generic set.
    available_roles: list = []
    try:
        stem_roles = loop.stem_roles  # dict of {role: file_key}
        if stem_roles:
            available_roles = list(stem_roles.keys())
    except Exception:
        pass
    if not available_roles:
        available_roles = ["full_mix"]

    sections = _layout_sections(total_bars)

    return {
        "loop_id": loop.id,
        "bpm": bpm,
        "total_bars": total_bars,
        "sections": [
            {
                "name": s["name"],
                "type": s["name"].upper(),
                "start_bar": s["bar_start"],
                "bar_start": s["bar_start"],
                "length_bars": s["bars"],
                "bars": s["bars"],
                "energy": _SECTION_ENERGY.get(s["name"], 0.5),
                "active_stem_roles": available_roles,
                "instruments": available_roles,
                "variations": [
                    {
                        "bar": s["bar_start"],
                        "variation_type": evt,
                        "intensity": 0.7,
                        "duration_bars": max(1, s["bars"] // 4),
                        "description": f"Boundary {evt} for section differentiation",
                        "params": {},
                    }
                    for evt in _SECTION_BOUNDARY_EVENTS.get(s["name"], [])
                ],
            }
            for s in sections
        ],
    }


def _compute_target_bars(loop: Loop, request: "AsyncRenderRequest") -> int:
    """Resolve the target bar count from the request and loop metadata.

    Priority order:
    1. ``request.target_bars``  (explicit bar count)
    2. ``request.target_length_seconds`` converted to bars
    3. ``request.duration`` converted to bars (frontend alias)
    4. ``request.length`` converted to bars (frontend alias)
    5. ``loop.bars`` (the loop's own length)
    6. Hard default of 32 bars

    Conversion formula (4/4 time):
        bars = round(length_seconds / 60 * bpm / 4)
    """
    if request.target_bars is not None:
        return max(1, request.target_bars)

    bpm = float(loop.bpm or loop.tempo or 120.0)

    length_seconds = (
        request.target_length_seconds
        or request.duration
        or request.length
    )
    if length_seconds is not None:
        bars = max(4, round((length_seconds / 60.0) * (bpm / 4.0)))
        return min(bars, _MAX_TARGET_BARS)

    return int(loop.bars or 32)


# ── Async Job Endpoints ───────────────────────────────────────────────────────────
# New async render pipeline using Redis queue

@router.post(
    "/loops/{loop_id}/render-async",
    response_model=AsyncRenderBatchResponse,
    status_code=202,
)
async def render_arrangement_async(
    loop_id: int,
    request: AsyncRenderRequest = Body(default=AsyncRenderRequest()),
    db: Session = Depends(get_db),
):
    """Enqueue *variation_count* render jobs asynchronously.

    Each job uses a different deterministic seed so the N resulting
    arrangements are musically distinct.  The arrangement length is
    controlled by ``target_length_seconds`` (or ``duration`` / ``length``
    aliases) which is converted to bars using the loop's BPM.

    Returns immediately with a list of job_ids.  Poll
    ``GET /api/v1/jobs/{job_id}`` for each job's status.

    Request fields
    --------------
    * ``target_length_seconds`` / ``duration`` / ``length`` – desired
      arrangement length in seconds (mutually equivalent aliases).
    * ``target_bars`` – desired length in bars (overrides seconds fields).
    * ``variation_count`` – number of distinct arrangements to create
      (default 3, max 10).
    * ``variation_seed`` – base seed; variation N receives
      ``variation_seed + N``.  When absent, a random base seed is chosen.
    * ``genre`` – musical genre hint (default ``"Trap"``).
    * ``energy`` – energy level hint (default ``"medium"``).

    Length computation
    ------------------
    ``total_bars = round(target_length_seconds / 60 * bpm / 4)``
    where *bpm* comes from the loop record (or defaults to 120).
    """
    logger.info(
        "render_async_request_received: loop_id=%s variation_count=%s target_length_seconds=%s "
        "target_bars=%s seed=%s",
        loop_id,
        request.variation_count,
        request.target_length_seconds or request.duration or request.length,
        request.target_bars,
        request.variation_seed,
    )

    # Check Redis availability first
    if not is_redis_available():
        raise HTTPException(
            status_code=503,
            detail="Background job queue is unavailable. Redis service may be offline."
        )

    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")

    if not (loop.file_key or loop.file_url):
        raise HTTPException(status_code=400, detail="Loop has no associated audio file")

    # ── Compute arrangement dimensions ───────────────────────────────────────
    target_bars = _compute_target_bars(loop, request)
    bpm = float(loop.bpm or loop.tempo or 120.0)
    # seconds = bars * (4 beats/bar) / (bpm beats/min) * 60 s/min
    actual_length_seconds = round((target_bars * 4 / bpm) * 60, 2)
    requested_length_seconds = (
        request.target_length_seconds or request.duration or request.length
    )

    # Section sequence is identical for all variations (only seed differs)
    section_templates = _layout_sections(target_bars)
    section_sequence = [s["name"] for s in section_templates]

    # ── Choose base seed ──────────────────────────────────────────────────────
    base_seed = (
        request.variation_seed
        if request.variation_seed is not None
        else random.randint(0, _MAX_RANDOM_SEED_OUTER)
    )

    # ── Build per-variation jobs ──────────────────────────────────────────────
    plan_params = {
        "genre": request.genre,
        "energy": request.energy,
    }

    variation_jobs: List[VariationJobInfo] = []

    for var_idx in range(request.variation_count):
        # Each variation gets a unique deterministic seed
        var_seed = (base_seed + var_idx) % (_MAX_RANDOM_SEED + 1)

        # Build render plan (generative, or minimal fallback)
        render_plan_json: Optional[str] = None
        logger.info(
            "render_plan_json_build_started: loop_id=%s variation_index=%d seed=%d",
            loop_id, var_idx, var_seed,
        )

        try:
            generative_plan = _build_generative_render_plan(
                loop, plan_params, target_bars=target_bars, seed=var_seed
            )
            render_plan_json = json.dumps(generative_plan)
            logger.info(
                "render_plan_json_build_success: loop_id=%s variation_index=%d "
                "source=generative_producer section_count=%d energy_curve_score=%.4f",
                loop_id,
                var_idx,
                len(generative_plan.get("sections", [])),
                generative_plan.get("metadata", {}).get("energy_curve_score", 0.0),
            )
        except Exception as gen_err:
            logger.warning(
                "generative_producer_failed: loop_id=%s variation_index=%d error=%s "
                "— falling back to minimal plan",
                loop_id, var_idx, gen_err,
            )
            try:
                minimal_plan = _build_minimal_render_plan(loop, plan_params, target_bars=target_bars)
                render_plan_json = json.dumps(minimal_plan)
                logger.info(
                    "render_plan_json_build_success: loop_id=%s variation_index=%d source=minimal_fallback",
                    loop_id, var_idx,
                )
            except Exception as min_err:
                logger.error(
                    "render_plan_json_missing_failed: loop_id=%s variation_index=%d error=%s",
                    loop_id, var_idx, min_err, exc_info=True,
                )

        if not render_plan_json:
            logger.error(
                "render_plan_json_missing_failed: loop_id=%s variation_index=%d reason=could_not_build_plan",
                loop_id, var_idx,
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not build render_plan_json for this loop. "
                    "Ensure the loop has valid metadata."
                ),
            )

        job_params = {
            "genre": request.genre,
            "energy": request.energy,
            "target_bars": target_bars,
            "variation_seed": var_seed,
            "variation_index": var_idx,
            "variation_count": request.variation_count,
            "requested_length_seconds": requested_length_seconds,
            "actual_length_seconds": actual_length_seconds,
            "section_count": len(section_templates),
            "section_sequence": section_sequence,
            "render_plan_json": render_plan_json,
        }

        try:
            job, was_deduplicated = create_render_job(db, loop_id, job_params)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))

        variation_jobs.append(
            VariationJobInfo(
                job_id=job.id,
                variation_index=var_idx,
                variation_seed=var_seed,
                status=job.status,
                poll_url=f"/api/v1/jobs/{job.id}",
                deduplicated=was_deduplicated,
            )
        )

    return AsyncRenderBatchResponse(
        loop_id=loop_id,
        variation_count=request.variation_count,
        requested_length_seconds=requested_length_seconds,
        actual_length_seconds=actual_length_seconds,
        section_sequence=section_sequence,
        jobs=variation_jobs,
    )



@router.get("/jobs/{job_id}", response_model=RenderJobStatusResponse)
async def get_job_status_endpoint(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Get full status of a render job, including outputs and presigned URLs."""
    try:
        job_status = get_job_status(db, job_id)
        return job_status
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/loops/{loop_id}/jobs", response_model=RenderJobHistoryResponse)
async def get_loop_jobs(
    loop_id: int,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """List all render jobs for a loop (recent first)."""
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if not loop:
        raise HTTPException(status_code=404, detail="Loop not found")
    
    jobs = list_loop_jobs(db, loop_id, limit)
    return RenderJobHistoryResponse(loop_id=loop_id, jobs=jobs)
