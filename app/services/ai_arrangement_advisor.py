"""AI Arrangement Advisor Service.

Provides LLM-based recommendations to ProducerEngine while maintaining 
deterministic control. Recommends (never overrides) structure changes 
with rule-based validation + fallback.

Flow:
1. ProducerEngine generates baseline deterministic arrangement
2. AI Advisor recommends optimizations (structure, energy, genre)  
3. ProducerEngine validates recommendation against rules
4. Accept valid rec → apply selectively
5. Reject invalid → deterministic fallback (guaranteed)
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Tuple, List
from pydantic import BaseModel, Field, validator

from app.config import settings
from app.services.producer_engine import ProducerEngine
from app.services.producer_models import ProducerArrangement, SectionType

logger = logging.getLogger(__name__)

class AdvisorRecommendation(BaseModel):
    """Structured AI recommendation schema."""
    suggested_genre: Optional[str] = Field(None, description=\"Genre suggestion\")
    suggested_template: Optional[str] = Field(None, description=\"Structure template: standard|progressive|looped|minimal\")
    energy_multiplier: float = Field(1.0, ge=0.8, le=1.2, description=\"Global energy scalar\")
    section_changes: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description=\"Per-section modifications\")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., max_length=200)

class AIArrangementAdvisor:
    """AI advisor integration layer for ProducerEngine."""
    
    def __init__(self):
        self.client = None
        if settings.openai_api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=getattr(settings, 'openai_base_url', None),
                )
            except ImportError:
                logger.warning(\"openai not installed - AI advisor disabled\")
    
    async def advise(self, 
                     target_seconds: float, 
                     tempo: float, 
                     genre: str, 
                     style_profile: Optional[Dict] = None) -> Tuple[Optional[AdvisorRecommendation], Dict]:
        """Get validated AI recommendation."""
        metadata = {\"used_ai\": False, \"accepted\": False, \"reason\": \"not_used\"}
        
        if not self.client:
            logger.info(\"OpenAI unavailable - skipping advisor\")
            return None, metadata
        
        try:
            rec_raw = await self._call_llm(target_seconds, tempo, genre, style_profile)
            rec = AdvisorRecommendation.model_validate(rec_raw)
            
            metadata[\"used_ai\"] = True
            metadata[\"recommendation\"] = rec.model_dump()
            
            valid, reason = self._validate_rec(rec, target_seconds, genre)
            metadata[\"accepted\"] = valid
            metadata[\"reason\"] = reason
            
            if valid:
                logger.info(f\"✅ AI advisor accepted (conf={rec.confidence:.2f}): {rec.reasoning[:80]}...\")
            else:
                logger.info(f\"❌ AI advisor rejected: {reason}\")
            
            return rec if valid else None, metadata
            
        except Exception as e:
            logger.warning(f\"AI advisor error: {e}\", exc_info=True)
            metadata[\"reason\"] = f\"error: {str(e)[:50]}\"
            return None, metadata
    
    async def _call_llm(self, target_seconds: float, tempo: float, genre: str, style_profile: Dict) -> Dict:
        """Call LLM for recommendation (strict JSON)."""
        prompt = self._build_prompt(target_seconds, tempo, genre, style_profile)
        
        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=settings.openai_model or \"gpt-4o-mini\",
            messages=[
                {\"role\": \"system\", \"content\": 
                 \"You are a music producer AI. Return ONLY valid JSON matching the schema. \" 
                 \"Conservative recommendations only - prefer safe changes. \" 
                 \"NEVER override ProducerEngine core rules (hooks > verses energy, etc).\"},
                {\"role\": \"user\", \"content\": prompt}
            ],
            temperature=0.2,
            max_tokens=600,
            response_format={\"type\": \"json_object\"}
        )
        
        raw = json.loads(response.choices[0].message.content or \"{}\")
        logger.debug(f\"AI raw rec: {json.dumps(raw, indent=2)[:300]}...\")
        return raw
    
    def _build_prompt(self, target_seconds: float, tempo: float, genre: str, style_profile: Dict) -> str:
        """Build structured LLM prompt."""
        sp_summary = json.dumps(style_profile or {}, indent=2)[:400] if style_profile else \"none\"
        
        return f\"\"\"Recommend arrangement optimizations for ProducerEngine baseline:

PARAMETERS:
- Duration: {target_seconds}s ({int(target_seconds/60)}min)
- Tempo: {tempo} BPM  
- Genre: {genre}
- Style profile: {{sp_summary}}

SCHEMA (JSON only):
```json
{{
  \"suggested_genre\": \"trap\", 
  \"suggested_template\": \"standard|progressive|looped|minimal\",
  \"energy_multiplier\": 1.05,
  \"section_changes\": {{
    \"verse\": {{\"bars\": 12}},
    \"hook\": {{\"energy_boost\": 0.1}}
  }},
  \"confidence\": 0.87,
  \"reasoning\": \"explanation...\"
}}
```

RULES (NEVER VIOLATE):
1. suggested_genre: only from {{list(ProducerEngine.INSTRUMENT_PRESETS.keys())}}
2. energy_multiplier: 0.8-1.2 only  
3. section_changes.keys(): intro|verse|hook|chorus|bridge|outro only
4. bars changes: 4-16 range only
5. confidence <0.7 → minimal changes only

Conservative: Prefer 'standard' template, small multipliers (<1.1).\"\"\"

    def _validate_rec(self, rec: AdvisorRecommendation, target_seconds: float, genre: str) -> Tuple[bool, str]:
        """Strict rule-based validation."""
        errors = []
        
        # Genre validation
        valid_genres = list(ProducerEngine.INSTRUMENT_PRESETS.keys())
        if rec.suggested_genre and rec.suggested_genre not in valid_genres:
            errors.append(f\"Invalid genre: {rec.suggested_genre}\")
        
        # Template validation  
        if rec.suggested_template and rec.suggested_template not in ProducerEngine.STRUCTURE_TEMPLATES:
            errors.append(f\"Invalid template: {rec.suggested_template}\")
        
        # Energy bounds
        if not 0.8 <= rec.energy_multiplier <= 1.2:
            errors.append(f\"Energy multiplier out of bounds: {rec.energy_multiplier}\")
        
        # Section changes validation
        valid_sections = {t.value.lower() for t in SectionType}
        for section in rec.section_changes:
            if section not in valid_sections:
                errors.append(f\"Invalid section in changes: {section}\")
        
        # Duration feasibility
        est_bars = int((target_seconds / 60 * tempo) / 4)
        if rec.confidence < 0.7 and abs(rec.energy_multiplier - 1.0) > 0.05:
            errors.append(\"Low confidence + non-trivial energy change\")
        
        valid = len(errors) == 0 and rec.confidence >= 0.6
        reason = \"; \".join(errors) if errors else \"valid\"
        return valid, reason

# Global singleton instance
ai_arrangement_advisor = AIArrangementAdvisor()
