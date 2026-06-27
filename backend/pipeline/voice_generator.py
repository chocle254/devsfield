import os
import httpx


async def generate_voice(script: list[dict], job_id: str) -> str:
    """Generate voiceover audio using ElevenLabs."""
    
    # Extract all text from script
    full_text = " ... ".join([s["text"] for s in script])
    
    # Get API key
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not set")
    
    # Use George voice (professional male)
    voice_id = "JBFqnCBsd6RMkjVDRZzb"
    
    # Call ElevenLabs
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={
                "text": full_text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
        )
    
    if response.status_code != 200:
        raise RuntimeError(
            f"ElevenLabs TTS failed: {response.status_code} {response.text}"
        )
    
    # Save audio
    audio_path = f"/tmp/voice_{job_id}.mp3"
    with open(audio_path, "wb") as f:
        f.write(response.content)
    
    return audio_path
