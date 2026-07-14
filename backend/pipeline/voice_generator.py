"""
Generates one voiceover clip per script segment, using genblaze-elevenlabs.
"""
import asyncio
import os
import re
import shutil
from urllib.parse import urlparse

import httpx
from genblaze_core import Pipeline, Modality
from genblaze_elevenlabs import ElevenLabsTTSProvider

MAX_CONCURRENT = 1


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

TONE_VOICES: dict[str, str] = {
    "pitch": "pNInz6obpgDQGcFmaJgB",       # Adam
    "pitch_demo": "JBFqnCBsd6RMkjVDRZzb",  # George
    "demo": "EXAVITQu4vr4xnSDxMaL",        # Sarah
    "technical": "21m00Tcm4TlvDq8ikWAM",   # Rachel
}
DEFAULT_VOICE = TONE_VOICES["pitch"]

# Named voices selectable from the "Voice" dropdown in the UI. The key is the
# lowercase value sent by the frontend; the value is the ElevenLabs voice_id
# (found in ElevenLabs under each voice's menu -> "View" -> "Voice ID").
#
# >>> Paste the real ElevenLabs voice IDs below. <<<
NAMED_VOICES: dict[str, str] = {
    "lamin": "hILdTfuUq4LRBMrxHERr",
    "julius": "VlUmeC1Uzj3NnwiVR9K9",
    "sinclair": "fx5le4FFKvx12m8z2cAr",
}


def resolve_voice_id(voice: str | None, tone: str) -> str:
    """Pick a voice_id: an explicit named voice wins, else fall back to tone."""
    if voice:
        key = voice.strip().lower()
        if key in NAMED_VOICES:
            return NAMED_VOICES[key]
        if key in TONE_VOICES:
            return TONE_VOICES[key]
        # Allow passing a raw ElevenLabs voice_id straight through.
        return voice.strip()
    return TONE_VOICES.get(tone, DEFAULT_VOICE)


def _prep_text(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"\s+[—–-]{1,2}\s+", ", ", text)
    text = text.replace("**", "").replace("`", "").replace("#", "")
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _generate_one(job_id: str, segment_id: int, text: str, voice_id: str) -> str:
    run, _manifest = (
        Pipeline(f"devfields-voice-{job_id}-seg{segment_id}")
        .step(
            ElevenLabsTTSProvider(output_dir="/tmp"),
            model="eleven_v3",
            prompt=text,
            modality=Modality.AUDIO,
            voice_id=voice_id,
        )
        .run(timeout=90)
    )
    step = run.steps[0]
    if step.status != "succeeded" or not step.assets:
        raise RuntimeError(
            f"Voice generation failed for segment {segment_id}: {step.error}")
    return step.assets[0].url


async def generate_segment_voices(script_segments: list[dict],
                                  job_id: str,
                                  tone: str = "pitch",
                                  voice: str | None = None) -> list[dict]:
    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise ValueError("ELEVENLABS_API_KEY not set")

    voice_id = resolve_voice_id(voice, tone)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def process(seg: dict) -> dict:
        segment_id = seg["segment_id"]
        text = _prep_text(seg.get("text", ""))

        async with semaphore:
            asset_url = await asyncio.to_thread(
                _generate_one, job_id, segment_id, text, voice_id)

            audio_path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
            await materialize_asset(asset_url, audio_path, timeout=60.0)

        return {**seg, "text": text, "audio_path": audio_path}

    results = await asyncio.gather(*(process(seg) for seg in script_segments))
    return list(results)
