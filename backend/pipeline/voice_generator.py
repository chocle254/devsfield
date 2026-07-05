"""
Voiceover generation using genblaze-gmicloud (ElevenLabs via GMI Cloud).
"""
import os
import httpx
from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudAudioProvider


async def generate_voice(script: list[dict], job_id: str) -> str:
    """Generate voiceover audio using ElevenLabs TTS via GMI Cloud + Genblaze."""

    full_text = " ... ".join([s["text"] for s in script])

    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise ValueError("GMI_CLOUD_API_KEY not set")

    run, manifest = (
        Pipeline(f"devfields-voice-{job_id}")
        .step(
            GMICloudAudioProvider(api_key=gmi_api_key),
            model="elevenlabs-tts-v3",
            prompt=full_text,
            modality=Modality.AUDIO,
        )
        .run(timeout=120)
    )

    step = run.steps[0]
    if step.status != "succeeded" or not step.assets:
        raise RuntimeError(f"Voice generation failed: {step.error}")

    audio_path = f"/tmp/voice_{job_id}.mp3"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(step.assets[0].url)
        with open(audio_path, "wb") as f:
            f.write(r.content)

    return audio_path
