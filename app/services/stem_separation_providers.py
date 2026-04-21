"""Multi-provider stem separation architecture.

Provider priority
-----------------
1. AudioShake  — commercial API; highest quality (when configured)
2. Demucs      — local ML model (htdemucs / htdemucs_6s)
3. Builtin     — frequency-based spectral split; always available

Selection logic
---------------
if STEM_SEPARATOR_PROVIDER == "audioshake" AND AUDIOSHAKE_API_KEY is set:
    try AudioShake → on failure fall back to Demucs
else:
    use Demucs (with builtin fallback when the package is absent)
"""

from __future__ import annotations

import abc
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydub import AudioSegment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal stem name constants
# ---------------------------------------------------------------------------

STEM_NAMES_4: tuple[str, ...] = ("drums", "bass", "vocals", "other")
STEM_NAMES_6: tuple[str, ...] = ("drums", "bass", "vocals", "guitar", "piano", "other")


# ---------------------------------------------------------------------------
# Provider result
# ---------------------------------------------------------------------------

@dataclass
class ProviderResult:
    """Outcome of a single provider run."""

    stems: dict[str, AudioSegment]
    provider_name: str
    fallback_used: bool
    duration_ms: int
    error: str | None = None


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class StemSeparatorProvider(abc.ABC):
    """Interface that every stem separation provider must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. ``"audioshake"`` or ``"demucs"``."""

    @abc.abstractmethod
    def separate(self, audio: AudioSegment) -> dict[str, AudioSegment]:
        """Separate *audio* into stems.

        Parameters
        ----------
        audio:
            Full-mix AudioSegment to separate.

        Returns
        -------
        dict[str, AudioSegment]
            Stem name → separated AudioSegment.

        Raises
        ------
        Exception
            Any exception signals that separation failed; callers should
            catch and trigger the fallback provider.
        """


# ---------------------------------------------------------------------------
# Demucs provider
# ---------------------------------------------------------------------------

class DemucsProvider(StemSeparatorProvider):
    """Stem separation backed by Demucs ML models.

    Falls back to the builtin frequency-based splitter when the ``demucs``
    package is not installed, preserving the existing behaviour.
    """

    def __init__(self, model: str = "htdemucs", timeout: int = 300) -> None:
        self._model = model
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "demucs"

    def separate(self, audio: AudioSegment) -> dict[str, AudioSegment]:
        """Run Demucs separation, falling back to builtin when unavailable."""
        from app.services.stem_separation import (
            DemucsUnavailableError,
            _builtin_stems,
            _demucs_stems,
        )

        try:
            stems = _demucs_stems(audio, model_name=self._model)
            logger.info(
                "DemucsProvider: separation succeeded (model=%s)", self._model
            )
            return stems
        except DemucsUnavailableError as exc:
            logger.info(
                "DemucsProvider: Demucs unavailable (%s) — using builtin fallback",
                exc,
            )
            return _builtin_stems(audio)
        except Exception as exc:
            logger.warning(
                "DemucsProvider: Demucs separation failed (%s) — using builtin fallback",
                exc,
                exc_info=True,
            )
            return _builtin_stems(audio)


# ---------------------------------------------------------------------------
# AudioShake provider
# ---------------------------------------------------------------------------

class AudioShakeProvider(StemSeparatorProvider):
    """Stem separation backed by the AudioShake cloud API.

    Workflow
    --------
    1. Upload the audio file to AudioShake.
    2. Poll the job status until it completes (async API).
    3. Retrieve per-stem download URLs.
    4. Download each stem and decode to AudioSegment.
    5. Normalise stem names to the internal 4-stem convention.

    Notes
    -----
    AudioShake returns stems named ``"drums"``, ``"bass"``, ``"melody"``,
    ``"other"`` (among others).  This provider normalises them to the
    internal 4-stem set (``drums / bass / vocals / other``) for downstream
    compatibility.  When the API returns ``"melody"`` but not ``"vocals"``,
    the melody stem is stored under the ``"vocals"`` key.
    """

    # AudioShake V2 API base URL
    _BASE_URL = "https://groovy.audioshake.ai"
    _POLL_INTERVAL_S = 3
    _MAX_POLL_ATTEMPTS = 60  # 3 s × 60 = 3 min maximum wait

    # Mapping from AudioShake stem labels to internal names
    _STEM_NAME_MAP: dict[str, str] = {
        "drums": "drums",
        "bass": "bass",
        "vocals": "vocals",
        "voice": "vocals",
        "melody": "vocals",
        "other": "other",
        "accompaniment": "other",
        "music": "other",
    }

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("AudioShake API key must not be empty")
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "audioshake"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def separate(self, audio: AudioSegment) -> dict[str, AudioSegment]:
        """Upload, poll, retrieve, and normalise stems via AudioShake."""
        import requests  # stdlib-compatible; requests is a transitive dep

        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {self._api_key}"})

        logger.info("AudioShakeProvider: uploading audio")
        asset_id = self._upload(session, audio)

        logger.info("AudioShakeProvider: submitting separation job (asset_id=%s)", asset_id)
        job_id = self._submit_job(session, asset_id)

        logger.info("AudioShakeProvider: polling job (job_id=%s)", job_id)
        output_assets = self._poll_job(session, job_id)

        logger.info("AudioShakeProvider: retrieving %d stems", len(output_assets))
        raw_stems = self._download_stems(session, output_assets)

        stems = self._normalise_stems(raw_stems)
        logger.info("AudioShakeProvider: separation complete — stems=%s", list(stems))
        return stems

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _audio_to_bytes(self, audio: AudioSegment) -> bytes:
        buf = io.BytesIO()
        audio.export(buf, format="wav")
        return buf.getvalue()

    def _upload(self, session: Any, audio: AudioSegment) -> str:
        """Upload audio bytes and return the resulting asset ID."""
        wav_bytes = self._audio_to_bytes(audio)
        resp = session.post(
            f"{self._BASE_URL}/upload",
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        asset_id: str = data["assetId"]
        return asset_id

    def _submit_job(self, session: Any, asset_id: str) -> str:
        """Submit a separation job for *asset_id* and return the job ID."""
        resp = session.post(
            f"{self._BASE_URL}/job",
            json={
                "metadata": {"format": "wav"},
                "callbackUrl": None,
                "outputFormat": "wav",
                "stems": ["drums", "bass", "vocals", "other"],
                "assetId": asset_id,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        job_id: str = data["job"]["id"]
        return job_id

    def _poll_job(self, session: Any, job_id: str) -> list[dict[str, Any]]:
        """Poll until the job is complete; return the list of output assets."""
        for attempt in range(self._MAX_POLL_ATTEMPTS):
            resp = session.get(
                f"{self._BASE_URL}/job/{job_id}",
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            status: str = data["job"]["status"]

            if status == "completed":
                return data["job"].get("outputAssets", [])

            if status in ("failed", "error"):
                raise RuntimeError(
                    f"AudioShake job {job_id!r} failed with status={status!r}"
                )

            logger.debug(
                "AudioShakeProvider: job=%s status=%s attempt=%d/%d",
                job_id,
                status,
                attempt + 1,
                self._MAX_POLL_ATTEMPTS,
            )
            time.sleep(self._POLL_INTERVAL_S)

        raise TimeoutError(
            f"AudioShake job {job_id!r} did not complete after "
            f"{self._MAX_POLL_ATTEMPTS * self._POLL_INTERVAL_S}s"
        )

    def _download_stems(
        self,
        session: Any,
        output_assets: list[dict[str, Any]],
    ) -> dict[str, AudioSegment]:
        """Download each output asset and decode to AudioSegment."""
        stems: dict[str, AudioSegment] = {}
        for asset in output_assets:
            stem_label: str = asset.get("name", "other").lower()
            url: str = asset.get("url", "")
            if not url:
                logger.warning(
                    "AudioShakeProvider: no URL for stem=%s, skipping", stem_label
                )
                continue
            resp = session.get(url, timeout=120)
            resp.raise_for_status()
            audio = AudioSegment.from_file(io.BytesIO(resp.content), format="wav")
            stems[stem_label] = audio
        return stems

    def _normalise_stems(
        self,
        raw_stems: dict[str, AudioSegment],
    ) -> dict[str, AudioSegment]:
        """Map AudioShake stem names to the internal 4-stem convention."""
        normalised: dict[str, AudioSegment] = {}
        for raw_name, audio in raw_stems.items():
            internal = self._STEM_NAME_MAP.get(raw_name, "other")
            if internal not in normalised:
                normalised[internal] = audio
            # If two raw stems map to the same internal key (e.g. melody+vocals),
            # overlay them (additive mix with -3 dB attenuation each to avoid clipping).
            else:
                normalised[internal] = normalised[internal].overlay(audio - 3)
        # Ensure all four internal stems are always present (use silence as fallback).
        # When normalised is empty (AudioShake returned no recognisable stems),
        # fall back to the original audio duration so silence stems match the source.
        if normalised:
            duration_ms = max(int(a.duration_seconds * 1000) for a in normalised.values())
        else:
            duration_ms = int(next(iter(raw_stems.values())).duration_seconds * 1000) if raw_stems else 0
        for stem in STEM_NAMES_4:
            if stem not in normalised:
                normalised[stem] = AudioSegment.silent(duration=duration_ms)
        return normalised


# ---------------------------------------------------------------------------
# Provider factory & selection
# ---------------------------------------------------------------------------

def get_provider() -> StemSeparatorProvider:
    """Return the appropriate provider based on environment configuration.

    Selection rules
    ---------------
    * ``STEM_SEPARATOR_PROVIDER=audioshake`` **and** ``AUDIOSHAKE_API_KEY``
      is non-empty → :class:`AudioShakeProvider`.
    * Otherwise → :class:`DemucsProvider`.
    """
    from app.config import settings

    requested = (settings.stem_separator_provider or "demucs").strip().lower()
    logger.info("StemSeparatorProvider: provider requested=%s", requested)

    if requested == "audioshake":
        api_key = (settings.audioshake_api_key or "").strip()
        if api_key:
            logger.info("StemSeparatorProvider: using AudioShake provider")
            return AudioShakeProvider(api_key=api_key)
        logger.warning(
            "StemSeparatorProvider: STEM_SEPARATOR_PROVIDER=audioshake but "
            "AUDIOSHAKE_API_KEY is not set — falling back to Demucs"
        )

    logger.info("StemSeparatorProvider: using Demucs provider")
    return DemucsProvider(
        model=getattr(settings, "demucs_model", "htdemucs"),
        timeout=getattr(settings, "demucs_timeout", 300),
    )


def separate_with_provider(
    audio: AudioSegment,
    provider: StemSeparatorProvider | None = None,
) -> ProviderResult:
    """Run separation using *provider* (or the configured provider).

    When *provider* is :class:`AudioShakeProvider` and it fails, the call
    automatically retries with :class:`DemucsProvider` (fallback).

    Parameters
    ----------
    audio:
        Full-mix to separate.
    provider:
        Provider to use.  When *None*, :func:`get_provider` is called to
        select the appropriate provider from the environment configuration.

    Returns
    -------
    ProviderResult
        Contains the stems dict, provider name actually used, fallback flag,
        wall-clock duration (ms), and any error message.
    """
    if provider is None:
        provider = get_provider()

    t0 = time.monotonic()
    fallback_used = False

    try:
        stems = provider.separate(audio)
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "StemSeparatorProvider: provider_used=%s fallback=False duration_ms=%d",
            provider.name,
            duration_ms,
        )
        return ProviderResult(
            stems=stems,
            provider_name=provider.name,
            fallback_used=False,
            duration_ms=duration_ms,
        )

    except Exception as primary_exc:
        # Only AudioShake triggers a hard fallback to Demucs; Demucs already
        # handles its own builtin fallback internally.
        if not isinstance(provider, AudioShakeProvider):
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "StemSeparatorProvider: provider=%s failed (%s) — no further fallback",
                provider.name,
                primary_exc,
                exc_info=True,
            )
            raise

        logger.warning(
            "StemSeparatorProvider: AudioShake failed (%s) — falling back to Demucs",
            primary_exc,
        )
        fallback_used = True

        from app.config import settings as _settings

        fallback_provider = DemucsProvider(
            model=getattr(_settings, "demucs_model", "htdemucs"),
            timeout=getattr(_settings, "demucs_timeout", 300),
        )
        stems = fallback_provider.separate(audio)
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "StemSeparatorProvider: provider_used=%s fallback=True (from audioshake) duration_ms=%d",
            fallback_provider.name,
            duration_ms,
        )
        return ProviderResult(
            stems=stems,
            provider_name=fallback_provider.name,
            fallback_used=True,
            duration_ms=duration_ms,
            error=str(primary_exc),
        )
