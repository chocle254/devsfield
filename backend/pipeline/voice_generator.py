"""
Generates one voiceover clip per script segment, using genblaze-gmicloud.
"""
import os
import httpx
from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudAudioProvider


async def generate_segment_voices(script_segments: list[dict], job_id: str) -> list[dict]:
    """
    For each segment (which has a "text" field), generate a voice clip.
    Returns the same list with "audio_path" added to each segment.
    """
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise ValueError("GMI_CLOUD_API_KEY not set")

    results = []
    for seg in script_segments:
        text = seg.get("text", "")
        segment_id = seg["segment_id"]

        run, manifest = (
            Pipeline(f"devfields-voice-{job_id}-seg{segment_id}")
            .step(
                GMICloudAudioProvider(api_key=gmi_api_key),
                model="elevenlabs-tts-v3",
                prompt=text,
                modality=Modality.AUDIO,
            )
            .run(timeout=60)
        )

        step = run.steps[0]
        if step.status != "succeeded" or not step.assets:
            raise RuntimeError(
                f"Voice generation failed for segment {segment_id}: {step.error}")

        audio_path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(step.assets[0].url)
            with open(audio_path, "wb") as f:
                f.write(r.content)

        results.append({**seg, "audio_path": audio_path})

    return results
