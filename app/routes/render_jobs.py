
"""Async render job endpoints - Redis queue-based background processing."""

import json
import logging
import random
from typing import Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.queue import is_redis_available
from app.routes.render import RenderConfig
from app.schemas.job import RenderJobRequest, RenderJobResponse, RenderJobStatusResponse, RenderJobHistoryResponse
from app.services.job_service import create_render_job, get_job_status, list_loop_jobs

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section layout templates
# ---------------------------------------------------------------------------

# Energy values per section type used when building render_plan_json from a
# ProducerPlan.  These mirror the canonical values in genre_profiles.py.
_SECTION_ENERGY: Dict[str, float] = {
    "intro": 0.2,
    "verse": 0.5,
    "pre_hook": 0.6,
    "hook": 0.9,
    "hook_2": 1.0,
    "bridge": 0.45,
    "breakdown": 0.3,
    "outro": 0.2,
}

# Active stem-role subsets per section type.
# Roles listed later in the tuple take priority (most prominent sections get more roles).
_FULL_ROLES_SENTINEL = "__full__"
_SECTION_ROLE_POLICY: Dict[str, str] = {
    "intro": "sparse",      # melody only (no drums/bass)
    "verse": "moderate",    # melody + bass + drums
    "pre_hook": "moderate",
    "hook": "full",         # all roles
    "hook_2": "full",
    "bridge": "sparse",
    "breakdown": "sparse",
    "outro": "sparse",
}

_ROLE_GROUPS = {
    "drums": ("drums", "percussion", "kick", "snare", "hat"),
    "bass": ("bass",),
    "melody": ("melody", "harmony", "pads", "synth", "keys", "lead"),
    "fx": ("fx", "accent", "atmos", "atmosphere"),
}


def _classify_roles(available_roles: List[str]) -> Dict[str, List[str]]:
    """Classify available roles into drum/bass/melody/fx groups."""
    groups: Dict[str, List[str]] = {k: [] for k in _ROLE_GROUPS}
    assigned: set = set()
    for group, keywords in _ROLE_GROUPS.items():
        for role in available_roles:
            if role.lower() in keywords or any(kw in role.lower() for kw in keywords):
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


def _layout_sections(loop_length_bars: int) -> List[Dict]:
    """Return a canonical section layout template for *loop_length_bars*.

    Produces 5 sections (intro, verse, hook, bridge, outro) scaled to the loop
    length.  For very short loops (< 8 bars) the layout collapses to fewer
    sections.
    """
    if loop_length_bars < 4:
        return [{"name": "verse", "bar_start": 0, "bar_end": loop_length_bars, "bars": loop_length_bars}]

    if loop_length_bars < 8:
        half = loop_length_bars // 2
        return [
            {"name": "verse", "bar_start": 0, "bar_end": half, "bars": half},
            {"name": "hook", "bar_start": half, "bar_end": loop_length_bars, "bars": loop_length_bars - half},
        ]

    # Standard 5-section layout.  Proportions: intro 12%, verse 25%, hook 38%, bridge 12%, outro 13%
    b = loop_length_bars
    intro_bars   = max(2, round(b * 0.12))
    verse_bars   = max(2, round(b * 0.25))
    hook_bars    = max(2, round(b * 0.38))
    bridge_bars  = max(2, round(b * 0.12))
    # outro gets whatever remains
    outro_bars   = b - intro_bars - verse_bars - hook_bars - bridge_bars
    if outro_bars < 2:
        # Shrink hook slightly to give outro room
        hook_bars = max(2, hook_bars - (2 - outro_bars))
        outro_bars = b - intro_bars - verse_bars - hook_bars - bridge_bars

    cursor = 0
    sections = []
    for name, bars in [
        ("intro", intro_bars),
        ("verse", verse_bars),
        ("hook", hook_bars),
        ("bridge", bridge_bars),
        ("outro", outro_bars),
    ]:
        sections.append({
            "name": name,
            "bar_start": cursor,
            "bar_end": cursor + bars,
            "bars": bars,
        })
        cursor += bars

    return sections


def _producer_plan_to_render_plan(
    producer_plan,
    section_templates: List[Dict],
    available_roles: List[str],
    role_groups: Dict[str, List[str]],
    bpm: float,
    loop_id: int,
    genre: str,
) -> dict:
    """Convert a ProducerPlan + section templates into render_plan_json dict.

    The resulting structure is consumed by the worker's
    ``_build_producer_arrangement_from_render_plan`` function.
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

    # Compute a simple energy_curve score: variance across section energies
    energies = [_SECTION_ENERGY.get(s["name"], 0.5) for s in sections]
    if len(energies) > 1:
        mean_e = sum(energies) / len(energies)
        variance = sum((e - mean_e) ** 2 for e in energies) / len(energies)
        energy_curve_score = round(min(1.0, variance * 10), 4)
    else:
        energy_curve_score = 0.0

    return {
        "loop_id": loop_id,
        "bpm": bpm,
        "key": "C",
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


def _build_generative_render_plan(loop: Loop, params: Dict) -> dict:
    """Build a render plan using GenerativeProducerOrchestrator.

    Produces a multi-section arrangement with varying energy levels and
    active roles, following musical rules (intro sparse, hook highest energy,
    outro simplified).

    Returns a dict ready to be serialised as render_plan_json.
    Raises on failure so the caller can fall back to the minimal plan.
    """
    from app.services.generative_producer_system.orchestrator import GenerativeProducerOrchestrator

    bpm = float(loop.bpm or loop.tempo or 120.0)
    loop_length_bars = int(loop.bars or 8)
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

    # Build section layout for the orchestrator
    section_templates = _layout_sections(loop_length_bars)

    orchestrator = GenerativeProducerOrchestrator(
        available_roles=available_roles,
        arrangement_id=loop.id,
        correlation_id=f"loop_{loop.id}",
    )

    seed = random.randint(0, 2**31 - 1)
    producer_plan = orchestrator.run(
        sections=section_templates,
        genre=genre,
        vibe=params.get("energy") or "medium",
        seed=seed,
    )

    logger.info(
        "producer_plan_generated: loop_id=%s genre=%s section_count=%d "
        "energy_curve_score=%.4f variation_score=%.4f warnings=%d",
        loop.id,
        genre,
        len(section_templates),
        # Compute energy_curve_score here for log (recomputed below too)
        min(1.0, sum(
            (_SECTION_ENERGY.get(s["name"], 0.5) - 0.5) ** 2
            for s in section_templates
        ) * 10 / max(1, len(section_templates))),
        producer_plan.section_variation_score,
        len(producer_plan.warnings),
    )

    return _producer_plan_to_render_plan(
        producer_plan=producer_plan,
        section_templates=section_templates,
        available_roles=available_roles,
        role_groups=role_groups,
        bpm=bpm,
        loop_id=loop.id,
        genre=genre,
    )


def _build_minimal_render_plan(loop: Loop, params: Dict) -> dict:
    """Build a minimal valid render plan from a loop when no existing plan is available.

    Prefers the loop's own bpm/bars values; falls back to safe defaults so the
    worker always receives a well-formed plan.
    """
    bpm = float(loop.bpm or loop.tempo or 120.0)
    loop_length_bars = int(loop.bars or 8)

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

    return {
        "loop_id": loop.id,
        "bpm": bpm,
        "sections": [
            {
                "name": "full_loop",
                "type": "VERSE",
                "start_bar": 0,
                "length_bars": loop_length_bars,
                "active_stem_roles": available_roles,
                "instruments": available_roles,
            }
        ],
    }


# ── Async Job Endpoints ───────────────────────────────────────────────────────────
# New async render pipeline using Redis queue

@router.post("/loops/{loop_id}/render-async", response_model=RenderJobResponse, status_code=202)
async def render_arrangement_async(
    loop_id: int,
    config: RenderConfig = Body(default=RenderConfig()),
    db: Session = Depends(get_db),
):
    """Enqueue a render job asynchronously.
    
    Returns immediately with job_id. Poll GET /api/v1/jobs/{job_id} for status.
    """
    logger.info("render_async_request_received: loop_id=%s", loop_id)

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

    # ── Build render_plan_json ────────────────────────────────────────────────
    # Prefer an existing arrangement's render_plan_json; otherwise build a
    # minimal valid plan so the worker always receives one.
    render_plan_json: str | None = None

    logger.info("render_plan_json_build_started: loop_id=%s", loop_id)

    try:
        from app.models.arrangement import Arrangement

        existing_arrangement = (
            db.query(Arrangement)
            .filter(
                Arrangement.loop_id == loop_id,
                Arrangement.render_plan_json.isnot(None),
            )
            .order_by(Arrangement.created_at.desc())
            .first()
        )
        if existing_arrangement and existing_arrangement.render_plan_json:
            render_plan_json = existing_arrangement.render_plan_json
            logger.info(
                "render_plan_json_build_success: loop_id=%s source=existing_arrangement arrangement_id=%s",
                loop_id,
                existing_arrangement.id,
            )
        else:
            plan_params = {
                "genre": config.genre,
                "length_seconds": config.length_seconds,
                "energy": config.energy,
            }
            # Try generative producer first; fall back to minimal plan if it fails.
            try:
                generative_plan = _build_generative_render_plan(loop, plan_params)
                render_plan_json = json.dumps(generative_plan)
                logger.info(
                    "render_plan_json_build_success: loop_id=%s source=generative_producer "
                    "section_count=%d energy_curve_score=%.4f",
                    loop_id,
                    len(generative_plan.get("sections", [])),
                    generative_plan.get("metadata", {}).get("energy_curve_score", 0.0),
                )
            except Exception as gen_err:
                logger.warning(
                    "generative_producer_failed: loop_id=%s error=%s — falling back to minimal plan",
                    loop_id,
                    gen_err,
                )
                minimal_plan = _build_minimal_render_plan(loop, plan_params)
                render_plan_json = json.dumps(minimal_plan)
                logger.info(
                    "render_plan_json_build_success: loop_id=%s source=minimal_fallback",
                    loop_id,
                )
    except Exception as plan_err:
        logger.error(
            "render_plan_json_missing_failed: loop_id=%s error=%s",
            loop_id,
            plan_err,
            exc_info=True,
        )
        render_plan_json = None

    if not render_plan_json:
        logger.error(
            "render_plan_json_missing_failed: loop_id=%s reason=could_not_build_plan",
            loop_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Could not build render_plan_json for this loop. Ensure the loop has valid metadata.",
        )

    params = {
        "genre": config.genre,
        "length_seconds": config.length_seconds,
        "energy": config.energy,
        "variations": config.variations,
        "variation_styles": config.variation_styles,
        "custom_style": config.custom_style,
        "render_plan_json": render_plan_json,
    }
    
    try:
        job, was_deduplicated = create_render_job(db, loop_id, params)
        return RenderJobResponse(
            job_id=job.id,
            loop_id=loop_id,
            status=job.status,
            created_at=job.created_at,
            poll_url=f"/api/v1/jobs/{job.id}",
            deduplicated=was_deduplicated,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


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
