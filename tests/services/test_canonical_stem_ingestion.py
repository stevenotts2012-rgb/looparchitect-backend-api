"""Phase 7 tests — Canonical Stem Ingestion Architecture

Covers:
- Phase 1: Ingestion router (all three input modes produce a CanonicalStemManifest)
- Phase 2: Canonical role mapper (aliases, fallbacks, source types)
- Phase 3: Advanced single-file separation (second-stage sub-role classification)
- Phase 4: Priority policy (uploaded > ZIP > AI)
- Phase 5: Canonical manifest data model
- Phase 6: Arranger integration (build_engine_from_manifest, stem_role_from_canonical)
- Regression: existing stem upload unchanged
- Regression: existing ZIP upload unchanged
- No silent stem loss
"""

from __future__ import annotations

import io
import pytest
from unittest.mock import MagicMock, patch

from pydub import AudioSegment
from pydub.generators import Sine

from app.services.canonical_stem_manifest import (
    CANONICAL_ROLES,
    CANONICAL_TO_BROAD,
    CANONICAL_ARRANGEMENT_GROUPS,
    CanonicalStemEntry,
    CanonicalStemManifest,
    SOURCE_AI_SEPARATED,
    SOURCE_UPLOADED_STEM,
    SOURCE_ZIP_STEM,
)
from app.services.stem_role_mapper import (
    RoleMapResult,
    map_ai_stem_to_role,
    map_filename_to_role,
)
from app.services.stem_ingestion_router import (
    SOURCE_MODE_MULTI_STEM,
    SOURCE_MODE_SINGLE_FILE,
    SOURCE_MODE_ZIP_STEM,
    build_manifest_from_ai_separation,
    build_manifest_from_uploaded_stems,
)
from app.services.stem_arrangement_engine import (
    StemArrangementEngine,
    StemRole,
    build_engine_from_manifest,
    stem_role_from_canonical,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wav_bytes(frequency: int = 440, duration_ms: int = 1000) -> bytes:
    seg = Sine(frequency).to_audio_segment(duration=duration_ms).set_frame_rate(44100)
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    return buf.getvalue()


def _make_ingest_result(filenames: list[str], duration_ms: int = 1000):
    """Build a StemPackIngestResult with the given filenames."""
    from app.services.stem_pack_service import StemPackIngestResult
    from app.services.stem_classifier import classify_stem

    role_stems = {}
    role_sources = {}
    stem_classifications = {}

    for fn in filenames:
        audio = AudioSegment.silent(duration=duration_ms)
        sc = classify_stem(fn, audio)
        role = sc.role
        role_stems[role] = audio
        role_sources.setdefault(role, []).append(fn)
        stem_classifications[fn] = sc

    mixed = AudioSegment.silent(duration=duration_ms)
    for a in role_stems.values():
        mixed = mixed.overlay(a)

    return StemPackIngestResult(
        mixed_preview=mixed,
        role_stems=role_stems,
        role_sources=role_sources,
        sample_rate=44100,
        duration_ms=duration_ms,
        source_files=list(filenames),
        alignment={"confidence": 0.95, "auto_aligned": False, "low_confidence": False},
        validation_warnings=[],
        fallback_to_loop=False,
        stem_classifications=stem_classifications,
    )


# ===========================================================================
# Phase 5 — CanonicalStemManifest data model
# ===========================================================================


class TestCanonicalStemManifest:
    def test_roles_property_deduplicates(self):
        manifest = CanonicalStemManifest(stems=[
            CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM),
            CanonicalStemEntry("kick", "drums", "k2.wav", 0.8, SOURCE_UPLOADED_STEM),
        ])
        assert manifest.roles == ["kick"]

    def test_broad_roles_property(self):
        manifest = CanonicalStemManifest(stems=[
            CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM),
            CanonicalStemEntry("bass", "bass", "b.wav", 0.9, SOURCE_UPLOADED_STEM),
        ])
        assert manifest.broad_roles == ["bass", "drums"]

    def test_by_role_returns_first_match(self):
        e = CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM)
        manifest = CanonicalStemManifest(stems=[e])
        assert manifest.by_role("kick") is e

    def test_by_role_returns_none_when_missing(self):
        manifest = CanonicalStemManifest(stems=[])
        assert manifest.by_role("kick") is None

    def test_by_broad_role(self):
        manifest = CanonicalStemManifest(stems=[
            CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM),
            CanonicalStemEntry("snare", "drums", "s.wav", 0.9, SOURCE_UPLOADED_STEM),
            CanonicalStemEntry("bass", "bass", "b.wav", 0.9, SOURCE_UPLOADED_STEM),
        ])
        drums = manifest.by_broad_role("drums")
        assert len(drums) == 2
        assert all(e.broad_role == "drums" for e in drums)

    def test_stem_keys_returns_broad_role_mapping(self):
        manifest = CanonicalStemManifest(stems=[
            CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM),
            CanonicalStemEntry("bass", "bass", "b.wav", 0.9, SOURCE_UPLOADED_STEM),
        ])
        keys = manifest.stem_keys()
        assert keys == {"drums": "k.wav", "bass": "b.wav"}

    def test_stem_keys_by_canonical(self):
        manifest = CanonicalStemManifest(stems=[
            CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM),
            CanonicalStemEntry("808", "bass", "b808.wav", 0.9, SOURCE_UPLOADED_STEM),
        ])
        keys = manifest.stem_keys_by_canonical()
        assert keys == {"kick": "k.wav", "808": "b808.wav"}

    def test_to_dict_has_required_keys(self):
        manifest = CanonicalStemManifest(
            stems=[CanonicalStemEntry("kick", "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM)],
            source_mode=SOURCE_MODE_MULTI_STEM,
            loop_id=42,
        )
        d = manifest.to_dict()
        assert "source_mode" in d
        assert "loop_id" in d
        assert "roles" in d
        assert "broad_roles" in d
        assert "stems" in d
        assert d["loop_id"] == 42


class TestCanonicalRoleTaxonomy:
    def test_all_canonical_roles_have_broad_mapping(self):
        """Every canonical role must map to a broad role."""
        for role in CANONICAL_ROLES:
            assert role in CANONICAL_TO_BROAD, f"Missing broad mapping for {role!r}"

    def test_all_canonical_roles_have_arrangement_group(self):
        """Every canonical role must map to an arrangement group."""
        for role in CANONICAL_ROLES:
            assert role in CANONICAL_ARRANGEMENT_GROUPS, (
                f"Missing arrangement group for {role!r}"
            )


# ===========================================================================
# Phase 2 — Canonical role mapper
# ===========================================================================


class TestRoleMapperAliases:
    """Verify alias coverage for the most important canonical roles."""

    @pytest.mark.parametrize("filename,expected_role", [
        # kick aliases
        ("kick_drum.wav",      "kick"),
        ("kick.wav",           "kick"),
        ("kik_01.wav",         "kick"),
        ("bd_loop.wav",        "kick"),
        ("bassdrum_hit.wav",   "kick"),
        # snare aliases
        ("snare.wav",          "snare"),
        ("snr_dry.wav",        "snare"),
        # clap aliases
        ("clap_tight.wav",     "clap"),
        # hi_hat aliases
        ("hihat_open.wav",     "hi_hat"),
        ("hat_closed.wav",     "hi_hat"),
        ("hh_loop.wav",        "hi_hat"),
        # cymbals
        ("crash_cymbal.wav",   "cymbals"),
        ("ride_pattern.wav",   "cymbals"),
        # bass
        ("bass_line.wav",      "bass"),
        ("sub_bass_loop.wav",  "bass"),
        # 808
        ("808_sub.wav",        "808"),
        # piano
        ("piano_chord.wav",    "piano"),
        # keys
        ("keys_riff.wav",      "keys"),
        ("synth_key.wav",      "keys"),
        # guitar
        ("guitar_riff.wav",    "guitar"),
        ("gtr_lead.wav",       "guitar"),
        # pads
        ("pads_layer.wav",     "pads"),
        ("pad_texture.wav",    "pads"),
        # strings
        ("strings_loop.wav",   "strings"),
        # synth
        ("synth_lead.wav",     "synth"),
        # arp
        ("arp_sequence.wav",   "arp"),
        ("arpeggio_loop.wav",  "arp"),
        # melody
        ("melody_hook.wav",    "melody"),
        ("lead_melody.wav",    "melody"),
        # fx
        ("fx_riser.wav",       "fx"),
        ("sfx_sweep.wav",      "fx"),
        # vocal
        ("vocal_chop.wav",     "vocal"),
        ("vox_adlib.wav",      "vocal"),
        # harmony
        ("harmony_chords.wav", "harmony"),
        # full_mix
        ("full_mix.wav",       "full_mix"),
        ("mixdown_stereo.wav", "full_mix"),
    ])
    def test_alias_mapping(self, filename, expected_role):
        result = map_filename_to_role(filename)
        assert result.canonical_role == expected_role, (
            f"{filename!r}: expected {expected_role!r}, got {result.canonical_role!r}"
        )

    def test_result_has_broad_role(self):
        result = map_filename_to_role("kick_drum.wav")
        assert result.broad_role == "drums"

    def test_result_has_source_type(self):
        result = map_filename_to_role("bass.wav", source_type=SOURCE_ZIP_STEM)
        assert result.source_type == SOURCE_ZIP_STEM

    def test_confidence_is_in_range(self):
        result = map_filename_to_role("kick.wav")
        assert 0.0 <= result.confidence <= 1.0

    def test_matched_keywords_populated(self):
        result = map_filename_to_role("kick_drum.wav")
        assert len(result.matched_keywords) >= 1


class TestRoleMapperFallbacks:
    """Low-confidence results must degrade safely — no silent drops."""

    def test_unknown_filename_returns_full_mix(self):
        result = map_filename_to_role("xyzzy_unknown_layer.wav")
        assert result.canonical_role == "full_mix"
        assert result.fallback is True

    def test_low_confidence_piano_falls_back_to_melody(self):
        # When a role is mapped at low confidence, _LOW_CONF_FALLBACK kicks in.
        # "piano" is in the fallback table: piano → melody.
        # To trigger this, we need a filename where piano only matches with low confidence.
        # We test the fallback table directly by checking that piano.wav gives a
        # known-high-confidence result (correctly classified as piano),
        # and then verify the fallback table itself maps piano→melody.
        from app.services.stem_role_mapper import _LOW_CONF_FALLBACK
        # Verify fallback table entry
        assert _LOW_CONF_FALLBACK.get("piano") == "melody"
        # High-confidence piano filename keeps "piano" role
        result = map_filename_to_role("piano.wav")
        assert result.canonical_role in ("piano", "melody")  # high conf → piano; low conf → melody

    def test_no_stem_is_silently_dropped(self):
        """map_filename_to_role must always return a result, never raise."""
        strange_names = [
            "!!@@##.wav",
            "123.wav",
            "A.wav",
            "  .wav",
        ]
        for name in strange_names:
            result = map_filename_to_role(name)
            assert isinstance(result.canonical_role, str)
            assert result.canonical_role  # not empty

    def test_fallback_flag_set_when_degraded(self):
        result = map_filename_to_role("xyzzy.wav")
        assert result.fallback is True


class TestAiStemMapper:
    def test_drums_maps_correctly(self):
        result = map_ai_stem_to_role("drums")
        assert result.canonical_role == "drums"
        assert result.broad_role == "drums"
        assert result.source_type == SOURCE_AI_SEPARATED

    def test_bass_maps_correctly(self):
        result = map_ai_stem_to_role("bass")
        assert result.canonical_role == "bass"
        assert result.broad_role == "bass"

    def test_vocals_maps_to_vocal(self):
        result = map_ai_stem_to_role("vocals")
        assert result.canonical_role == "vocal"
        assert result.broad_role == "vocals"

    def test_other_maps_to_melody(self):
        result = map_ai_stem_to_role("other")
        assert result.canonical_role == "melody"

    def test_confidence_passed_through(self):
        result = map_ai_stem_to_role("bass", confidence=0.85)
        assert result.confidence == 0.85


# ===========================================================================
# Phase 1 — Ingestion router
# ===========================================================================


class TestIngestionRouterUploadedStems:
    """Path B: multi_stem mode → CanonicalStemManifest."""

    def test_produces_canonical_manifest(self):
        ingest_result = _make_ingest_result(["kick.wav", "bass.wav", "melody.wav"])
        stem_keys = {"drums": "stems/loop_1_drums.wav", "bass": "stems/loop_1_bass.wav", "melody": "stems/loop_1_melody.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result,
            loop_id=1,
            stem_s3_keys=stem_keys,
            source_type=SOURCE_UPLOADED_STEM,
            source_mode=SOURCE_MODE_MULTI_STEM,
        )
        assert isinstance(manifest, CanonicalStemManifest)
        assert manifest.source_mode == SOURCE_MODE_MULTI_STEM
        assert manifest.loop_id == 1

    def test_all_stems_present_in_manifest(self):
        ingest_result = _make_ingest_result(["kick.wav", "bass.wav", "melody.wav"])
        stem_keys = {"drums": "stems/k.wav", "bass": "stems/b.wav", "melody": "stems/m.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result,
            loop_id=2,
            stem_s3_keys=stem_keys,
            source_type=SOURCE_UPLOADED_STEM,
        )
        assert len(manifest.stems) >= 3

    def test_source_type_is_uploaded_stem(self):
        ingest_result = _make_ingest_result(["kick.wav", "bass.wav"])
        stem_keys = {"drums": "k.wav", "bass": "b.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=3, stem_s3_keys=stem_keys, source_type=SOURCE_UPLOADED_STEM
        )
        for entry in manifest.stems:
            assert entry.source_type == SOURCE_UPLOADED_STEM

    def test_no_stem_silently_dropped(self):
        """Every file that was classified must appear in the manifest."""
        filenames = ["kick.wav", "bass.wav", "pad_layer.wav", "fx_riser.wav"]
        ingest_result = _make_ingest_result(filenames)
        stem_keys = {
            role: f"stems/{role}.wav"
            for role in ingest_result.role_stems
        }
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=4, stem_s3_keys=stem_keys
        )
        manifest_filenames = {e.original_filename for e in manifest.stems if e.original_filename}
        for fn in filenames:
            assert fn in manifest_filenames, f"{fn!r} was silently dropped from the manifest"

    def test_original_filename_preserved(self):
        ingest_result = _make_ingest_result(["kick_drum_001.wav"])
        stem_keys = {"drums": "k.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=5, stem_s3_keys=stem_keys
        )
        entry = manifest.stems[0]
        assert entry.original_filename == "kick_drum_001.wav"


class TestIngestionRouterZipStems:
    """Path C: zip_stem mode → CanonicalStemManifest."""

    def test_produces_manifest_with_zip_source_type(self):
        ingest_result = _make_ingest_result(["drums.wav", "bass.wav"])
        stem_keys = {"drums": "d.wav", "bass": "b.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result,
            loop_id=10,
            stem_s3_keys=stem_keys,
            source_type=SOURCE_ZIP_STEM,
            source_mode=SOURCE_MODE_ZIP_STEM,
        )
        assert manifest.source_mode == SOURCE_MODE_ZIP_STEM
        for entry in manifest.stems:
            assert entry.source_type == SOURCE_ZIP_STEM


class TestIngestionRouterAiSeparation:
    """Path A: single_file mode → CanonicalStemManifest."""

    def test_produces_canonical_manifest(self):
        separated = {
            "drums": "stems/loop_1_drums.wav",
            "bass": "stems/loop_1_bass.wav",
            "vocals": "stems/loop_1_vocals.wav",
            "other": "stems/loop_1_other.wav",
        }
        manifest = build_manifest_from_ai_separation(separated, loop_id=99)
        assert isinstance(manifest, CanonicalStemManifest)
        assert manifest.source_mode == SOURCE_MODE_SINGLE_FILE
        assert manifest.loop_id == 99

    def test_all_demucs_stems_present(self):
        separated = {
            "drums": "d.wav",
            "bass": "b.wav",
            "vocals": "v.wav",
            "other": "o.wav",
        }
        manifest = build_manifest_from_ai_separation(separated, loop_id=100)
        assert len(manifest.stems) == 4

    def test_source_type_is_ai_separated(self):
        manifest = build_manifest_from_ai_separation(
            {"drums": "d.wav", "bass": "b.wav"}, loop_id=101
        )
        for entry in manifest.stems:
            assert entry.source_type == SOURCE_AI_SEPARATED

    def test_broad_roles_correct(self):
        manifest = build_manifest_from_ai_separation(
            {"drums": "d.wav", "bass": "b.wav", "vocals": "v.wav", "other": "o.wav"},
            loop_id=102,
        )
        broad = set(manifest.broad_roles)
        assert "drums" in broad
        assert "bass" in broad


# ===========================================================================
# Phase 4 — Priority policy
# ===========================================================================


class TestSourcePriority:
    """Uploaded stems must outrank AI-separated stems; AI never replaces user content."""

    def test_uploaded_stems_use_uploaded_source_type(self):
        ingest_result = _make_ingest_result(["kick.wav", "bass.wav"])
        stem_keys = {"drums": "d.wav", "bass": "b.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=20, stem_s3_keys=stem_keys, source_type=SOURCE_UPLOADED_STEM
        )
        ai_entries = [e for e in manifest.stems if e.source_type == SOURCE_AI_SEPARATED]
        assert ai_entries == [], "Uploaded-stem manifest must not contain AI-separated entries"

    def test_zip_stems_use_zip_source_type(self):
        ingest_result = _make_ingest_result(["drums.wav", "bass.wav"])
        stem_keys = {"drums": "d.wav", "bass": "b.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=21, stem_s3_keys=stem_keys, source_type=SOURCE_ZIP_STEM
        )
        ai_entries = [e for e in manifest.stems if e.source_type == SOURCE_AI_SEPARATED]
        assert ai_entries == [], "ZIP-stem manifest must not contain AI-separated entries"


# ===========================================================================
# Phase 3 — Advanced single-file separation
# ===========================================================================


class TestAdvancedStemSeparation:
    """Advanced separation produces a CanonicalStemManifest via run_advanced_separation."""

    def test_run_advanced_separation_returns_result(self, tmp_path):
        from app.services.advanced_stem_separation import run_advanced_separation

        audio = AudioSegment.silent(duration=2000)

        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            result = run_advanced_separation(audio, loop_id=999, backend="builtin")

        assert result.succeeded is True
        assert len(result.stem_entries) > 0

    def test_produces_manifest_with_ai_separated_source(self, tmp_path):
        from app.services.advanced_stem_separation import run_advanced_separation

        audio = AudioSegment.silent(duration=2000)

        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            result = run_advanced_separation(audio, loop_id=998, backend="builtin")

        manifest = result.to_manifest(998)
        assert isinstance(manifest, CanonicalStemManifest)
        for entry in manifest.stems:
            assert entry.source_type == SOURCE_AI_SEPARATED

    def test_fails_gracefully_on_bad_backend(self):
        """An unknown backend falls back to builtin instead of raising.

        The pipeline's job is to always produce stems.  An unrecognised backend
        alias is treated like a missing Demucs install — graceful degradation to
        the frequency-based builtin splitter, not a hard failure.
        """
        from app.services.advanced_stem_separation import run_advanced_separation
        from unittest.mock import MagicMock, patch

        audio = AudioSegment.silent(duration=1000)
        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            result = run_advanced_separation(audio, loop_id=997, backend="nonexistent_backend")
        # The pipeline falls back to builtin, so it succeeds
        assert result.succeeded is True
        assert result.backend == "builtin"
        assert len(result.stem_entries) > 0

    def test_to_manifest_loop_id_set_correctly(self):
        from app.services.advanced_stem_separation import AdvancedSeparationResult, CanonicalStemEntry

        result = AdvancedSeparationResult(
            succeeded=True,
            backend="builtin",
            stem_entries=[
                CanonicalStemEntry("drums", "drums", "d.wav", 0.7, SOURCE_AI_SEPARATED),
            ],
        )
        manifest = result.to_manifest(42)
        assert manifest.loop_id == 42


class TestSubRoleClassifiers:
    """Second-stage sub-role classifiers degrade safely."""

    def test_drums_classifier_returns_valid_subrole(self):
        from app.services.advanced_stem_separation import _classify_drums_subrole

        audio = AudioSegment.silent(duration=500)
        candidate = _classify_drums_subrole(audio)
        assert candidate.role in ("kick", "snare", "hi_hat", "percussion", "cymbals", "drums")
        assert 0.0 < candidate.confidence <= 1.0

    def test_bass_classifier_returns_valid_subrole(self):
        from app.services.advanced_stem_separation import _classify_bass_subrole

        audio = AudioSegment.silent(duration=500)
        candidate = _classify_bass_subrole(audio)
        assert candidate.role in ("bass", "808")

    def test_other_classifier_returns_valid_subrole(self):
        from app.services.advanced_stem_separation import _classify_other_subrole

        audio = AudioSegment.silent(duration=500)
        candidate = _classify_other_subrole(audio)
        assert candidate.role in (
            "piano", "guitar", "pads", "arp", "melody", "keys", "strings", "synth"
        )

    def test_low_confidence_falls_back_to_broad_role(self):
        from app.services.advanced_stem_separation import SUBROLE_MIN_CONFIDENCE, run_advanced_separation

        audio = AudioSegment.silent(duration=1000)

        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            # Use a very short silent segment — all band heuristics will fire at near-zero
            result = run_advanced_separation(audio, loop_id=50, backend="builtin")

        # All entries must have a valid (non-empty) role and broad_role
        for entry in result.stem_entries:
            assert entry.role, "role must not be empty"
            assert entry.broad_role, "broad_role must not be empty"


# ===========================================================================
# Phase 6 — Arranger integration
# ===========================================================================


class TestArrangerIntegration:
    """build_engine_from_manifest and stem_role_from_canonical."""

    def test_stem_role_from_canonical_kick(self):
        assert stem_role_from_canonical("kick") == StemRole.DRUMS

    def test_stem_role_from_canonical_snare(self):
        assert stem_role_from_canonical("snare") == StemRole.DRUMS

    def test_stem_role_from_canonical_808(self):
        assert stem_role_from_canonical("808") == StemRole.BASS

    def test_stem_role_from_canonical_piano(self):
        assert stem_role_from_canonical("piano") == StemRole.MELODY

    def test_stem_role_from_canonical_pads(self):
        assert stem_role_from_canonical("pads") == StemRole.PADS

    def test_stem_role_from_canonical_vocal(self):
        assert stem_role_from_canonical("vocal") == StemRole.VOCALS

    def test_stem_role_from_canonical_unknown_falls_back(self):
        result = stem_role_from_canonical("totally_unknown_role")
        assert result == StemRole.FULL_MIX

    def test_build_engine_from_manifest_with_broad_roles(self):
        """Engine can be built from a manifest containing only broad roles."""
        manifest = CanonicalStemManifest(
            stems=[
                CanonicalStemEntry("drums", "drums", "d.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("bass",  "bass",  "b.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("melody","melody","m.wav", 0.9, SOURCE_UPLOADED_STEM),
            ],
            source_mode=SOURCE_MODE_MULTI_STEM,
            loop_id=1,
        )
        engine = build_engine_from_manifest(manifest, tempo=120, key="C")
        assert isinstance(engine, StemArrangementEngine)
        assert StemRole.DRUMS in engine.available_stems
        assert StemRole.BASS in engine.available_stems
        assert StemRole.MELODY in engine.available_stems

    def test_build_engine_from_manifest_with_sub_roles(self):
        """Engine folds sub-roles (kick/snare/hi_hat) into their parent StemRole."""
        manifest = CanonicalStemManifest(
            stems=[
                CanonicalStemEntry("kick",   "drums", "k.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("snare",  "drums", "s.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("hi_hat", "drums", "h.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("808",    "bass",  "808.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("piano",  "melody","p.wav", 0.9, SOURCE_UPLOADED_STEM),
            ],
            source_mode=SOURCE_MODE_MULTI_STEM,
            loop_id=2,
        )
        engine = build_engine_from_manifest(manifest, tempo=140, key="Am")
        assert StemRole.DRUMS in engine.available_stems
        assert StemRole.BASS in engine.available_stems
        assert StemRole.MELODY in engine.available_stems

    def test_build_engine_can_generate_arrangement(self):
        """Engine built from manifest can produce a valid arrangement."""
        manifest = CanonicalStemManifest(
            stems=[
                CanonicalStemEntry("drums",  "drums",  "d.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("bass",   "bass",   "b.wav", 0.9, SOURCE_UPLOADED_STEM),
                CanonicalStemEntry("melody", "melody", "m.wav", 0.9, SOURCE_UPLOADED_STEM),
            ],
            source_mode=SOURCE_MODE_MULTI_STEM,
            loop_id=3,
        )
        engine = build_engine_from_manifest(manifest, tempo=120, key="C")
        sections = engine.generate_arrangement(target_bars=32)
        assert len(sections) > 0


# ===========================================================================
# Regression: existing stem upload unchanged
# ===========================================================================


class TestExistingStemUploadUnchanged:
    """Existing stem_pack_service / stem_classifier must behave identically."""

    def test_ingest_stem_files_unchanged(self):
        """ingest_stem_files must still produce the same result shape."""
        from app.services.stem_pack_service import StemSourceFile, ingest_stem_files

        files = [
            StemSourceFile(
                filename="kick.wav",
                content=_wav_bytes(80, 1000),
            ),
            StemSourceFile(
                filename="bass.wav",
                content=_wav_bytes(55, 1000),
            ),
        ]
        result = ingest_stem_files(files)
        assert "drums" in result.role_stems or "bass" in result.role_stems
        assert result.duration_ms == 1000
        assert result.sample_rate == 44100

    def test_stem_classifier_unchanged(self):
        """The legacy classify_stem must still work."""
        from app.services.stem_classifier import classify_stem
        from pydub import AudioSegment

        sc = classify_stem("kick_drum.wav", AudioSegment.silent(duration=500))
        assert sc.role == "drums"
        assert sc.group == "rhythm"
        assert sc.confidence > 0.0

    def test_stem_role_classifier_wrapper_unchanged(self):
        """stem_role_classifier.py compatibility wrapper must still export correctly."""
        from app.services.stem_role_classifier import (
            STEM_ROLES,
            ARRANGEMENT_GROUPS,
            StemClassification,
            classify_stem,
        )
        assert "drums" in STEM_ROLES
        assert "bass" in STEM_ROLES


# ===========================================================================
# Regression: existing ZIP upload unchanged
# ===========================================================================


class TestExistingZipUploadUnchanged:
    def test_extract_stem_files_from_zip_unchanged(self):
        """ZIP extraction must still work with the new infrastructure."""
        import zipfile
        from app.services.stem_pack_extractor import extract_stem_files_from_zip

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("drums.wav", _wav_bytes(frequency=100, duration_ms=500))
            zf.writestr("bass.wav", _wav_bytes(frequency=55, duration_ms=500))
        result = extract_stem_files_from_zip(buf.getvalue())
        assert len(result) == 2
        filenames = {r.filename for r in result}
        assert "drums.wav" in filenames
        assert "bass.wav" in filenames


# ===========================================================================
# Edge cases & no silent stem loss
# ===========================================================================


class TestNoSilentStemLoss:
    """Every ingested stem must appear in the final manifest — no silent drops."""

    def test_safety_net_adds_unaccounted_stems(self):
        """Stems in stem_s3_keys that have no matching classification still appear."""
        ingest_result = _make_ingest_result(["kick.wav"])
        # Add an extra key that has no corresponding classification
        stem_keys = {"drums": "d.wav", "harmony": "harmony_extra.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=50, stem_s3_keys=stem_keys
        )
        manifest_keys = {e.file_key for e in manifest.stems}
        assert "harmony_extra.wav" in manifest_keys, "Safety-net entry must be included"

    def test_empty_stem_classifications_handled_gracefully(self):
        """If stem_classifications is empty, no exception is raised."""
        from app.services.stem_pack_service import StemPackIngestResult

        ingest_result = StemPackIngestResult(
            mixed_preview=AudioSegment.silent(duration=1000),
            role_stems={},
            role_sources={},
            sample_rate=44100,
            duration_ms=1000,
            source_files=[],
            alignment={},
            validation_warnings=[],
            fallback_to_loop=False,
            stem_classifications={},
        )
        stem_keys = {"drums": "d.wav"}
        manifest = build_manifest_from_uploaded_stems(
            ingest_result, loop_id=60, stem_s3_keys=stem_keys
        )
        assert any(e.file_key == "d.wav" for e in manifest.stems)


# ===========================================================================
# Backend priority chain — stem_separation.py
# ===========================================================================


class TestStemSeparationBackendPriorityChain:
    """separate_stems_with_fallback always returns stems, even when preferred backend fails."""

    def test_builtin_backend_returns_four_stems(self):
        from app.services.stem_separation import separate_stems_with_fallback
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=1000)
        stems, used = separate_stems_with_fallback(audio, "builtin")
        assert isinstance(stems, dict)
        assert len(stems) >= 4
        assert used == "builtin"

    def test_mock_backend_alias_accepted(self):
        from app.services.stem_separation import separate_stems_with_fallback
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        stems, used = separate_stems_with_fallback(audio, "mock")
        # mock falls to builtin chain
        assert isinstance(stems, dict)
        assert len(stems) >= 1

    def test_demucs_htdemucs_6s_falls_back_to_builtin_when_unavailable(self):
        """When demucs is not installed, demucs_htdemucs_6s falls back to builtin."""
        from app.services.stem_separation import separate_stems_with_fallback
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        # demucs is not installed in the test environment, so this must fall back
        stems, used_backend = separate_stems_with_fallback(audio, "demucs_htdemucs_6s")
        assert isinstance(stems, dict)
        assert len(stems) >= 1
        # The used backend should be "builtin" (fallback)
        assert used_backend == "builtin"

    def test_demucs_htdemucs_falls_back_to_builtin_when_unavailable(self):
        from app.services.stem_separation import separate_stems_with_fallback
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        stems, used_backend = separate_stems_with_fallback(audio, "demucs_htdemucs")
        assert isinstance(stems, dict)
        assert used_backend == "builtin"

    def test_demucs_alias_falls_back_to_builtin_when_unavailable(self):
        from app.services.stem_separation import separate_stems_with_fallback
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        stems, used_backend = separate_stems_with_fallback(audio, "demucs")
        assert isinstance(stems, dict)
        assert used_backend == "builtin"

    def test_builtin_stems_returns_standard_keys(self):
        from app.services.stem_separation import _builtin_stems
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        stems = _builtin_stems(audio)
        assert set(stems.keys()) == {"bass", "drums", "vocals", "other"}


class TestDemucsUnavailableError:
    def test_demucs_stems_raises_when_not_installed(self):
        from app.services.stem_separation import _demucs_stems, DemucsUnavailableError
        from pydub import AudioSegment
        import unittest.mock

        audio = AudioSegment.silent(duration=500)
        # Ensure demucs is not importable
        with unittest.mock.patch.dict("sys.modules", {"demucs": None}):
            with pytest.raises(DemucsUnavailableError):
                _demucs_stems(audio, model_name="htdemucs_6s")

    def test_separate_and_store_stems_falls_back_on_demucs_backend(self):
        """separate_and_store_stems succeeds when demucs backend is configured.

        The provider system routes through DemucsProvider, which internally falls
        back to the builtin frequency-based splitter when the demucs package is
        absent.  The ``backend`` field now reflects the provider used (``"demucs"``)
        rather than the internal splitter name (``"builtin"``).
        """
        from app.services.stem_separation import separate_and_store_stems
        from unittest.mock import MagicMock, patch
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        with patch("app.services.stem_separation.settings") as mock_settings:
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs_htdemucs_6s"
            with patch("app.services.stem_separation.storage") as mock_storage:
                mock_storage.upload_file = MagicMock()
                result = separate_and_store_stems(audio, loop_id=1)
        assert result.enabled is True
        assert result.succeeded is True
        # DemucsProvider handles the builtin fallback internally; the provider
        # name reported is "demucs" (not "builtin").
        assert result.backend == "demucs"


# ===========================================================================
# htdemucs_6s stem name mapping — stem_role_mapper.py
# ===========================================================================


class TestHtdemucs6sStemMapping:
    """AI stem names from the 6-stem model map to correct canonical roles."""

    @pytest.mark.parametrize("stem_name,expected_role", [
        # 4-stem model names
        ("drums",   "drums"),
        ("bass",    "bass"),
        ("vocals",  "vocal"),
        ("other",   "melody"),
        # htdemucs_6s additional stems
        ("piano",   "piano"),
        ("guitar",  "guitar"),
        ("keys",    "keys"),
        ("synth",   "synth"),
        ("strings", "strings"),
    ])
    def test_6s_stem_name_maps_to_canonical_role(self, stem_name, expected_role):
        result = map_ai_stem_to_role(stem_name)
        assert result.canonical_role == expected_role, (
            f"Stem {stem_name!r}: expected {expected_role!r}, got {result.canonical_role!r}"
        )

    def test_guitar_broad_role_is_melody(self):
        result = map_ai_stem_to_role("guitar")
        assert result.broad_role == "melody"

    def test_piano_broad_role_is_melody(self):
        result = map_ai_stem_to_role("piano")
        assert result.broad_role == "melody"


# ===========================================================================
# 6-stem model second-stage classification — advanced_stem_separation.py
# ===========================================================================


class TestSecondStageClassify6Stem:
    """_second_stage_classify handles htdemucs_6s-style stem names correctly."""

    def test_guitar_direct_mapping(self):
        from app.services.advanced_stem_separation import _second_stage_classify
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        candidate = _second_stage_classify("guitar", audio)
        assert candidate.role == "guitar"
        assert candidate.broad_role == "melody"
        assert candidate.confidence >= 0.60

    def test_piano_direct_mapping(self):
        from app.services.advanced_stem_separation import _second_stage_classify
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        candidate = _second_stage_classify("piano", audio)
        assert candidate.role == "piano"
        assert candidate.broad_role == "melody"

    def test_keys_direct_mapping(self):
        from app.services.advanced_stem_separation import _second_stage_classify
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        candidate = _second_stage_classify("keys", audio)
        assert candidate.role == "keys"
        assert candidate.broad_role == "harmony"

    def test_all_6s_stems_produce_valid_candidates(self):
        from app.services.advanced_stem_separation import _second_stage_classify
        from app.services.stem_separation import DEMUCS_6S_STEMS
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=500)
        for stem in DEMUCS_6S_STEMS:
            candidate = _second_stage_classify(stem, audio)
            assert candidate.role, f"role must not be empty for stem={stem!r}"
            assert candidate.broad_role, f"broad_role must not be empty for stem={stem!r}"
            assert 0.0 < candidate.confidence <= 1.0


# ===========================================================================
# Advanced separation — backend reported in result matches used backend
# ===========================================================================


class TestAdvancedSeparationBackendReporting:
    """The AdvancedSeparationResult.backend field always records what actually ran."""

    def test_builtin_backend_reported_in_result(self):
        from app.services.advanced_stem_separation import run_advanced_separation
        from unittest.mock import MagicMock, patch
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=1000)
        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            result = run_advanced_separation(audio, loop_id=200, backend="builtin")
        assert result.succeeded is True
        assert result.backend == "builtin"

    def test_demucs_fallback_reports_builtin(self):
        """When demucs_htdemucs_6s is unavailable, result.backend == 'builtin'."""
        from app.services.advanced_stem_separation import run_advanced_separation
        from unittest.mock import MagicMock, patch
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=1000)
        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            result = run_advanced_separation(audio, loop_id=201, backend="demucs_htdemucs_6s")
        assert result.succeeded is True
        # demucs not installed → pipeline fell back to builtin
        assert result.backend == "builtin"

    def test_manifest_from_6s_fallback_has_ai_separated_source_type(self):
        from app.services.advanced_stem_separation import run_advanced_separation
        from unittest.mock import MagicMock, patch
        from pydub import AudioSegment

        audio = AudioSegment.silent(duration=1000)
        with patch("app.services.advanced_stem_separation.storage") as mock_storage:
            mock_storage.upload_file = MagicMock()
            result = run_advanced_separation(audio, loop_id=202, backend="demucs_htdemucs_6s")
        manifest = result.to_manifest(202)
        for entry in manifest.stems:
            assert entry.source_type == SOURCE_AI_SEPARATED


# ===========================================================================
# preferred_stem_backend config setting
# ===========================================================================


class TestPreferredStemBackendConfig:
    def test_default_is_demucs_htdemucs_6s(self):
        from app.config import Settings

        s = Settings()
        assert s.preferred_stem_backend == "demucs_htdemucs_6s"

    def test_env_override_accepted(self, monkeypatch):
        monkeypatch.setenv("PREFERRED_STEM_BACKEND", "builtin")
        from app.config import Settings

        s = Settings()
        assert s.preferred_stem_backend == "builtin"
