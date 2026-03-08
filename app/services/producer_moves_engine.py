"""Producer Moves Engine: injects producer-style musical events into render plans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MoveEvent:
    type: str
    bar: int
    description: str
    section_name: str | None = None
    section_type: str | None = None
    intensity: float = 0.7
    duration_bars: int | None = None

    def to_dict(self) -> dict:
        payload = {
            "type": self.type,
            "bar": self.bar,
            "description": self.description,
            "intensity": self.intensity,
        }
        if self.section_name:
            payload["section_name"] = self.section_name
        if self.section_type:
            payload["section_type"] = self.section_type
        if self.duration_bars is not None:
            payload["duration_bars"] = int(self.duration_bars)
        return payload


class ProducerMovesEngine:
    """Generate reusable move events from section layout."""

    @staticmethod
    def inject(render_plan: dict) -> dict:
        sections = list(render_plan.get("sections") or [])
        if not sections:
            return render_plan

        events = list(render_plan.get("events") or [])
        moves: list[dict] = []

        hook_indices = [
            idx for idx, section in enumerate(sections)
            if str(section.get("type", "")).strip().lower() in {"hook", "chorus", "drop"}
        ]
        final_hook_idx = hook_indices[-1] if hook_indices else None

        for idx, section in enumerate(sections):
            section_name = str(section.get("name") or f"Section {idx + 1}")
            section_type = str(section.get("type") or "verse").strip().lower()
            bar_start = int(section.get("bar_start", 0) or 0)
            bars = max(1, int(section.get("bars", 1) or 1))
            bar_end = bar_start + bars

            if section_type in {"hook", "chorus", "drop"}:
                if bar_start > 0:
                    moves.append(
                        MoveEvent(
                            type="pre_hook_drum_mute",
                            bar=max(0, bar_start - 1),
                            description="Pre-hook drum mute for anticipation",
                            section_name=section_name,
                            section_type=section_type,
                            intensity=0.8,
                        ).to_dict()
                    )
                    moves.append(
                        MoveEvent(
                            type="silence_drop_before_hook",
                            bar=max(0, bar_start - 1),
                            description="Silence drop before hook impact",
                            section_name=section_name,
                            section_type=section_type,
                            intensity=0.9,
                        ).to_dict()
                    )

                step = 4 if bars >= 8 else 2
                for hat_bar in range(bar_start, bar_end, step):
                    moves.append(
                        MoveEvent(
                            type="hat_density_variation",
                            bar=hat_bar,
                            description="Hat roll / density variation",
                            section_name=section_name,
                            section_type=section_type,
                            intensity=0.7,
                        ).to_dict()
                    )

                for cr_bar in range(bar_start + 2, bar_end, 4):
                    moves.append(
                        MoveEvent(
                            type="call_response_variation",
                            bar=cr_bar,
                            description="Call-and-response variation",
                            section_name=section_name,
                            section_type=section_type,
                            intensity=0.65,
                        ).to_dict()
                    )

                if final_hook_idx is not None and idx == final_hook_idx:
                    moves.append(
                        MoveEvent(
                            type="final_hook_expansion",
                            bar=bar_start,
                            description="Final hook expansion",
                            section_name=section_name,
                            section_type=section_type,
                            intensity=1.0,
                            duration_bars=bars,
                        ).to_dict()
                    )

            if section_type == "verse":
                moves.append(
                    MoveEvent(
                        type="verse_melody_reduction",
                        bar=bar_start,
                        description="Verse melody reduction for vocal space",
                        section_name=section_name,
                        section_type=section_type,
                        intensity=0.7,
                        duration_bars=bars,
                    ).to_dict()
                )

            if section_type in {"bridge", "breakdown", "break"}:
                moves.append(
                    MoveEvent(
                        type="bridge_bass_removal",
                        bar=bar_start,
                        description="Bridge bass removal",
                        section_name=section_name,
                        section_type=section_type,
                        intensity=0.8,
                        duration_bars=bars,
                    ).to_dict()
                )

            if section_type == "outro":
                moves.append(
                    MoveEvent(
                        type="outro_strip_down",
                        bar=bar_start,
                        description="Outro strip-down",
                        section_name=section_name,
                        section_type=section_type,
                        intensity=0.8,
                        duration_bars=bars,
                    ).to_dict()
                )

            moves.append(
                MoveEvent(
                    type="end_section_fill",
                    bar=max(bar_start, bar_end - 1),
                    description="End-of-section fill",
                    section_name=section_name,
                    section_type=section_type,
                    intensity=0.7,
                ).to_dict()
            )

        merged_events = events + moves
        merged_events.sort(key=lambda item: int(item.get("bar", 0) or 0))
        render_plan["events"] = merged_events
        render_plan["events_count"] = len(merged_events)
        render_plan.setdefault("render_profile", {})["producer_moves_enabled"] = True
        render_plan["render_profile"]["producer_moves_count"] = len(moves)
        return render_plan
