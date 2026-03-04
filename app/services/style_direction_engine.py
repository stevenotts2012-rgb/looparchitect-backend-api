"""
Style Direction Engine: Maps user input to structured StyleProfile.

Handles natural language input like:
- "Southside type"
- "Lil Baby vibe"
- "Drake R&B"
- "Detroit Drill"
- "Afrobeats"
- "Cinematic Hans Zimmer"

Returns StyleProfile that influences:
- BPM range
- Genre classification
- Energy level
- Drum style
- Melody style
- Bass style
- Structure template
"""

import logging
import re
from typing import Dict, Tuple
from app.services.producer_models import StyleProfile

logger = logging.getLogger(__name__)


class StyleDirectionEngine:
    """Maps user style input to structured StyleProfile."""
    
    # Keyword mappings for genre detection
    GENRE_KEYWORDS = {
        "trap": {"trap", "atl", "southside", "hi-hats", "hi hat", "808"},
        "rnb": {
            "r&b", "rnb", "soul", "neo soul", "melodic", "drake", "usher",
            "bryson tiller", "h.e.r", "khalid"
        },
        "pop": {
            "pop", "radio", "mainstream", "upbeat", "catchy", "dua lipa",
            "ariana", "post malone"
        },
        "cinematic": {
            "cinematic", "film", "score", "hans zimmer", "orchestral",
            "dark", "epic", "dramatic", "cinematic", "movie"
        },
        "afrobeats": {
            "afrobeats", "afrobeat", "amapiano", "wizkid", "burna boy",
            "rema", "davido", "afro", "nigerian", "ghana"
        },
        "drill": {
            "drill", "detroit", "chicago", "london drill", "dark", "aggressive",
            "hard", "street", "violent"
        },
        "house": {
            "house", "electronic", "dance", "edm", "dj", "techno", "deep house",
            "progressive house", "tech house"
        },
        "jazz": {
            "jazz", "smooth", "laid back", "chill", "lofi", "lo-fi", "atmospheric"
        },
    }
    
    # Artist mappings
    ARTIST_KEYWORDS = {
        "lil baby": ("trap", 0.7, "electronic"),
        "drake": ("rnb", 0.65, "melodic"),
        "usher": ("rnb", 0.6, "melodic"),
        "post malone": ("pop", 0.7, "melodic"),
        "dark sky": ("cinematic", 0.8, "orchestral"),
        "hans zimmer": ("cinematic", 0.9, "orchestral"),
        "wizkid": ("afrobeats", 0.75, "percussive"),
        "burna boy": ("afrobeats", 0.8, "percussive"),
        "daft punk": ("house", 0.75, "electronic"),
    }
    
    # Reference-based mood mappings
    MOOD_KEYWORDS = {
        "aggressive": {"aggressive", "hard", "intense", "heavy"},
        "energetic": {"energetic", "upbeat", "high energy", "exciting", "fun"},
        "chill": {"chill", "laid back", "relaxed", "smooth", "mellow"},
        "dark": {"dark", "gritty", "moody", "mysterious", "ominous"},
        "bright": {"bright", "uplifting", "positive", "euphoric", "happy"},
    }

    @staticmethod
    def parse(style_input: str) -> StyleProfile:
        """
        Parse user style input and return a StyleProfile.
        
        Args:
            style_input: Natural language style description
        
        Returns:
            StyleProfile with structured attributes
        """
        if not style_input or not isinstance(style_input, str):
            return StyleDirectionEngine._default_profile()
        
        style_input_lower = style_input.lower().strip()
        
        # Detect genre
        detected_genre = StyleDirectionEngine._detect_genre(style_input_lower)
        
        # Detect artist references
        detected_artist = StyleDirectionEngine._detect_artist(style_input_lower)
        
        # Detect mood/energy
        detected_mood = StyleDirectionEngine._detect_mood(style_input_lower)
        
        # Detect specific characteristics
        drum_style = StyleDirectionEngine._detect_drum_style(style_input_lower, detected_genre)
        melody_style = StyleDirectionEngine._detect_melody_style(style_input_lower, detected_genre)
        bass_style = StyleDirectionEngine._detect_bass_style(style_input_lower, detected_genre)
        
        # Map to BPM range
        bpm_range = StyleDirectionEngine._bpm_for_genre(detected_genre)
        
        # Determine energy (0.0 to 1.0)
        energy = StyleDirectionEngine._energy_for_mood(detected_mood)
        
        # Template selection
        structure_template = StyleDirectionEngine._structure_template(detected_genre)
        
        # Build description
        description_parts = []
        if detected_artist:
            description_parts.append(f"{detected_artist} vibes")
        if detected_mood and detected_mood != "neutral":
            description_parts.append(detected_mood)
        description_parts.append(f"{detected_genre} style")
        
        profile = StyleProfile(
            genre=detected_genre,
            bpm_range=bpm_range,
            energy=energy,
            drum_style=drum_style,
            melody_style=melody_style,
            bass_style=bass_style,
            structure_template=structure_template,
            description=" | ".join(description_parts),
            references=[ref for ref in [detected_artist] if ref],
        )
        
        logger.info(f"Parsed style input '{style_input}' -> {detected_genre} @{bpm_range[0]}-{bpm_range[1]}BPM")
        
        return profile

    @staticmethod
    def _detect_genre(text: str) -> str:
        """Detect genre from keyword analysis."""
        text_words = set(text.split())
        
        genre_scores = {}
        
        for genre, keywords in StyleDirectionEngine.GENRE_KEYWORDS.items():
            matches = len(text_words & keywords)
            if matches > 0:
                genre_scores[genre] = matches
        
        if not genre_scores:
            return "generic"
        
        return max(genre_scores, key=genre_scores.get)

    @staticmethod
    def _detect_artist(text: str) -> str:
        """Detect artist reference from keyword matching."""
        text_lower = text.lower()
        
        for artist in StyleDirectionEngine.ARTIST_KEYWORDS.keys():
            if artist in text_lower:
                return artist
        
        return ""

    @staticmethod
    def _detect_mood(text: str) -> str:
        """Detect mood from keywords."""
        text_words = set(text.split())
        
        for mood, keywords in StyleDirectionEngine.MOOD_KEYWORDS.items():
            if text_words & keywords:
                return mood
        
        return "neutral"

    @staticmethod
    def _detect_drum_style(text: str, genre: str) -> str:
        """Detect drum style based on keywords and genre."""
        defaults = {
            "trap": "programmed",
            "rnb": "programmed",
            "pop": "live",
            "cinematic": "orchestral",
            "afrobeats": "percussive",
            "drill": "programmed",
            "house": "electronic",
            "jazz": "live",
        }
        
        if "live" in text.lower():
            return "live"
        elif "acoustic" in text.lower():
            return "acoustic"
        elif "electronic" in text.lower() or "synth" in text.lower():
            return "electronic"
        elif "orchestral" in text.lower():
            return "orchestral"
        
        return defaults.get(genre, "programmed")

    @staticmethod
    def _detect_melody_style(text: str, genre: str) -> str:
        """Detect melody style based on keywords and genre."""
        defaults = {
            "rap": "rhythmic",
            "rnb": "melodic",
            "pop": "melodic",
            "cinematic": "orchestral",
            "afrobeats": "rhythmic",
            "drill": "minimalist",
            "house": "rhythmic",
            "jazz": "improvisational",
        }
        
        if "minimalist" in text.lower():
            return "minimalist"
        elif "orchestral" in text.lower():
            return "orchestral"
        elif "melodic" in text.lower() or "vocal" in text.lower():
            return "melodic"
        elif "rhythmic" in text.lower():
            return "rhythmic"
        
        return defaults.get(genre, "melodic")

    @staticmethod
    def _detect_bass_style(text: str, genre: str) -> str:
        """Detect bass style based on keywords and genre."""
        defaults = {
            "trap": "sub",
            "rnb": "synth",
            "pop": "synth",
            "cinematic": "orchestral",
            "afrobeats": "electric",
            "drill": "sub",
            "house": "synth",
            "jazz": "acoustic",
        }
        
        if "808" in text.lower():
            return "sub"
        elif "synth" in text.lower():
            return "synth"
        elif "electric" in text.lower():
            return "electric"
        elif "acoustic" in text.lower():
            return "acoustic"
        elif "orchestral" in text.lower():
            return "orchestral"
        
        return defaults.get(genre, "synth")

    @staticmethod
    def _bpm_for_genre(genre: str) -> Tuple[int, int]:
        """Return BPM range for genre."""
        ranges = {
            "trap": (85, 115),
            "rnb": (80, 105),
            "pop": (95, 130),
            "cinematic": (60, 100),
            "afrobeats": (95, 130),
            "drill": (130, 160),
            "house": (120, 130),
            "jazz": (80, 120),
        }
        return ranges.get(genre, (90, 140))

    @staticmethod
    def _energy_for_mood(mood: str) -> float:
        """Return energy level (0.0-1.0) for mood."""
        moods = {
            "aggressive": 0.9,
            "energetic": 0.85,
            "chill": 0.4,
            "dark": 0.6,
            "bright": 0.8,
            "neutral": 0.5,
        }
        return moods.get(mood, 0.5)

    @staticmethod
    def _structure_template(genre: str) -> str:
        """Select structure template for genre."""
        templates = {
            "trap": "standard",
            "rnb": "progressive",
            "pop": "standard",
            "cinematic": "progressive",
            "afrobeats": "looped",
            "drill": "minimal",
            "house": "looped",
            "jazz": "progressive",
        }
        return templates.get(genre, "standard")

    @staticmethod
    def _default_profile() -> StyleProfile:
        """Return default neutral StyleProfile."""
        return StyleProfile(
            genre="generic",
            bpm_range=(90, 140),
            energy=0.5,
            drum_style="programmed",
            melody_style="melodic",
            bass_style="synth",
            structure_template="standard",
            description="Default generic style",
        )
