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
import csv
import io
import zipfile
from typing import Dict, List
from pathlib import Path
from pydub import AudioSegment
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

    @staticmethod
    def build_export_zip(
        arrangement_id: int,
        full_mix: AudioSegment,
        bpm: float,
        musical_key: str,
        sections: List[Dict],
        midi_files: Dict[str, bytes] | None = None,
    ) -> tuple[bytes, Dict]:
        """Build a real DAW export ZIP with non-empty stems and metadata files."""
        midi_files = midi_files or {}

        stems = DAWExporter._derive_stems_from_mix(full_mix)
        DAWExporter._validate_stems(stems, expected_duration_ms=len(full_mix))

        markers_csv = DAWExporter._generate_markers_csv_from_sections(sections, bpm)
        tempo_map_json = json.dumps(
            {
                "constant_tempo": True,
                "bpm": bpm,
                "time_signature": "4/4",
                "total_bars": DAWExporter._estimate_total_bars(sections),
                "changes": [{"bar": 1, "bpm": bpm, "time_signature": "4/4"}],
            },
            indent=2,
        )
        readme = DAWExporter._generate_readme_text(
            arrangement_id=arrangement_id,
            bpm=bpm,
            musical_key=musical_key,
            sections=sections,
            midi_included=sorted(list(midi_files.keys())),
        )

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            stem_names: list[str] = []
            for stem_name, stem_audio in stems.items():
                stem_bytes = io.BytesIO()
                stem_audio.export(stem_bytes, format="wav")
                raw = stem_bytes.getvalue()
                if not raw:
                    raise ValueError(f"Generated empty stem file: {stem_name}")
                archive.writestr(f"stems/{stem_name}.wav", raw)
                stem_names.append(f"stems/{stem_name}.wav")

            midi_paths: list[str] = []
            for midi_filename, midi_content in midi_files.items():
                if not midi_content:
                    continue
                path = f"midi/{midi_filename}"
                archive.writestr(path, midi_content)
                midi_paths.append(path)

            archive.writestr("markers.csv", markers_csv.encode("utf-8"))
            archive.writestr("tempo_map.json", tempo_map_json.encode("utf-8"))
            archive.writestr("README.txt", readme.encode("utf-8"))

        payload = zip_buffer.getvalue()
        if not payload:
            raise ValueError("Generated DAW export ZIP is empty")

        return payload, {
            "stems": stem_names,
            "midi": midi_paths,
            "metadata": ["markers.csv", "tempo_map.json", "README.txt"],
        }

    @staticmethod
    def _derive_stems_from_mix(full_mix: AudioSegment) -> Dict[str, AudioSegment]:
        """Create real, non-empty stem tracks from the rendered mix using frequency bands."""
        duration_ms = len(full_mix)

        kick = full_mix.low_pass_filter(140)
        bass = full_mix.high_pass_filter(45).low_pass_filter(260)
        snare = full_mix.high_pass_filter(180).low_pass_filter(4000)
        hats = full_mix.high_pass_filter(5000)
        melody = full_mix.high_pass_filter(700).low_pass_filter(8500)
        pads = full_mix.high_pass_filter(180).low_pass_filter(2200)

        stems = {
            "kick": DAWExporter._normalize_stem_duration(kick, duration_ms),
            "bass": DAWExporter._normalize_stem_duration(bass, duration_ms),
            "snare": DAWExporter._normalize_stem_duration(snare, duration_ms),
            "hats": DAWExporter._normalize_stem_duration(hats, duration_ms),
            "melody": DAWExporter._normalize_stem_duration(melody, duration_ms),
            "pads": DAWExporter._normalize_stem_duration(pads, duration_ms),
        }
        return stems

    @staticmethod
    def _normalize_stem_duration(stem: AudioSegment, duration_ms: int) -> AudioSegment:
        """Ensure all stems start at 0:00 and have equal total duration."""
        clipped = stem[:duration_ms]
        if len(clipped) < duration_ms:
            clipped = clipped + AudioSegment.silent(duration=duration_ms - len(clipped))
        return clipped

    @staticmethod
    def _validate_stems(stems: Dict[str, AudioSegment], expected_duration_ms: int) -> None:
        """Validate non-empty stems and exact duration alignment."""
        if not stems:
            raise ValueError("No stems were generated")

        for name, segment in stems.items():
            if len(segment) <= 0:
                raise ValueError(f"Stem has zero duration: {name}")
            if len(segment) != expected_duration_ms:
                raise ValueError(
                    f"Stem duration mismatch for {name}: expected {expected_duration_ms}ms, got {len(segment)}ms"
                )

    @staticmethod
    def _generate_markers_csv_from_sections(sections: List[Dict], bpm: float) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "Start (bars)", "Start (seconds)", "End (bars)", "End (seconds)", "Color"])

        color_map = {
            "intro": "Blue",
            "verse": "Green",
            "hook": "Red",
            "chorus": "Red",
            "bridge": "Orange",
            "breakdown": "Yellow",
            "outro": "Blue",
        }

        bar_duration_seconds = (60.0 / max(bpm, 1.0)) * 4.0
        for section in sections:
            name = str(section.get("name", "Section"))
            start_bar = int(section.get("bar_start", section.get("start_bar", 0)))
            bars = int(section.get("bars", 1))
            end_bar = max(start_bar, start_bar + bars - 1)
            start_seconds = start_bar * bar_duration_seconds
            end_seconds = (end_bar + 1) * bar_duration_seconds
            color = color_map.get(name.lower(), "Gray")
            writer.writerow([name, start_bar, f"{start_seconds:.2f}", end_bar, f"{end_seconds:.2f}", color])

        return output.getvalue()

    @staticmethod
    def _estimate_total_bars(sections: List[Dict]) -> int:
        max_end_bar = 0
        for section in sections:
            start_bar = int(section.get("bar_start", section.get("start_bar", 0)))
            bars = int(section.get("bars", 1))
            max_end_bar = max(max_end_bar, start_bar + bars)
        return max_end_bar

    @staticmethod
    def _generate_readme_text(
        arrangement_id: int,
        bpm: float,
        musical_key: str,
        sections: List[Dict],
        midi_included: List[str],
    ) -> str:
        lines = [
            "# LoopArchitect DAW Export",
            "",
            f"Arrangement ID: {arrangement_id}",
            f"Tempo: {bpm} BPM",
            f"Key: {musical_key}",
            "",
            "Contents:",
            "- stems/*.wav (derived from final rendered mix)",
        ]
        if midi_included:
            lines.append("- midi/*.mid (real MIDI artifacts found for this arrangement)")
        else:
            lines.append("- midi/*.mid not included (no real MIDI artifacts available yet)")
        lines.extend([
            "- markers.csv",
            "- tempo_map.json",
            "- README.txt",
            "",
            "Section markers:",
        ])

        for section in sections:
            name = str(section.get("name", "Section"))
            start_bar = int(section.get("bar_start", section.get("start_bar", 0)))
            bars = int(section.get("bars", 1))
            lines.append(f"- {name}: bars {start_bar}-{start_bar + bars - 1}")

        lines.append("")
        lines.append("Notes:")
        lines.append("- All stems start at 0:00 and have equal duration for DAW alignment.")
        lines.append("- Stems are generated from the completed arrangement render using band-splitting.")
        return "\n".join(lines)
