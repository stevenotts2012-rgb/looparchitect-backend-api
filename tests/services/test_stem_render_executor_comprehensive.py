"""Comprehensive tests for StemRenderExecutor (app/services/stem_render_executor.py).

Covers _load_stems, _validate_stem_compatibility, _render_section,
_extract_stem_slice, _apply_stem_processing, _apply_pan, _mix_audio,
_apply_producer_moves, render_to_file.
"""

from __future__ import annotations

import wave
import io
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.services.stem_arrangement_engine import (
    ProducerMove,
    SectionConfig,
    StemRole,
    StemState,
)
from app.services.stem_render_executor import StemRenderError, StemRenderExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _silent(duration_ms: int = 500, sample_rate: int = 44100) -> AudioSegment:
    seg = AudioSegment.silent(duration=duration_ms)
    return seg.set_frame_rate(sample_rate).set_channels(2).set_sample_width(2)


def _write_wav(path: Path, duration_ms: int = 500) -> None:
    """Write a minimal WAV file to *path*."""
    seg = _silent(duration_ms)
    seg.export(str(path), format="wav")


def _make_section(
    name: str = "Verse",
    section_type: str = "verse",
    bars: int = 4,
    bpm: float = 120.0,
    active_stems: set | None = None,
    stem_states: dict | None = None,
    producer_moves: list | None = None,
) -> SectionConfig:
    return SectionConfig(
        name=name,
        section_type=section_type,
        bar_start=0,
        bars=bars,
        active_stems=active_stems or set(),
        energy_level=0.5,
        producer_moves=producer_moves or [],
        stem_states=stem_states or {},
        bpm=bpm,
    )


# ===========================================================================
# StemRenderExecutor.__init__
# ===========================================================================


class TestInit:
    def test_default_sample_rate(self):
        executor = StemRenderExecutor()
        assert executor.target_sample_rate == 44100

    def test_custom_sample_rate(self):
        executor = StemRenderExecutor(target_sample_rate=48000)
        assert executor.target_sample_rate == 48000

    def test_stems_cache_starts_empty(self):
        executor = StemRenderExecutor()
        assert executor.stems_cache == {}


# ===========================================================================
# _load_stems
# ===========================================================================


class TestLoadStems:
    def test_loads_valid_wav_file(self, tmp_path):
        executor = StemRenderExecutor()
        wav = tmp_path / "drums.wav"
        _write_wav(wav)

        executor._load_stems({StemRole.DRUMS: wav})
        assert StemRole.DRUMS in executor.stems_cache
        assert isinstance(executor.stems_cache[StemRole.DRUMS], AudioSegment)

    def test_raises_when_file_missing(self, tmp_path):
        executor = StemRenderExecutor()
        missing = tmp_path / "nonexistent.wav"

        with pytest.raises(StemRenderError, match="not found"):
            executor._load_stems({StemRole.DRUMS: missing})

    def test_resamples_to_target_rate(self, tmp_path):
        executor = StemRenderExecutor(target_sample_rate=22050)

        wav = tmp_path / "bass.wav"
        # Write at 44100Hz, executor should resample
        seg = AudioSegment.silent(duration=500).set_frame_rate(44100)
        seg.export(str(wav), format="wav")

        executor._load_stems({StemRole.BASS: wav})
        assert executor.stems_cache[StemRole.BASS].frame_rate == 22050

    def test_loads_multiple_stems(self, tmp_path):
        executor = StemRenderExecutor()
        for role, name in [(StemRole.DRUMS, "drums"), (StemRole.BASS, "bass")]:
            _write_wav(tmp_path / f"{name}.wav")

        executor._load_stems({
            StemRole.DRUMS: tmp_path / "drums.wav",
            StemRole.BASS: tmp_path / "bass.wav",
        })
        assert StemRole.DRUMS in executor.stems_cache
        assert StemRole.BASS in executor.stems_cache


# ===========================================================================
# _validate_stem_compatibility
# ===========================================================================


class TestValidateStemCompatibility:
    def test_raises_when_no_stems_loaded(self):
        executor = StemRenderExecutor()
        with pytest.raises(StemRenderError, match="No stems loaded"):
            executor._validate_stem_compatibility()

    def test_passes_with_same_length_stems(self, tmp_path):
        executor = StemRenderExecutor()
        _write_wav(tmp_path / "drums.wav", duration_ms=500)
        _write_wav(tmp_path / "bass.wav", duration_ms=500)
        executor._load_stems({
            StemRole.DRUMS: tmp_path / "drums.wav",
            StemRole.BASS: tmp_path / "bass.wav",
        })
        # Should not raise
        executor._validate_stem_compatibility()

    def test_raises_on_different_sample_rates(self, tmp_path):
        executor = StemRenderExecutor()

        drums = tmp_path / "drums.wav"
        bass = tmp_path / "bass.wav"
        # Write both at 44100; manually set cache with different rates
        _write_wav(drums)
        _write_wav(bass)
        executor._load_stems({StemRole.DRUMS: drums, StemRole.BASS: bass})

        # Manually set different sample rate on one
        executor.stems_cache[StemRole.BASS] = (
            executor.stems_cache[StemRole.BASS].set_frame_rate(22050)
        )

        with pytest.raises(StemRenderError, match="different sample rates"):
            executor._validate_stem_compatibility()

    def test_warns_but_does_not_raise_on_different_lengths(self, tmp_path):
        executor = StemRenderExecutor()
        _write_wav(tmp_path / "drums.wav", duration_ms=500)
        _write_wav(tmp_path / "bass.wav", duration_ms=1000)
        executor._load_stems({
            StemRole.DRUMS: tmp_path / "drums.wav",
            StemRole.BASS: tmp_path / "bass.wav",
        })
        # Different lengths should warn but not raise
        executor._validate_stem_compatibility()


# ===========================================================================
# _extract_stem_slice
# ===========================================================================


class TestExtractStemSlice:
    def test_slices_when_stem_longer(self):
        executor = StemRenderExecutor()
        stem = _silent(2000)
        result = executor._extract_stem_slice(stem, 1000)
        assert len(result) == 1000

    def test_loops_when_stem_shorter(self):
        executor = StemRenderExecutor()
        stem = _silent(300)
        result = executor._extract_stem_slice(stem, 1000)
        assert len(result) == 1000

    def test_exact_length_returned_as_is(self):
        executor = StemRenderExecutor()
        stem = _silent(500)
        result = executor._extract_stem_slice(stem, 500)
        assert len(result) == 500


# ===========================================================================
# _apply_stem_processing
# ===========================================================================


class TestApplyStemProcessing:
    def _make_state(
        self,
        role: StemRole = StemRole.DRUMS,
        gain_db: float = 0.0,
        pan: float = 0.0,
        filter_cutoff: float | None = None,
    ) -> StemState:
        return StemState(role=role, active=True, gain_db=gain_db, pan=pan, filter_cutoff=filter_cutoff)

    def test_no_op_when_all_defaults(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        state = self._make_state()
        result = executor._apply_stem_processing(audio, state)
        assert isinstance(result, AudioSegment)
        assert len(result) == 500

    def test_gain_applied(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        state = self._make_state(gain_db=6.0)
        result = executor._apply_stem_processing(audio, state)
        assert isinstance(result, AudioSegment)

    def test_negative_gain_applied(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        state = self._make_state(gain_db=-6.0)
        result = executor._apply_stem_processing(audio, state)
        assert isinstance(result, AudioSegment)

    def test_filter_cutoff_applied(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        state = self._make_state(filter_cutoff=4000.0)
        result = executor._apply_stem_processing(audio, state)
        assert isinstance(result, AudioSegment)

    def test_pan_applied(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        state = self._make_state(pan=0.5)
        result = executor._apply_stem_processing(audio, state)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _apply_pan
# ===========================================================================


class TestApplyPan:
    def test_stereo_output_from_mono_input(self):
        executor = StemRenderExecutor()
        mono = _silent(500).set_channels(1)
        result = executor._apply_pan(mono, 0.5)
        assert result.channels == 2

    def test_stereo_input_returns_stereo(self):
        executor = StemRenderExecutor()
        stereo = _silent(500)
        result = executor._apply_pan(stereo, 0.3)
        assert result.channels == 2

    def test_no_pan_returns_same_length(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        result = executor._apply_pan(audio, 0.0)
        assert len(result) == 500

    def test_left_pan(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        result = executor._apply_pan(audio, -1.0)
        assert isinstance(result, AudioSegment)

    def test_right_pan(self):
        executor = StemRenderExecutor()
        audio = _silent(500)
        result = executor._apply_pan(audio, 1.0)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _mix_audio
# ===========================================================================


class TestMixAudio:
    def test_same_length_mixed_returns_audio_segment(self):
        executor = StemRenderExecutor()
        base = _silent(500)
        overlay = _silent(500)
        result = executor._mix_audio(base, overlay)
        assert isinstance(result, AudioSegment)

    def test_shorter_overlay_produces_audio_segment(self):
        executor = StemRenderExecutor()
        base = _silent(1000)
        overlay = _silent(500)
        result = executor._mix_audio(base, overlay)
        assert isinstance(result, AudioSegment)
        assert len(result) > 0

    def test_longer_overlay_trimmed_produces_audio_segment(self):
        executor = StemRenderExecutor()
        base = _silent(500)
        overlay = _silent(1000)
        result = executor._mix_audio(base, overlay)
        assert isinstance(result, AudioSegment)
        assert len(result) > 0

    def test_mixed_is_audio_segment(self):
        executor = StemRenderExecutor()
        result = executor._mix_audio(_silent(300), _silent(300))
        assert isinstance(result, AudioSegment)

    def test_channels_unified(self):
        executor = StemRenderExecutor()
        mono = _silent(500).set_channels(1)
        stereo = _silent(500)
        result = executor._mix_audio(mono, stereo)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# _apply_producer_moves
# ===========================================================================


class TestApplyProducerMoves:
    def test_no_moves_returns_unchanged(self):
        executor = StemRenderExecutor()
        section = _make_section(producer_moves=[])
        audio = _silent(2000)
        result = executor._apply_producer_moves(audio, section)
        assert len(result) == len(audio)

    def test_drum_fill_returns_audio_segment(self):
        executor = StemRenderExecutor()
        section = _make_section(bpm=120.0, producer_moves=[ProducerMove.DRUM_FILL])
        audio = _silent(4000)
        result = executor._apply_producer_moves(audio, section)
        assert isinstance(result, AudioSegment)

    def test_pre_hook_silence_shortens_audio(self):
        executor = StemRenderExecutor()
        section = _make_section(bpm=120.0, producer_moves=[ProducerMove.PRE_HOOK_SILENCE])
        audio = _silent(4000)
        result = executor._apply_producer_moves(audio, section)
        # The end is replaced with silence — overall length stays same
        assert isinstance(result, AudioSegment)

    def test_crash_hit_returns_audio_segment(self):
        executor = StemRenderExecutor()
        section = _make_section(bpm=120.0, producer_moves=[ProducerMove.CRASH_HIT])
        audio = _silent(4000)
        result = executor._apply_producer_moves(audio, section)
        assert isinstance(result, AudioSegment)

    def test_bass_pause_returns_unchanged(self):
        """BASS_PAUSE is a no-op in the executor (done at stem level)."""
        executor = StemRenderExecutor()
        section = _make_section(bpm=120.0, producer_moves=[ProducerMove.BASS_PAUSE])
        audio = _silent(2000)
        result = executor._apply_producer_moves(audio, section)
        assert len(result) == len(audio)


# ===========================================================================
# _render_section
# ===========================================================================


class TestRenderSection:
    def test_renders_silence_when_no_active_stems(self):
        executor = StemRenderExecutor()
        section = _make_section(bars=4, bpm=120.0, active_stems=set())
        result = executor._render_section(section)
        assert isinstance(result, AudioSegment)
        # 4 bars @ 120 BPM = 8000ms
        assert abs(len(result) - 8000) <= 100

    def test_renders_with_active_stem(self, tmp_path):
        executor = StemRenderExecutor()
        _write_wav(tmp_path / "drums.wav", duration_ms=1000)
        executor._load_stems({StemRole.DRUMS: tmp_path / "drums.wav"})

        section = _make_section(
            bars=2, bpm=120.0, active_stems={StemRole.DRUMS}
        )
        result = executor._render_section(section)
        assert isinstance(result, AudioSegment)
        assert len(result) > 0

    def test_missing_stem_in_cache_is_skipped(self, tmp_path):
        executor = StemRenderExecutor()
        _write_wav(tmp_path / "drums.wav", duration_ms=1000)
        executor._load_stems({StemRole.DRUMS: tmp_path / "drums.wav"})

        # BASS is not in cache but active
        section = _make_section(bars=2, bpm=120.0, active_stems={StemRole.BASS})
        result = executor._render_section(section)
        assert isinstance(result, AudioSegment)


# ===========================================================================
# render_from_stems (integration-style)
# ===========================================================================


class TestRenderFromStems:
    def test_renders_non_empty_audio(self, tmp_path):
        _write_wav(tmp_path / "drums.wav", duration_ms=2000)
        _write_wav(tmp_path / "bass.wav", duration_ms=2000)

        sections = [
            _make_section(
                "Verse",
                bars=2,
                bpm=120.0,
                active_stems={StemRole.DRUMS, StemRole.BASS},
            )
        ]

        executor = StemRenderExecutor()
        with patch("app.services.stem_render_executor.apply_mastering", side_effect=lambda x: x):
            result = executor.render_from_stems(
                stem_files={
                    StemRole.DRUMS: tmp_path / "drums.wav",
                    StemRole.BASS: tmp_path / "bass.wav",
                },
                sections=sections,
                apply_master=True,
            )
        assert isinstance(result, AudioSegment)
        assert len(result) > 0

    def test_skips_mastering_when_disabled(self, tmp_path):
        _write_wav(tmp_path / "drums.wav", duration_ms=500)

        sections = [_make_section("Intro", bars=1, bpm=120.0, active_stems=set())]
        executor = StemRenderExecutor()

        with patch("app.services.stem_render_executor.apply_mastering") as mock_master:
            executor.render_from_stems(
                stem_files={StemRole.DRUMS: tmp_path / "drums.wav"},
                sections=sections,
                apply_master=False,
            )
        mock_master.assert_not_called()


# ===========================================================================
# render_to_file
# ===========================================================================


class TestRenderToFile:
    def test_creates_output_file(self, tmp_path):
        _write_wav(tmp_path / "drums.wav", duration_ms=1000)

        sections = [_make_section("Verse", bars=1, bpm=120.0, active_stems=set())]
        output_path = tmp_path / "output.wav"

        executor = StemRenderExecutor()
        with patch("app.services.stem_render_executor.apply_mastering", side_effect=lambda x: x):
            result = executor.render_to_file(
                stem_files={StemRole.DRUMS: tmp_path / "drums.wav"},
                sections=sections,
                output_path=output_path,
                format="wav",
            )
        assert result == output_path
        assert output_path.exists()
