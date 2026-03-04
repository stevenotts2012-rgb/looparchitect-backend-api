"""Style validation service for PHASE 3 sliders and parameters."""

import logging
from typing import Tuple, List

from app.schemas.style_profile import StyleProfile as ComplexStyleProfile

logger = logging.getLogger(__name__)


class StyleValidationService:
    """Validate and normalize style profiles from UI input."""

    def __init__(self):
        """Initialize the validation service."""
        pass

    def validate_and_normalize(
        self, profile_dict: dict
    ) -> Tuple[dict, List[str]]:
        """Validate style profile and return normalized version with warnings.
        
        Args:
            profile_dict: Dictionary representation of style profile from UI
            
        Returns:
            Tuple of (normalized_profile_dict, warnings_list)
            
        Raises:
            ValueError: If profile is invalid
        """
        warnings: List[str] = []

        # Validate intent is present and non-empty
        intent = profile_dict.get("intent", "").strip()
        if not intent:
            raise ValueError("intent is required and cannot be empty")
        if len(intent) > 500:
            raise ValueError("intent cannot exceed 500 characters")

        # Normalize sliders (0-1 range)
        energy = float(profile_dict.get("energy", 0.5))
        darkness = float(profile_dict.get("darkness", 0.5))
        bounce = float(profile_dict.get("bounce", 0.5))
        warmth = float(profile_dict.get("warmth", 0.5))

        if not (0 <= energy <= 1):
            raise ValueError("energy must be between 0 and 1")
        if not (0 <= darkness <= 1):
            raise ValueError("darkness must be between 0 and 1")
        if not (0 <= bounce <= 1):
            raise ValueError("bounce must be between 0 and 1")
        if not (0 <= warmth <= 1):
            raise ValueError("warmth must be between 0 and 1")

        # Validate texture
        texture = profile_dict.get("texture", "balanced").lower()
        if texture not in ["smooth", "balanced", "gritty"]:
            raise ValueError("texture must be one of: smooth, balanced, gritty")

        # Validate references and avoid lists
        references = profile_dict.get("references", [])
        if not isinstance(references, list):
            raise ValueError("references must be a list")
        if len(references) > 10:
            warnings.append(
                "More than 10 references may slow down parsing (truncating to 10)"
            )
            references = references[:10]

        avoid = profile_dict.get("avoid", [])
        if not isinstance(avoid, list):
            raise ValueError("avoid must be a list")
        if len(avoid) > 10:
            warnings.append(
                "More than 10 avoid items may affect generation (truncating to 10)"
            )
            avoid = avoid[:10]

        # Validate seed
        seed = int(profile_dict.get("seed", 42))
        if seed < 0:
            warnings.append("Seed should be positive; using absolute value")
            seed = abs(seed)

        # Validate confidence
        confidence = float(profile_dict.get("confidence", 0.8))
        if not (0 <= confidence <= 1):
            warnings.append("Confidence adjusted to valid range (0-1)")
            confidence = max(0, min(1, confidence))

        # Build normalized profile
        normalized = {
            "intent": intent,
            "energy": round(energy, 2),
            "darkness": round(darkness, 2),
            "bounce": round(bounce, 2),
            "warmth": round(warmth, 2),
            "texture": texture,
            "references": references,
            "avoid": avoid,
            "seed": seed,
            "confidence": round(confidence, 2),
        }

        logger.info(
            f"Style profile validated: intent='{intent[:50]}...', "
            f"energy={energy:.2f}, darkness={darkness:.2f}, "
            f"bounce={bounce:.2f}, warmth={warmth:.2f}"
        )

        return normalized, warnings


# Singleton instance
style_validation_service = StyleValidationService()
