"""
Generates one voiceover clip per script segment, using genblaze-gmicloud.

Segments are generated in parallel (bounded) and each line gets light text
prep so the TTS reads it like a person: clean punctuation for natural
pauses, no dangling fragments the model would rush through.
"""
import asyncio
import os
import re

import httpx
from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudAudioProvider

# How many TTS jobs to run at once
MAX_CONCURRENT = 3

# Curated voice per tone — ElevenLabs voice ids from the provider's
# curated catalog (genblaze_gmicloud.models.voices). Each tone gets the
# delivery style that suits it; the whole video always uses ONE voice so
# the narration sounds like a single person presenting.
#   pitch      -> Adam   (deep, announcer)     : confident investor pitch
#   pitch_demo -> George (warm, narration)     : warm pitch into a demo
#   demo       -> Sarah  (conversational)      : friendly walkthrough
#   technical  -> Rachel (clear, narration)    : precise, easy to follow
TONE_VOICES: dict[str, str] = {
    "pitch": "pNInz6obpgDQGcFmaJgB",       # Adam
    "pitch_demo": "JBFqnCBsd6RMkjVDRZzb",  # George
    "demo": "EXAVITQu4vr4xnSDxMaL",        # Sarah
    "technical": "21m00Tcm4TlvDq8ikWAM",   # Rachel
}
DEFAULT_VOICE = TONE_VOICES["pitch"]


def _prep_text(text: str) -> str:
    """Light cleanup so the TTS delivery sounds natural."""
    text = " ".join(text.split())
    # Em/en dashes read better as commas (short pause, not a hard stop)
    text = re.sub(r"\s+[—–-]{1,2}\s+", ", ", text)
    # Strip markdown remnants that would be read aloud weirdly
    text = text.replace("**", "").replace("`", "").replace("#", "")
    # Ensure terminal punctuation so the clip doesn't end abruptly
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _generate_one(gmi_api_key: str, job_id: str, segment_id: int,
                  text: str, voice_id: str) -> str:
    """Blocking Genblaze pipeline call — run inside a thread."""
    run, _manifest = (
        Pipeline(f"devfields-voice-{job_id}-seg{segment_id}")
        .step(
            GMICloudAudioProvider(api_key=gmi_api_key),
            model="elevenlabs-tts-v3",
            prompt=text,
            voice=voice_id,
            modality=Modality.AUDIO,
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
    """
    For each segment (which has a "text" field), generate a voice clip.
    Returns the same list with "audio_path" added to each segment.
    The narration voice is chosen once per job based on the video tone.
    """
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise ValueError("GMI_CLOUD_API_KEY not set")

    voice_id = TONE_VOICES.get(tone, DEFAULT_VOICE)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def process(seg: dict) -> dict:
        segment_id = seg["segment_id"]
        text = _prep_text(seg.get("text", ""))

        async with semaphore:
            # The Genblaze Pipeline API is synchronous; keep the event loop
            # free by running it in a worker thread.
            asset_url = await asyncio.to_thread(
                _generate_one, gmi_api_key, job_id, segment_id, text, voice_id)

            audio_path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.get(asset_url)
                r.raise_for_status()
                with open(audio_path, "wb") as f:
                    f.write(r.content)

        return {**seg, "text": text, "audio_path": audio_path}

    results = await asyncio.gather(*(process(seg) for seg in script_segments))
    # gather preserves input order, matching the original sequential behavior
    return list(results)
