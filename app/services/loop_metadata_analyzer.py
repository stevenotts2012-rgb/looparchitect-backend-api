"""Loop Metadata Analyzer: Rule-based genre, mood, and energy detection from loop metadata.

This service analyzes loop metadata (BPM, tags, filename, keywords) to automatically
detect genre, mood, energy level, and provide arrangement recommendations. No audio
file processing required - works purely with metadata.

Distinct from LoopAnalyzer which processes audio files - this analyzer works with
metadata only for fast genre/mood detection.

Supports:
- Genres: trap, dark_trap, melodic_trap, drill, rage, generic
- Moods: dark, aggressive, emotional, cinematic, energetic, neutral
- Energy: 0.0-1.0 scale
- Templates: standard, progressive, looped, minimal
- Instruments: contextual recommendations based on genre/mood
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Set, Any

logger = logging.getLogger(__name__)


class LoopMetadataAnalyzer:
    """Rule-based analyzer for loop genre, mood, and arrangement recommendations."""
    
    # Analysis algorithm version
    VERSION = "1.0.0"
    
    # =================================================================
    # GENRE DETECTION RULES
    # =================================================================
    
    # BPM ranges for different genres
    BPM_RANGES = {
        "trap": (130, 160),
        "dark_trap": (130, 160),
        "melodic_trap": (120, 155),
        "drill": (135, 150),
        "rage": (140, 170),
    }
    
    # Keywords that strongly indicate specific genres
    GENRE_KEYWORDS = {
        "trap": ["trap", "hi-hat", "808", "triplet", "metro"],
        "dark_trap": ["dark", "trap", "sinister", "evil", "devil", "night"],
        "melodic_trap": ["melodic", "piano", "emotional", "melody", "sad", "ambient"],
        "drill": ["drill", "uk drill", "chicago", "sliding", "slide"],
        "rage": ["rage", "hyper", "distorted", "yeat", "synth", "glitch"],
    }
    
    # Filename patterns (regex)
    FILENAME_PATTERNS = {
        "dark_trap": r'\b(dark|evil|sinister|devil)\b.*\btrap\b|\btrap\b.*\b(dark|evil)',
        "melodic_trap": r'\b(melodic|melody|emotional|piano|sad)\b.*\btrap\b',
        "drill": r'\b(drill|uk.?drill|chicago)\b',
        "rage": r'\b(rage|hyper|yeat|glitch)\b',
        "trap": r'\b(trap|metro|future|808)\b',
    }
    
    # =================================================================
    # MOOD DETECTION RULES
    # =================================================================
    
    MOOD_KEYWORDS = {
        "dark": ["dark", "sinister", "evil", "devil", "shadow", "night", "gloomy"],
        "aggressive": ["aggressive", "hard", "angry", "intense", "violent", "raw"],
        "emotional": ["emotional", "sad", "melancholy", "heartbreak", "pain", "feelings"],
        "cinematic": ["cinematic", "orchestral", "epic", "dramatic", "score", "soundtrack"],
        "energetic": ["energetic", "hype", "upbeat", "party", "club", "bounce"],
    }
    
    # =================================================================
    # INSTRUMENT RECOMMENDATIONS
    # =================================================================
    
    GENRE_INSTRUMENTS = {
        "trap": ["kick", "snare", "hats", "808_bass", "hi-hat_roll", "fx"],
        "dark_trap": ["kick", "snare", "hats", "808_bass", "dark_pad", "fx", "reverse_cymbal"],
        "melodic_trap": ["kick", "snare", "hats", "808_bass", "piano", "pad", "strings", "melody"],
        "drill": ["kick", "snare", "hats", "sliding_808", "percussion", "fx"],
        "rage": ["kick", "snare", "hats", "distorted_bass", "synth", "glitch_fx", "vocal_chop"],
        "generic": ["kick", "snare", "hats", "bass", "pad"],
    }
    
    # =================================================================
    # TEMPLATE RECOMMENDATIONS
    # =================================================================
    
    GENRE_TEMPLATES = {
        "trap": "standard",
        "dark_trap": "progressive",
        "melodic_trap": "progressive",
        "drill": "looped",
        "rage": "standard",
        "generic": "standard",
    }
    
    # =================================================================
    # CORE ANALYSIS METHODS
    # =================================================================
    
    @classmethod
    def analyze(
        cls,
        bpm: Optional[float] = None,
        tags: Optional[List[str]] = None,
        filename: Optional[str] = None,
        mood_keywords: Optional[List[str]] = None,
        genre_hint: Optional[str] = None,
        bars: Optional[int] = None,
        musical_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Main analysis method - detects genre, mood, energy, and provides recommendations.
        
        Args:
            bpm: Beats per minute (60-200)
            tags: User-provided tags
            filename: Original filename
            mood_keywords: Explicit mood descriptors
            genre_hint: User's genre preference
            bars: Number of bars in the loop
            musical_key: Musical key
            
        Returns:
            Dictionary containing:
            - detected_genre: str
            - detected_mood: str
            - energy_level: float (0.0-1.0)
            - recommended_template: str
            - confidence: float (0.0-1.0)
            - suggested_instruments: List[str]
            - analysis_version: str
            - source_signals: Dict[str, Any]
            - reasoning: str
        """
        logger.info(f"Starting loop metadata analysis: bpm={bpm}, tags={tags}, filename={filename}")
        
        # Normalize inputs
        tags = [t.lower() for t in (tags or [])]
        filename_lower = (filename or "").lower()
        mood_keywords = [m.lower() for m in (mood_keywords or [])]
        genre_hint_lower = (genre_hint or "").lower() if genre_hint else None
        
        # Collect all signals for analysis
        signals: Dict[str, Any] = {
            "bpm_provided": bpm is not None,
            "bpm_value": bpm,
            "tag_count": len(tags),
            "tags": tags,
            "has_filename": bool(filename),
            "filename": filename,
            "mood_keywords": mood_keywords,
            "genre_hint": genre_hint,
        }
        
        # Step 1: Detect Genre
        detected_genre, genre_confidence, genre_signals = cls._detect_genre(
            bpm=bpm,
            tags=tags,
            filename=filename_lower,
            genre_hint=genre_hint_lower
        )
        signals.update(genre_signals)
        
        # Step 2: Detect Mood
        detected_mood, mood_confidence, mood_signals = cls._detect_mood(
            tags=tags,
            filename=filename_lower,
            mood_keywords=mood_keywords,
            detected_genre=detected_genre
        )
        signals.update(mood_signals)
        
        # Step 3: Calculate Energy Level
        energy_level = cls._calculate_energy(
            bpm=bpm,
            detected_genre=detected_genre,
            detected_mood=detected_mood
        )
        signals["energy_level"] = energy_level
        
        # Step 4: Recommend Template
        recommended_template = cls.GENRE_TEMPLATES.get(detected_genre, "standard")
        
        # Step 5: Suggest Instruments
        suggested_instruments = cls.GENRE_INSTRUMENTS.get(detected_genre, cls.GENRE_INSTRUMENTS["generic"])
        
        # Step 6: Calculate Overall Confidence
        overall_confidence = (genre_confidence + mood_confidence) / 2.0
        
        # Step 7: Generate Reasoning
        reasoning = cls._generate_reasoning(
            detected_genre=detected_genre,
            detected_mood=detected_mood,
            bpm=bpm,
            tags=tags,
            mood_keywords=mood_keywords,
            filename=filename,
            genre_hint=genre_hint
        )
        
        result = {
            "detected_genre": detected_genre,
            "detected_mood": detected_mood,
            "energy_level": round(energy_level, 2),
            "recommended_template": recommended_template,
            "confidence": round(overall_confidence, 2),
            "suggested_instruments": suggested_instruments,
            "analysis_version": cls.VERSION,
            "source_signals": signals,
            "reasoning": reasoning,
        }
        
        logger.info(
            f"Metadata analysis complete: genre={detected_genre}, mood={detected_mood}, "
            f"energy={energy_level:.2f}, confidence={overall_confidence:.2f}"
        )
        
        return result
    
    # =================================================================
    # GENRE DETECTION
    # =================================================================
    
    @classmethod
    def _detect_genre(
        cls,
        bpm: Optional[float],
        tags: List[str],
        filename: str,
        genre_hint: Optional[str]
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Detect genre using BPM, tags, filename patterns, and hints.
        
        Returns:
            (detected_genre, confidence, signals_dict)
        """
        signals = {
            "genre_bpm_match": False,
            "genre_tag_matches": [],
            "genre_filename_match": None,
            "genre_hint_used": False,
        }
        
        # Priority 1: Explicit genre hint
        if genre_hint:
            normalized_hint = cls._normalize_genre(genre_hint)
            if normalized_hint in cls.GENRE_KEYWORDS:
                signals["genre_hint_used"] = True
                return normalized_hint, 0.95, signals
        
        # Build genre scores
        genre_scores: Dict[str, float] = {}
        
        # Check each genre
        for genre in ["dark_trap", "melodic_trap", "drill", "rage", "trap"]:
            score = 0.0
            
            # BPM match (30 points)
            if bpm and cls._bpm_matches_genre(bpm, genre):
                score += 30.0
                signals["genre_bpm_match"] = True
            
            # Tag matches (10 points each, max 40)
            tag_matches = [tag for tag in tags if tag in cls.GENRE_KEYWORDS[genre]]
            score += min(len(tag_matches) * 10.0, 40.0)
            if tag_matches:
                signals["genre_tag_matches"].extend(tag_matches)
            
            # Filename pattern match (30 points)
            if genre in cls.FILENAME_PATTERNS:
                if re.search(cls.FILENAME_PATTERNS[genre], filename):
                    score += 30.0
                    signals["genre_filename_match"] = genre
            
            genre_scores[genre] = score
        
        # Select best genre
        if genre_scores:
            best_genre = max(genre_scores, key=genre_scores.get)
            best_score = genre_scores[best_genre]
            
            if best_score >= 30.0:  # Minimum threshold
                confidence = min(best_score / 100.0, 1.0)
                return best_genre, confidence, signals
        
        # Fallback: generic trap
        logger.warning("No strong genre match - falling back to 'trap'")
        return "trap", 0.4, signals
    
    @classmethod
    def _bpm_matches_genre(cls, bpm: float, genre: str) -> bool:
        """Check if BPM falls within genre's typical range."""
        if genre not in cls.BPM_RANGES:
            return False
        min_bpm, max_bpm = cls.BPM_RANGES[genre]
        return min_bpm <= bpm <= max_bpm
    
    @classmethod
    def _normalize_genre(cls, genre: str) -> str:
        """Normalize genre string to canonical form."""
        genre_map = {
            "dark": "dark_trap",
            "melodic": "melodic_trap",
            "uk drill": "drill",
            "chicago drill": "drill",
        }
        return genre_map.get(genre, genre)
    
    # =================================================================
    # MOOD DETECTION
    # =================================================================
    
    @classmethod
    def _detect_mood(
        cls,
        tags: List[str],
        filename: str,
        mood_keywords: List[str],
        detected_genre: str
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Detect mood from keywords, tags, filename, and genre.
        
        Returns:
            (detected_mood, confidence, signals_dict)
        """
        signals = {
            "mood_keyword_matches": [],
            "mood_tag_matches": [],
            "mood_filename_hints": [],
        }
        
        mood_scores: Dict[str, float] = {}
        
        # Check each mood
        for mood, keywords in cls.MOOD_KEYWORDS.items():
            score = 0.0
            
            # Direct mood keyword matches (25 points each)
            keyword_matches = [kw for kw in mood_keywords if kw in keywords]
            score += len(keyword_matches) * 25.0
            if keyword_matches:
                signals["mood_keyword_matches"].extend(keyword_matches)
            
            # Tag matches (15 points each)
            tag_matches = [tag for tag in tags if tag in keywords]
            score += len(tag_matches) * 15.0
            if tag_matches:
                signals["mood_tag_matches"].extend(tag_matches)
            
            # Filename hints (10 points each)
            filename_matches = [kw for kw in keywords if kw in filename]
            score += len(filename_matches) * 10.0
            if filename_matches:
                signals["mood_filename_hints"].extend(filename_matches)
            
            mood_scores[mood] = score
        
        # Genre-mood associations (boost certain moods for certain genres)
        genre_mood_boost = {
            "dark_trap": {"dark": 20.0, "aggressive": 10.0},
            "melodic_trap": {"emotional": 20.0, "cinematic": 10.0},
            "drill": {"aggressive": 20.0, "dark": 10.0},
            "rage": {"aggressive": 20.0, "energetic": 15.0},
        }
        
        if detected_genre in genre_mood_boost:
            for mood, boost in genre_mood_boost[detected_genre].items():
                mood_scores[mood] = mood_scores.get(mood, 0.0) + boost
        
        # Select best mood
        if mood_scores:
            best_mood = max(mood_scores, key=mood_scores.get)
            best_score = mood_scores[best_mood]
            
            if best_score >= 15.0:  # Minimum threshold
                confidence = min(best_score / 100.0, 1.0)
                return best_mood, confidence, signals
        
        # Fallback: neutral
        logger.warning("No strong mood match - falling back to 'dark'")
        return "dark", 0.3, signals
    
    # =================================================================
    # ENERGY CALCULATION
    # =================================================================
    
    @classmethod
    def _calculate_energy(
        cls,
        bpm: Optional[float],
        detected_genre: str,
        detected_mood: str
    ) -> float:
        """Calculate energy level (0.0-1.0) based on BPM, genre, and mood.
        
        Returns:
            Energy level between 0.0 (calm) and 1.0 (intense)
        """
        # Base energy from BPM
        if bpm:
            # Normalize BPM to 0.0-1.0 range (60 BPM = 0.0, 180 BPM = 1.0)
            bpm_energy = min(max((bpm - 60.0) / 120.0, 0.0), 1.0)
        else:
            bpm_energy = 0.5  # Default mid-range
        
        # Genre modifiers
        genre_modifiers = {
            "rage": 0.15,
            "drill": 0.10,
            "dark_trap": 0.05,
            "trap": 0.0,
            "melodic_trap": -0.10,
        }
        genre_mod = genre_modifiers.get(detected_genre, 0.0)
        
        # Mood modifiers
        mood_modifiers = {
            "energetic": 0.15,
            "aggressive": 0.10,
            "dark": 0.05,
            "cinematic": 0.0,
            "emotional": -0.10,
        }
        mood_mod = mood_modifiers.get(detected_mood, 0.0)
        
        # Calculate final energy
        energy = bpm_energy + genre_mod + mood_mod
        energy = min(max(energy, 0.0), 1.0)  # Clamp to 0.0-1.0
        
        return energy
    
    # =================================================================
    # REASONING GENERATION
    # =================================================================
    
    @classmethod
    def _generate_reasoning(
        cls,
        detected_genre: str,
        detected_mood: str,
        bpm: Optional[float],
        tags: List[str],
        mood_keywords: List[str],
        filename: Optional[str],
        genre_hint: Optional[str]
    ) -> str:
        """Generate human-readable explanation of the analysis."""
        parts = []
        
        # Genre reasoning
        parts.append(f"Detected {detected_genre} based on:")
        
        if genre_hint:
            parts.append(f"  - User provided genre hint: '{genre_hint}'")
        
        if bpm:
            bpm_range = cls.BPM_RANGES.get(detected_genre)
            if bpm_range:
                parts.append(f"  - BPM {bpm:.0f} in {detected_genre} range ({bpm_range[0]}-{bpm_range[1]})")
        
        genre_tags = [t for t in tags if t in cls.GENRE_KEYWORDS.get(detected_genre, [])]
        if genre_tags:
            parts.append(f"  - Genre tags: {', '.join(genre_tags)}")
        
        if filename:
            parts.append(f"  - Filename hints: '{filename}'")
        
        # Mood reasoning
        parts.append(f"Detected {detected_mood} mood from:")
        
        if mood_keywords:
            parts.append(f"  - Mood keywords: {', '.join(mood_keywords)}")
        
        mood_tags = [t for t in tags if any(t in keywords for keywords in cls.MOOD_KEYWORDS.values())]
        if mood_tags:
            parts.append(f"  - Mood-related tags: {', '.join(mood_tags)}")
        
        return "\n".join(parts)
