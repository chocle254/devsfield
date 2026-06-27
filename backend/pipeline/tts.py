"""
Text-to-Speech generation using Genblaze GMI Cloud
"""
import os
import asyncio
from typing import Optional

from genblaze_core import Workflow
from genblaze_gmicloud import TTSTask


async def generate_audio(text: str, output_path: str) -> str:
    """
    Generate TTS audio using ElevenLabs TTS v3 via GMI Cloud Genblaze.
    
    Args:
        text: The text to convert to speech
        output_path: Where to save the audio file
        
    Returns:
        Path to the generated audio file
    """
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise ValueError("GMI_CLOUD_API_KEY not set in environment")
    
    workflow = Workflow(api_key=gmi_api_key)
    
    tts_task = TTSTask(
        text=text,
        model="elevenlabs-tts-v3",
        voice_id="alloy",  # Can be customized
        output_format="mp3",
    )
    
    result = await asyncio.to_thread(
        lambda: workflow.execute_task(tts_task)
    )
    
    # Save audio to output path
    if isinstance(result, bytes):
        with open(output_path, "wb") as f:
            f.write(result)
    elif hasattr(result, "audio_data"):
        with open(output_path, "wb") as f:
            f.write(result.audio_data)
    else:
        # Result might be a URL - download it
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(result, timeout=60.0)
            response.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(response.content)
    
    return output_path


async def generate_scene_audio(scenes: list[dict]) -> dict[int, str]:
    """
    Generate audio for all scenes in the script.
    
    Args:
        scenes: List of scene dicts with 'text' and 'duration' keys
        
    Returns:
        Dict mapping scene index to audio file path
    """
    audio_files = {}
    
    for i, scene in enumerate(scenes):
        text = scene.get("text", "")
        if not text:
            continue
        
        output_path = f"/tmp/audio_scene_{i}.mp3"
        
        try:
            path = await generate_audio(text, output_path)
            audio_files[i] = path
        except Exception as e:
            raise RuntimeError(f"Failed to generate audio for scene {i}: {str(e)}")
    
    return audio_files
