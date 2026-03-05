"""
Beat Genome Loader - Load and cache beat genome configurations.

Beat genomes provide genre-specific production rules and presets for
the ProducerEngine to use when generating arrangements.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from functools import lru_cache

logger = logging.getLogger(__name__)


class BeatGenomeLoader:
    """Load and cache beat genomes from JSON configuration files."""
    
    GENOMES_DIR = Path(__file__).parent.parent.parent / "config" / "genomes"
    
    # Cache loaded genomes
    _cache: Dict[str, dict] = {}
    
    @classmethod
    def load(cls, genre: str, mood: Optional[str] = None) -> dict:
        """
        Load a beat genome by genre and optional mood.
        
        Args:
            genre: Genre name (e.g., "trap", "rnb", "edm", "cinematic")
            mood: Optional mood qualifier (e.g., "dark", "bounce", "modern")
        
        Returns:
            Beat genome configuration as dict
        
        Raises:
            FileNotFoundError: If genome file doesn't exist
            json.JSONDecodeError: If genome file is invalid JSON
        
        Examples:
            >>> genome = BeatGenomeLoader.load("trap", "dark")
            >>> genome["energy_curve"][0]["energy"]
            0.2
        """
        
        # Build cache key
        cache_key = f"{genre}_{mood}" if mood else genre
        
        # Check cache first
        if cache_key in cls._cache:
            logger.debug(f"✓ Genome loaded from cache: {cache_key}")
            return cls._cache[cache_key]
        
        # Build filename
        if mood:
            filename = f"{genre}_{mood}.json"
        else:
            filename = f"{genre}.json"
        
        filepath = cls.GENOMES_DIR / filename
        
        if not filepath.exists():
            available = cls.list_available()
            raise FileNotFoundError(
                f"Genome not found: {filename}\n"
                f"Available genomes: {', '.join(available)}"
            )
        
        try:
            with open(filepath) as f:
                genome = json.load(f)
            
            # Cache it
            cls._cache[cache_key] = genome
            
            logger.info(f"✓ Loaded genome: {genome.get('name', filename)}")
            return genome
        
        except json.JSONDecodeError as e:
            logger.error(f"✗ Invalid JSON in {filename}: {e}")
            raise
        
        except Exception as e:
            logger.error(f"✗ Error loading genome {filename}: {e}")
            raise
    
    @classmethod
    def list_available(cls) -> List[str]:
        """
        List all available genome files.
        
        Returns:
            List of genome filenames (without .json extension)
        
        Examples:
            >>> genomes = BeatGenomeLoader.list_available()
            >>> "trap_dark" in genomes
            True
        """
        
        if not cls.GENOMES_DIR.exists():
            logger.warning(f"Genomes directory not found: {cls.GENOMES_DIR}")
            return []
        
        genomes = []
        for filepath in cls.GENOMES_DIR.glob("*.json"):
            genomes.append(filepath.stem)
        
        return sorted(genomes)
    
    @classmethod
    def get_genre_default(cls, genre: str) -> dict:
        """
        Get default genome for a genre (first one found).
        
        Args:
            genre: Genre name
        
        Returns:
            Default genome for genre
        
        Raises:
            FileNotFoundError: If no genome exists for genre
        """
        
        # Try to find any genome matching the genre
        for available in cls.list_available():
            if available.startswith(genre):
                # Extract mood if present
                parts = available.split("_", 1)
                if len(parts) == 2:
                    _, mood = parts
                    return cls.load(genre, mood)
                else:
                    return cls.load(genre)
        
        # Fallback: try genre without mood
        try:
            return cls.load(genre)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"No genome found for genre: {genre}\n"
                f"Available: {', '.join(cls.list_available())}"
            )
    
    @classmethod
    def validate(cls, genome: dict) -> tuple[bool, List[str]]:
        """
        Validate a genome configuration structure.
        
        Args:
            genome: Genome dict to validate
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        
        errors = []
        
        # Check required fields
        required = ["name", "genre", "section_lengths", "energy_curve", "instrument_layers"]
        for field in required:
            if field not in genome:
                errors.append(f"Missing required field: {field}")
        
        # Validate section lengths
        if "section_lengths" in genome:
            for section, bars in genome["section_lengths"].items():
                if not isinstance(bars, int) or bars <= 0:
                    errors.append(f"Invalid section length for {section}: {bars}")
        
        # Validate energy curve
        if "energy_curve" in genome:
            for point in genome["energy_curve"]:
                if "section" not in point or "energy" not in point:
                    errors.append("Energy curve points must have 'section' and 'energy'")
                if not 0.0 <= point.get("energy", -1) <= 1.0:
                    errors.append(f"Energy value out of range: {point.get('energy')}")
        
        # Validate instrument layers
        if "instrument_layers" in genome:
            if not isinstance(genome["instrument_layers"], dict):
                errors.append("instrument_layers must be a dict")
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    @classmethod
    def reload_cache(cls) -> None:
        """Clear the genome cache and reload on next access."""
        cls._cache.clear()
        logger.info("✓ Genome cache cleared")
    
    @classmethod
    def get_cache_stats(cls) -> dict:
        """
        Get cache statistics.
        
        Returns:
            Dict with cache stats
        """
        return {
            "cached_genomes": len(cls._cache),
            "cache_keys": list(cls._cache.keys()),
        }


# Convenience function for backward compatibility
def load_beat_genome(genre: str, mood: Optional[str] = None) -> dict:
    """Load a beat genome (convenience wrapper)."""
    return BeatGenomeLoader.load(genre, mood)
