"""
DAW Export System: Exports arrangement as stem files, MIDI, and metadata.

Creates ZIP with:
/stems
  - kick.wav
  - snare.wav
  - hats.wav
  - bass.wav
  - melody.wav
  - pads.wav
  
/midi
  - drums.mid
  - bass.mid
  - melody.mid

/metadata
  - markers.csv
  - tempo_map.json
  - README.txt
"""

import logging
import json
from typing import Dict, List
from pathlib import Path
from app.services.producer_models import ProducerArrangement, Section

logger = logging.getLogger(__name__)


class DAWExporter:
    """Exports arrangements for use in DAWs (FL Studio, Ableton, Logic, etc.)"""

    SUPPORTED_DAWS = ["FL Studio", "Ableton Live", "Logic Pro", "Studio One", "Pro Tools", "Reaper"]

    @staticmethod
    def generate_export_metadata(
        arrangement: ProducerArrangement,
        arrangement_id: int,
    ) -> Dict:
        """
        Generate metadata for DAW export.
        
        Args:
            arrangement: The ProducerArrangement to export
            arrangement_id: Arrangement ID for naming
        
        Returns:
            Dictionary with export metadata
        """
        metadata = {
            "arrangement_id": arrangement_id,
            "arrangement_name": f"Arrangement_{arrangement_id}",
            "tempo": arrangement.tempo,
            "key": arrangement.key,
            "total_bars": arrangement.total_bars,
            "total_seconds": arrangement.total_seconds,
            "genre": arrangement.genre,
            "supported_daws": DAWExporter.SUPPORTED_DAWS,
            "sections": [],
            "stem_names": DAWExporter._get_stem_names(arrangement),
            "midi_files": DAWExporter._get_midi_files(arrangement),
        }
        
        # Add section markers
        for section in arrangement.sections:
            metadata["sections"].append({
                "name": section.name,
                "type": section.section_type.value,
                "bar_start": section.bar_start,
                "bars": section.bars,
                "energy": section.energy_level,
            })
        
        return metadata

    @staticmethod
    def generate_markers_csv(arrangement: ProducerArrangement) -> str:
        """
        Generate CSV marker data for DAW import.
        
        Format:
        Name,Start (bars),Start (seconds),End (bars),End (seconds),Color
        """
        lines = ["Name,Start (bars),Start (seconds),End (bars),End (seconds),Color"]
        
        # Colors by section type
        color_map = {
            "Intro": "Blue",
            "Verse": "Green",
            "Hook": "Red",
            "Chorus": "Red",
            "Bridge": "Orange",
            "Breakdown": "Yellow",
            "Outro": "Blue",
        }
        
        bar_duration_seconds = (60.0 / arrangement.tempo) * 4.0
        
        for section in arrangement.sections:
            start_seconds = section.bar_start * bar_duration_seconds
            end_bar = section.bar_start + section.bars - 1
            end_seconds = end_bar * bar_duration_seconds
            color = color_map.get(section.name, "Gray")
            
            line = (
                f'"{section.name}",'
                f'{section.bar_start},'
                f'{start_seconds:.2f},'
                f'{end_bar},'
                f'{end_seconds:.2f},'
                f'{color}'
            )
            lines.append(line)
        
        return "\n".join(lines)

    @staticmethod
    def generate_tempo_map_json(
        arrangement: ProducerArrangement,
    ) -> str:
        """
        Generate tempo map (constant tempo for now, extensible to tempo changes).
        
        Returns:
            JSON string with tempo data
        """
        tempo_map = {
            "constant_tempo": True,
            "bpm": arrangement.tempo,
            "time_signature": "4/4",
            "total_bars": arrangement.total_bars,
            "changes": [  # Empty for now - could support dynamic tempos
                {
                    "bar": 1,
                    "bpm": arrangement.tempo,
                    "time_signature": "4/4",
                }
            ],
        }
        
        return json.dumps(tempo_map, indent=2)

    @staticmethod
    def generate_readme(
        arrangement: ProducerArrangement,
        arrangement_id: int,
    ) -> str:
        """Generate README for DAW export."""
        readme = f"""# LoopArchitect Arrangement Export

## Arrangement ID: {arrangement_id}

### Basic Info
- **Tempo:** {arrangement.tempo} BPM
- **Key:** {arrangement.key}
- **Duration:** {arrangement.total_bars} bars (~{arrangement.total_seconds:.1f} seconds)
- **Genre:** {arrangement.genre}

### Structure
"""
        
        for i, section in enumerate(arrangement.sections, 1):
            readme += f"{i}. {section.name}: bars {section.bar_start}-{section.bar_start + section.bars - 1} (energy: {section.energy_level:.0%})\n"
        
        readme += f"""
### Files Included

#### /stems (Audio tracks)
- kick.wav - Kick drum
- snare.wav - Snare/snares
- hats.wav - Hi-hats and cymbals
- bass.wav - Bass line
- melody.wav - Melody/lead
- pads.wav - Pads and atmospheric elements

#### /midi (MIDI data)
- drums.mid - Drum pattern (kick, snare, hats)
- bass.mid - Bass line and bass notes
- melody.mid - Melody and lead notes

#### /metadata
- markers.csv - Arrange window markers for DAWs
- tempo_map.json - Tempo and timing data
- README.txt - This file

### Importing into Your DAW

#### Ableton Live
1. Create a new Ableton Set
2. Set tempo to {arrangement.tempo} BPM
3. Create audio tracks and drag stems into clips
4. Create MIDI tracks and import MIDI files
5. Use markers.csv to create locators

#### FL Studio
1. Create new project, set BPM to {arrangement.tempo}
2. Import audio stems into Mixer
3. Import MIDI files into Piano Roll
4. Use tempo_map.json for timing reference

#### Logic Pro
1. Create new Logic project
2. Set tempo to {arrangement.tempo}
3. Import stems into Arrange window
4. Import MIDI files to track stacks
5. Use markers.csv to create Arrange markers

#### Pro Tools
1. Create new Pro Tools session at {arrangement.tempo} BPM
2. Import audio stems to tracks
3. Import MIDI clips to MIDI tracks
4. Use markers.csv for memory locations

#### Studio One
1. Create new Song at {arrangement.tempo} BPM
2. Drag stems to audio tracks
3. Import MIDI files to instrument tracks
4. Use markers.csv for markers

#### Reaper
1. Create new Reaper project
2. Set tempo to {arrangement.tempo}
3. Import stems via File > Import Media
4. Import MIDI via File > Import MIDI
5. Use markers.csv as guide

### Support
For issues or questions, visit the LoopArchitect project.
"""
        
        return readme

    @staticmethod
    def _get_stem_names(arrangement: ProducerArrangement) -> List[str]:
        """Get list of stem file names that would be exported."""
        stems = [
            "kick.wav",
            "snare.wav",
            "hats.wav",
            "bass.wav",
            "melody.wav",
            "pads.wav",
        ]
        
        # Add additional stems based on arrangement
        instruments_used = set()
        for section in arrangement.sections:
            for instrument in section.instruments:
                instruments_used.add(instrument.value)
        
        # Could add fx.wav, strings.wav, etc. based on what's used
        if "strings" in instruments_used:
            stems.append("strings.wav")
        
        return stems

    @staticmethod
    def _get_midi_files(arrangement: ProducerArrangement) -> List[str]:
        """Get list of MIDI file names that would be exported."""
        return [
            "drums.mid",
            "bass.mid",
            "melody.mid",
        ]

    @staticmethod
    def get_export_package_info(arrangement: ProducerArrangement) -> Dict:
        """Get complete package info for export."""
        return {
            "type": "LoopArchitect DAW Export",
            "version": "1.0",
            "format": "ZIP",
            "contents": {
                "stems": DAWExporter._get_stem_names(arrangement),
                "midi": DAWExporter._get_midi_files(arrangement),
                "metadata": [
                    "markers.csv",
                    "tempo_map.json",
                    "README.txt",
                ],
            },
            "supported_daws": DAWExporter.SUPPORTED_DAWS,
            "tempo": arrangement.tempo,
            "key": arrangement.key,
            "duration_bars": arrangement.total_bars,
            "duration_seconds": arrangement.total_seconds,
        }
