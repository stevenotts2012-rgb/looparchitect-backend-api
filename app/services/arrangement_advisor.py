and falls back to deterministic ProducerEngine logic.
"""AI Arrangement Advisor - LLM recommendations with ProducerEngine validation.

Recommends structure modifications for ProducerEngine. Advisor suggestions are 
validated against ProducerEngine rules before acceptance. Rejects invalid suggestions 
and falls back to deterministic ProducerEngine logic.
"""

import logging
import json
import asyncio
from typing import Dict, Any, Optional, Tuple
from dataclasses import asdict

from app.config import settings
from app.services.producer_models import ProducerArrangement, SectionType
from app.services.producer_engine import ProducerEngine

logger = logging.getLogger(__name__)

class AIAdvisorRecommendation(BaseModel):
    """Schema for AI advisor recommendations."""
    suggested_structure: List[str]  # ['intro', 'verse', 'hook', ...]
    suggested_genre: Optional[str] = None
    energy_multiplier: float = 1.0  # 0.8-1.2
    confidence: float  # 0.0-1.0
    reasoning: str

class ArrangementAdvisor:
    """AI advisor layer for ProducerEngine."""
    
    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
    
    async def get_advisor_recommendation(
        self, 
        target_seconds: float,
        base_genre: str,
        style_profile: Optional[Dict] = None
    ) -> Optional[AIAdvisorRecommendation]:
        """Get LLM recommendation for arrangement parameters."""
        if not self.client:
            logger.warning(\"OpenAI client unavailable, skipping advisor\")
            return None
        
        prompt = f\"\"\"Recommend optimal arrangement structure for:
- Duration: {target_seconds}s  
- Genre: {base_genre}
- Style: {style_profile or 'none'}

Output strict JSON only:
{{
  \"suggested_structure\": [\"intro\", \"verse\", \"hook\", ...], 
  \"suggested_genre\": \"trap\",
  \"energy_multiplier\": 1.05,
  \"confidence\": 0.85, 
  \"reasoning\": \"brief reasoning\"
}}

Rules to recommend:
1. 3-8 sections maximum
2. Hooks have highest energy
3. Intro/outro <= 8 bars each  
4. Verse/hook: 8-16 bars
5. Bridge optional, <=12 bars\"\"\"

        try:
            response = await asyncio.to_thread(
                self.client.chat.completions.create,
                model=settings.openai_model,
                messages=[
                    {\"role\": \"system\", \"content\": \"Music producer AI. Strict JSON only.\"},
                    {\"role\": \"user\", \"content\": prompt},
                ],
                temperature=0.3,
                max_tokens=400,
                response_format={\"type\": \"json_object\"},
            )
            
            raw = response.choices[0].message.content.strip()
            rec = json.loads(raw)
            recommendation = AIAdvisorRecommendation(**rec)
            
            logger.info(f\"AI advisor rec: structure={recommendation.suggested_structure}, conf={recommendation.confidence:.2f}\")
            return recommendation
            
        except Exception as e:
            logger.warning(f\"AI advisor failed: {e}\")
            return None
    
    def validate_recommendation(self, rec: AIAdvisorRecommendation, original: ProducerArrangement) -> Tuple[bool, str]:
        \"\"\"Validate AI recommendation against ProducerEngine rules.\"\"\"
        errors = []
        
        # Structure validation
        valid_types = {t.value.lower() for t in SectionType}
        for section in rec.suggested_structure:
            if section not in valid_types:
                errors.append(f\"Invalid section: {section}\")
        
        if len(rec.suggested_structure) < 3 or len(rec.suggested_structure) > 8:
            errors.append(\"Structure must have 3-8 sections\")
        
        # Ensure hooks exist and have reasonable positioning
        hooks = [i for i, s in enumerate(rec.suggested_structure) if 'hook' in s or 'chorus' in s]
        if not hooks:
            errors.append(\"Must include at least one hook/chorus\")
        
        # Energy multiplier bounds
        if not 0.7 <= rec.energy_multiplier <= 1.3:
            errors.append(\"Energy multiplier out of bounds\")
        
        # Genre validation (basic)
        if rec.suggested_genre and rec.suggested_genre not in ProducerEngine.INSTRUMENT_PRESETS:
            logger.debug(f\"Unknown genre {rec.suggested_genre}, using original\")
        
        valid = len(errors) == 0
        reason = \"; \".join(errors) if errors else \"Valid recommendation\"
        return valid, reason
    
    async def enhance_arrangement(
        self,
        target_seconds: float,
        tempo: float,
        genre: str,
        style_profile: Optional[Dict],
        enable_ai: bool = True
    ) -> Tuple[ProducerArrangement, Dict[str, Any]]:
        \"\"\"
        Enhance ProducerArrangement with optional AI advisor.
        
        Returns: (enhanced_arrangement, advisor_metadata)
        advisor_metadata contains:
        - advisor_used: bool
        - recommendation: dict or None  
        - accepted: bool
        - rejection_reason: str or None
        - fallback_used: bool
        \"\"\"
        
        # Generate baseline deterministic arrangement
        arrangement = ProducerEngine.generate(
            target_seconds=target_seconds,
            tempo=tempo,
            genre=genre,
            style_profile=style_profile,
        )
        
        advisor_metadata = {
            \"advisor_used\": False,
            \"recommendation\": None,
            \"accepted\": False,
            \"rejection_reason\": None,
            \"fallback_used\": False,
        }
        
        if not enable_ai:
            logger.info(\"AI advisor disabled via flag\")
            return arrangement, advisor_metadata
        
        # Get AI recommendation
        rec = await self.get_advisor_recommendation(target_seconds, genre, style_profile)
        if not rec:
            logger.info(\"No AI recommendation available (client error/fallback)\")
            return arrangement, advisor_metadata
        
        advisor_metadata[\"advisor_used\"] = True
        advisor_metadata[\"recommendation\"] = rec.model_dump()
        
        # Validate recommendation
        valid, reason = self.validate_recommendation(rec, arrangement)
        advisor_metadata[\"accepted\"] = valid
        advisor_metadata[\"rejection_reason\"] = reason if not valid else None
        
        if not valid:
            logger.info(f\"AI recommendation rejected: {reason}\")
            advisor_metadata[\"fallback_used\"] = True
            return arrangement, advisor_metadata
        
        # Apply accepted recommendation
        logger.info(f\"Applying AI recommendation (conf {rec.confidence:.2f}): {rec.suggested_structure}\")
        
        # Regenerate with AI suggestions
        new_genre = rec.suggested_genre or genre
        ai_arrangement = ProducerEngine.generate(
            target_seconds=target_seconds * rec.energy_multiplier,
            tempo=tempo,
            genre=new_genre,
            style_profile=style_profile,
            structure_template=\"custom\",  # Will map suggested_structure
        )
        
        # TODO: Map rec.suggested_structure to ai_arrangement.sections
        # For now, keep deterministic structure but log recommendation
        
        return ai_arrangement, advisor_metadata

# Global singleton
arrangement_advisor = ArrangementAdvisor()
