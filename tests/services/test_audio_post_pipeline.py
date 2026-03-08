from pydub import AudioSegment
from pydub.generators import Sine

from app.services.mastering import apply_mastering
from app.services.stem_separation import separate_and_store_stems


def test_apply_mastering_returns_genre_profile(monkeypatch):
    monkeypatch.setattr("app.services.mastering.settings.feature_mastering_stage", True)
    monkeypatch.setattr("app.services.mastering.settings.mastering_profile_default", "auto")

    source = Sine(440).to_audio_segment(duration=1000).apply_gain(-6)
    result = apply_mastering(source, genre="rnb")

    assert result.applied is True
    assert result.profile == "rnb_smooth"
    assert isinstance(result.peak_dbfs_after, float)


def test_stem_separation_disabled_returns_feature_flag_metadata(monkeypatch):
    monkeypatch.setattr("app.services.stem_separation.settings.feature_stem_separation", False)

    source = AudioSegment.silent(duration=500)
    result = separate_and_store_stems(source, loop_id=123)

    assert result.enabled is False
    assert result.error == "feature_disabled"
    assert result.stem_s3_keys == {}


def test_stem_separation_builtin_uploads_expected_stems(monkeypatch):
    monkeypatch.setattr("app.services.stem_separation.settings.feature_stem_separation", True)
    monkeypatch.setattr("app.services.stem_separation.settings.stem_separation_backend", "builtin")

    uploaded_keys = []

    def _fake_upload(file_bytes, content_type, key):
        uploaded_keys.append((content_type, key, len(file_bytes)))
        return key

    monkeypatch.setattr("app.services.stem_separation.storage.upload_file", _fake_upload)

    source = Sine(220).to_audio_segment(duration=800).apply_gain(-8)
    result = separate_and_store_stems(source, loop_id=77)

    assert result.enabled is True
    assert result.succeeded is True
    assert set(result.stems_generated) == {"bass", "drums", "vocals", "other"}
    assert len(uploaded_keys) == 4
    assert all(item[0] == "audio/wav" for item in uploaded_keys)
