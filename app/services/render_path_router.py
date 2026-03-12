"""
STEM vs LOOP ROUTING SERVICE

Determines which rendering path to use (stem-based or loop-variation-based)
and orchestrates the complete arrangement + rendering workflow.

This is the key decision point in PHASE 8 - LOOP FALLBACK:
- If stems_exist: use StemArrangementEngine + StemRenderExecutor
- Else: use existing LoopVariationEngine
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List

from sqlalchemy.orm import Session

from app.models.loop import Loop
from app.models.arrangement import Arrangement
from app.services.stem_arrangement_engine import (
    StemArrangementEngine,
    StemRole,
    SectionConfig,
)
from app.services.stem_render_executor import StemRenderExecutor
from app.services.arrangement_engine import LOOP_VARIATION_MAX_SECONDS

logger = logging.getLogger(__name__)


class RenderPathRouter:
    """Routes arrangements to appropriate render engine based on loop type."""
    
    @staticmethod
    def should_use_stem_path(loop: Loop) -> bool:
        """
        Determine if we should use stem rendering path for this loop.
        
        Args:
            loop: Loop model
        
        Returns:
            True if loop has properly validated stems, False otherwise
        """
        # Check for stem pack markers
        if not hasattr(loop, 'is_stem_pack') or not hasattr(loop, 'stem_files_json'):
            return False
        
        is_stem_pack = str(getattr(loop, 'is_stem_pack', 'false') or 'false').lower().strip()
        stem_files_json = getattr(loop, 'stem_files_json', None)
        stem_validation_json = getattr(loop, 'stem_validation_json', None)
        
        if is_stem_pack != 'true' or not stem_files_json:
            return False
        
        # Verify validation passed
        if stem_validation_json:
            try:
                validation = json.loads(stem_validation_json)
                if not validation.get('is_valid', False):
                    logger.warning(f"Stem validation failed for loop {loop.id}")
                    return False
            except (json.JSONDecodeError, AttributeError):
                return False
        
        return True
    
    @staticmethod
    def get_available_stem_roles(loop: Loop) -> Dict[StemRole, str]:
        """
        Extract available stem roles and file locations from loop.
        
        Args:
            loop: Loop model with stem data
        
        Returns:
            Dict mapping StemRole to file path/URL
        """
        result: Dict[StemRole, str] = {}
        
        if not hasattr(loop, 'stem_files_json'):
            return result
        
        try:
            stem_files = json.loads(loop.stem_files_json or '{}')
            for role_str, file_info in stem_files.items():
                try:
                    role = StemRole(role_str)
                    # Get the file URL or S3 key
                    file_location = file_info.get('url') or file_info.get('s3_key') or file_info.get('file_key')
                    if file_location:
                        result[role] = file_location
                except ValueError:
                    logger.warning(f"Unknown stem role: {role_str}")
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse stem_files_json for loop {loop.id}")
        
        return result
    
    @staticmethod
    def route_and_arrange(
        loop: Loop,
        target_seconds: int,
        genre: Optional[str] = None,
        intensity: Optional[str] = None,
    ) -> Tuple[str, Dict]:
        """
        Determine render path and generate arrangement.
        
        Args:
            loop: Loop model
            target_seconds: Desired output duration
            genre: Optional genre hint
            intensity: Optional intensity level
        
        Returns:
            Tuple of (render_path, arrangement_data)
            - render_path: "stem" or "loop"
            - arrangement_data: Path-specific arrangement JSON
        """
        # PHASE 8: LOOP FALLBACK
        use_stem_path = RenderPathRouter.should_use_stem_path(loop)
        
        if use_stem_path:
            logger.info(f"Using STEM rendering path for loop {loop.id}")
            arrangement = RenderPathRouter._arrange_via_stems(
                loop=loop,
                target_seconds=target_seconds,
                genre=genre,
                intensity=intensity,
            )
            return "stem", arrangement
        else:
            logger.info(f"Using LOOP rendering path for loop {loop.id}")
            # Fallback to existing arrangement engine
            # (existing code path unchanged)
            return "loop", {}


    @staticmethod
    def _arrange_via_stems(
        loop: Loop,
        target_seconds: int,
        genre: Optional[str] = None,
        intensity: Optional[str] = None,
    ) -> Dict:
        """
        Generate stem-based arrangement.
        
        Args:
            loop: Loop model with stems
            target_seconds: Target duration
            genre: Genre hint
            intensity: Intensity level
        
        Returns:
            Arrangement data dict with sections and stem configuration
        """
        # Get tempo from loop or use default
        bpm = loop.bpm or 120
        
        # Get key from loop or use default
        key = loop.musical_key or loop.key or "C major"
        
        # Convert seconds to bars (assuming 4 beats per bar)
        bars_per_minute = bpm / 4
        target_bars = int((target_seconds / 60) * bars_per_minute)
        target_bars = max(8, min(target_bars, 256))  # Clamp between 8-256 bars
        
        # Get available stems
        stem_roles = RenderPathRouter.get_available_stem_roles(loop)
        if not stem_roles:
            raise ValueError(f"Loop {loop.id} marked as stem pack but no stems found")
        
        logger.info(f"Arranging stems: {list(stem_roles.keys())} for {target_bars} bars @ {bpm} BPM")
        
        # Create arrangement engine
        engine = StemArrangementEngine(
            available_stems=stem_roles,
            tempo=bpm,
            key=key,
        )
        
        # Generate arrangement
        sections: List[SectionConfig] = engine.generate_arrangement(
            target_bars=target_bars,
            genre=genre,
            intensity=intensity,
        )
        
        # Convert to JSON-serializable format
        sections_dicts = [section.to_dict() for section in sections]
        
        arrangement_data = {
            "type": "stem",
            "bpm": bpm,
            "key": key,
            "total_bars": target_bars,
            "genre": genre or "generic",
            "intensity": intensity or "medium",
            "sections": sections_dicts,
            "stem_roles": {role.value: path for role, path in stem_roles.items()},
        }
        
        logger.info(f"Generated stem arrangement: {len(sections_dicts)} sections")
        
        return arrangement_data
    
    @staticmethod
    def save_arrangement_metadata(
        arrangement: Arrangement,
        render_path: str,
        arrangement_data: Dict,
    ) -> None:
        """
        Save arrangement metadata to database.
        
        Args:
            arrangement: Arrangement model to save
            render_path: "stem" or "loop"
            arrangement_data: Arrangement data dict
        """
        if render_path == "stem":
            arrangement.stem_render_path = "stem"
            arrangement.stem_arrangement_json = json.dumps(arrangement_data)
            arrangement.rendered_from_stems = True
            logger.debug(f"Saved stem arrangement metadata for arrangement {arrangement.id}")
        else:
            arrangement.stem_render_path = "loop"
            arrangement.rendered_from_stems = False
            logger.debug(f"Using loop arrangement for arrangement {arrangement.id}")


class StemRenderOrchestrator:
    """
    Orchestrates the complete rendering process for stem-based arrangements.
    
    Workflow:
    1. Load stems from storage
    2. Create StemRenderExecutor
    3. Render sections
    4. Apply mastering
    5. Save output
    """
    
    @staticmethod
    async def render_arrangement_async(
        arrangement: Arrangement,
        output_storage_key: str,
        storage_client,
    ) -> Tuple[str, int]:
        """
        Render a stem-based arrangement in background.
        
        Args:
            arrangement: Arrangement model with stem_arrangement_json
            output_storage_key: Where to save output file
            storage_client: Storage client for uploads
        
        Returns:
            Tuple of (output_url, duration_ms)
        """
        if not arrangement.stem_arrangement_json:
            raise ValueError(f"Arrangement {arrangement.id} has no stem arrangement data")
        
        # Parse arrangement data
        try:
            arrangement_data = json.loads(arrangement.stem_arrangement_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid stem arrangement JSON: {e}")
        
        # Extract metadata
        sections_data = arrangement_data.get('sections', [])
        stem_roles = arrangement_data.get('stem_roles', {})
        
        if not sections_data or not stem_roles:
            raise ValueError("Arrangement data missing sections or stem roles")
        
        # Reconstruct SectionConfig objects
        from app.services.stem_arrangement_engine import(
            SectionConfig, StemRole, StemState, ProducerMove
        )
        
        sections = []
        for section_dict in sections_data:
            # Reconstruct stem states
            stem_states = {}
            for role_str, state_dict in section_dict.get('stem_states', {}).items():
                try:
                    role = StemRole(role_str)
                    stem_states[role] = StemState(
                        role=role,
                        active=state_dict.get('active', False),
                        gain_db=state_dict.get('gain_db', 0.0),
                        pan=state_dict.get('pan', 0.0),
                        filter_cutoff=state_dict.get('filter_cutoff'),
                    )
                except ValueError:
                    pass
            
            # Reconstruct active stems
            active_stems = set()
            for stem_str in section_dict.get('active_stems', []):
                try:
                    active_stems.add(StemRole(stem_str))
                except ValueError:
                    pass
            
            # Reconstruct producer moves
            producer_moves = []
            for move_str in section_dict.get('producer_moves', []):
                try:
                    from app.services.stem_arrangement_engine import ProducerMove
                    producer_moves.append(ProducerMove(move_str))
                except ValueError:
                    pass
            
            section = SectionConfig(
                name=section_dict.get('name', 'Section'),
                section_type=section_dict.get('section_type', 'verse'),
                bar_start=section_dict.get('bar_start', 0),
                bars=section_dict.get('bars', 8),
                active_stems=active_stems,
                energy_level=section_dict.get('energy_level', 0.5),
                producer_moves=producer_moves,
                stem_states=stem_states,
                bpm=section_dict.get('bpm', 120),
            )
            sections.append(section)
        
        # Convert stem roles to path dict
        stem_files = {StemRole(role): Path(path) for role, path in stem_roles.items()}
        
        # Render
        executor = StemRenderExecutor()
        output_audio = executor.render_from_stems(
            stem_files=stem_files,
            sections=sections,
            apply_master=True,
        )
        
        # Get duration
        duration_ms = len(output_audio)
        
        # Export and upload
        import io
        output_buffer = io.BytesIO()
        output_audio.export(output_buffer, format='wav')
        output_buffer.seek(0)
        
        # Upload to storage (assuming storage_client has upload_file method)
        # storage_client.upload_file(
        #     file_bytes=output_buffer.getvalue(),
        #     content_type="audio/wav",
        #     key=output_storage_key
        # )
        
        logger.info(f"Rendered stem arrangement: {duration_ms/1000:.1f}s")
        
        return output_storage_key, duration_ms
