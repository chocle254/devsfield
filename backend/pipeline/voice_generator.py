"""
Generates one voiceover clip per script segment using genblaze-gmicloud
(GMICloudAudioProvider). This uses the SAME GMI_CLOUD_API_KEY the rest of the
pipeline already relies on — no separate ElevenLabs account is required, which
also avoids ElevenLabs' free-tier block on cloud/data-center IPs.

Voice is NON-FATAL: if TTS fails for a segment (or every candidate model is
unavailable on the account), that segment comes back with ``audio_path=None``
and the pipeline keeps going, producing a silent-but-complete segment instead
of failing the whole job.
"""
import asyncio
import os
import re
import shutil
from urllib.parse import urlparse

import httpx
from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudAudioProvider

MAX_CONCURRENT = 1

# Per-segment generation timeout. GMI audio runs through a request queue, so it
# needs a more generous budget than a direct HTTP TTS call.
GEN_TIMEOUT = 120


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
        audio_path: str | None = None

        async with semaphore:
            if working:
                attempts = [working["combo"]]
            else:
                attempts = [(m, voices[gender]) for m, voices in _CANDIDATES]

            for model, voice_id in attempts:
                try:
                    asset_url = await asyncio.to_thread(
                        _generate_one, job_id, segment_id, text,
                        model, voice_id, gmi_api_key)
                    path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
                    await materialize_asset(asset_url, path, timeout=60.0)
                    audio_path = path
                    working["combo"] = (model, voice_id)
                    break
                except Exception as exc:  # noqa: BLE001 — non-fatal by design
                    print(
                        f"[voice] segment {segment_id} attempt failed "
                        f"({model}): {exc}",
                        flush=True,
                    )
                    continue

        if audio_path is None:
            print(
                f"[voice] segment {segment_id}: no TTS model succeeded — "
                f"segment will be silent",
                flush=True,
            )
        return {**seg, "text": text, "audio_path": audio_path}

    # Sequential (semaphore=1) so the first success can lock the working combo
    # before the remaining segments run.
    results = []
    for seg in script_segments:
        results.append(await process(seg))
    return results
