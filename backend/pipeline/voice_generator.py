"""
Generates one voiceover clip per script segment using genblaze-gmicloud
(GMICloudAudioProvider). This uses the SAME GMI_CLOUD_API_KEY the rest of the
pipeline already relies on — no separate ElevenLabs account is required, which
also avoids ElevenLabs' free-tier block on cloud/data-center IPs.

Voice is required for every segment. A generated asset is only accepted after
it has been materialized, checked to be non-empty, and successfully probed by
ffprobe. This prevents the video assembler from quietly producing an all- or
partially-silent final video when a provider returns a bad asset.
"""
import asyncio
import math
import os
import re
import shutil
from urllib.parse import urlparse

import httpx
from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudAudioProvider

from .segment_tool import get_duration

MAX_CONCURRENT = 1

# Per-segment generation timeout. GMI audio runs through a request queue, so it
# needs a more generous budget than a direct HTTP TTS call.
GEN_TIMEOUT = 120

# A valid narration asset must contain actual, playable audio. ffprobe is
# already bounded by segment_tool's timeout, so this validation cannot hang a
# job indefinitely.
MIN_VALID_AUDIO_SECONDS = 0.05


async def materialize_asset(asset_url: str, dest_path: str, timeout: float = 60.0) -> None:
    """
    genblaze providers may return either a remote http(s) URL or a local
    filesystem path (when given an output_dir). Handle both so we never feed a
    bare path into httpx, which raises
    "Request URL is missing an 'http://' or 'https://' protocol".
    """
    parsed = urlparse(asset_url)
    if parsed.scheme in ("http", "https"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(asset_url)
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(r.content)
        return

    # Local file (possibly a file:// URL). Copy it into the expected location.
    src = parsed.path if parsed.scheme == "file" else asset_url
    if not os.path.exists(src):
        raise RuntimeError(f"Generated asset not found on disk: {src}")
    if os.path.abspath(src) != os.path.abspath(dest_path):
        shutil.copyfile(src, dest_path)


async def _validate_audio_asset(path: str) -> float:
    """Return a valid asset's duration, or raise a clear validation error."""
    if not os.path.isfile(path):
        raise RuntimeError(f"Generated audio asset was not written: {path}")

    size = os.path.getsize(path)
    if size <= 0:
        raise RuntimeError(f"Generated audio asset is empty: {path}")

    duration = await get_duration(path)
    if not math.isfinite(duration) or duration < MIN_VALID_AUDIO_SECONDS:
        raise RuntimeError(
            f"Generated audio asset has invalid duration ({duration!r}s): {path}")
    return duration


def _remove_incomplete_asset(path: str) -> None:
    """Avoid a failed attempt being mistaken for a later successful one."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# Candidate (model, {gender: voice_id}) combos, ordered by preference. We try
# them in order on the first segment and lock onto the first one that actually
# works on this account, then reuse it for the rest of the segments. All voice
# ids come from genblaze-gmicloud's curated catalog (models/voices.py).
#
# ElevenLabs-via-GMI is last on purpose: it routes through GMI's ElevenLabs
# proxy, which can hit the same upstream issues as the direct ElevenLabs API.
_CANDIDATES: list[tuple[str, dict[str, str]]] = [
    ("minimax-tts-speech-2.6-turbo", {"female": "presenter_female",
                                      "male": "presenter_female"}),
    ("inworld-tts-1.5-mini", {"female": "ashley", "male": "ronald"}),
    ("elevenlabs-tts-v3", {"female": "EXAVITQu4vr4xnSDxMaL",   # Sarah
                           "male": "pNInz6obpgDQGcFmaJgB"}),    # Adam
]

# Map the UI "tone" (and a few explicit voice hints) to a gender preference so
# we pick a sensible voice from whichever candidate model ends up working.
_MALE_TONES = {"pitch", "pitch_demo"}


def _gender_for(tone: str, voice: str | None) -> str:
    if voice:
        v = voice.strip().lower()
        if v in ("male", "man", "adam", "george", "antoni", "ronald"):
            return "male"
        if v in ("female", "woman", "sarah", "rachel", "ashley"):
            return "female"
    return "male" if (tone or "").lower() in _MALE_TONES else "female"


def _prep_text(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"\s+[—–-]{1,2}\s+", ", ", text)
    text = text.replace("**", "").replace("`", "").replace("#", "")
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _generate_one(job_id: str, segment_id: int, text: str,
                  model: str, voice_id: str, gmi_api_key: str) -> str:
    """Generate a single clip with one GMI audio model. Raises on failure."""
    run, _manifest = (
        Pipeline(f"devfields-voice-{job_id}-seg{segment_id}")
        .step(
            GMICloudAudioProvider(api_key=gmi_api_key),
            model=model,
            prompt=text,
            modality=Modality.AUDIO,
            voice_id=voice_id,
        )
        .run(timeout=GEN_TIMEOUT)
    )
    step = run.steps[0]
    if step.status != "succeeded" or not step.assets:
        raise RuntimeError(
            f"model={model} voice_id={voice_id} error={step.error!r}")
    return step.assets[0].url


async def generate_segment_voices(script_segments: list[dict],
                                  job_id: str,
                                  tone: str = "pitch",
                                  voice: str | None = None) -> list[dict]:
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise ValueError("GMI_CLOUD_API_KEY not set")

    gender = _gender_for(tone, voice)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # Once one (model, voice) combo succeeds we lock it in so we don't re-probe
    # dead models for every segment. Guarded by the semaphore (concurrency 1).
    working: dict[str, tuple[str, str]] = {}

    async def process(seg: dict) -> dict:
        segment_id = seg["segment_id"]
        text = _prep_text(seg.get("text", ""))
        if not text:
            raise ValueError(
                f"Voice generation requires non-empty narration text for "
                f"segment {segment_id}")

        audio_path: str | None = None
        attempt_errors: list[str] = []

        async with semaphore:
            candidates = [(m, voices[gender]) for m, voices in _CANDIDATES]
            if working:
                # Prefer the known-good combination, but if it starts failing
                # (quota, transient provider issue, bad asset), exhaust every
                # remaining candidate before failing this segment.
                locked_combo = working["combo"]
                attempts = [locked_combo] + [
                    combo for combo in candidates if combo != locked_combo
                ]
            else:
                attempts = candidates

            for model, voice_id in attempts:
                path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
                try:
                    _remove_incomplete_asset(path)
                    asset_url = await asyncio.to_thread(
                        _generate_one, job_id, segment_id, text,
                        model, voice_id, gmi_api_key)
                    if not isinstance(asset_url, str) or not asset_url.strip():
                        raise RuntimeError("provider returned no audio asset URL")
                    await materialize_asset(asset_url, path, timeout=60.0)
                    duration = await _validate_audio_asset(path)
                    audio_path = path
                    working["combo"] = (model, voice_id)
                    print(
                        f"[voice] segment {segment_id} generated "
                        f"{duration:.2f}s audio with {model}",
                        flush=True,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - try bounded fallbacks
                    _remove_incomplete_asset(path)
                    attempt_errors.append(f"{model}: {exc}")
                    print(
                        f"[voice] segment {segment_id} attempt failed "
                        f"({model}): {exc}",
                        flush=True,
                    )
                    continue

        if audio_path is None:
            tried_models = ", ".join(model for model, _ in attempts)
            details = "; ".join(attempt_errors)
            raise RuntimeError(
                f"Voice generation failed for segment {segment_id}: no valid "
                f"non-empty audio asset after trying {tried_models}. {details}")
        return {**seg, "text": text, "audio_path": audio_path}

    # Sequential (semaphore=1) so the first success can lock the working combo
    # before the remaining segments run.
    results = []
    for seg in script_segments:
        results.append(await process(seg))
    return results
