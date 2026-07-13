"""
Generates one voiceover clip per script segment, using genblaze-elevenlabs.
"""
import asyncio
import os
import re

import httpx
from genblaze_core import Pipeline, Modality
from genblaze_elevenlabs import ElevenLabsTTSProvider

MAX_CONCURRENT = 1

TONE_VOICES: dict[str, str] = {
    "pitch": "pNInz6obpgDQGcFmaJgB",       # Adam
    "pitch_demo": "JBFqnCBsd6RMkjVDRZzb",  # George
    "demo": "EXAVITQu4vr4xnSDxMaL",        # Sarah
    "technical": "21m00Tcm4TlvDq8ikWAM",   # Rachel
}
DEFAULT_VOICE = TONE_VOICES["pitch"]


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
                                  tone: str = "pitch") -> list[dict]:
    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise ValueError("ELEVENLABS_API_KEY not set")

    voice_id = TONE_VOICES.get(tone, DEFAULT_VOICE)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def process(seg: dict) -> dict:
        segment_id = seg["segment_id"]
        text = _prep_text(seg.get("text", ""))

        async with semaphore:
            asset_url = await asyncio.to_thread(
                _generate_one, job_id, segment_id, text, voice_id)

            audio_path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(asset_url)
                r.raise_for_status()
                with open(audio_path, "wb") as f:
                    f.write(r.content)

        return {**seg, "text": text, "audio_path": audio_path}

    results = await asyncio.gather(*(process(seg) for seg in script_segments))
    return list(results)
