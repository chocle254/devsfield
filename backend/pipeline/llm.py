"""
LLM-based script generation using DeepSeek V3
"""
import json
import os
from typing import AsyncGenerator

import httpx


async def generate_script(topic: str) -> list[dict]:
    """
    Generate a video script using DeepSeek V3 API via AI Gateway.
    
    Each scene in the script is a dict with:
    - text: The narration text for this scene
    - duration: How long to show this scene (seconds)
    - screenshot_prompt: What should be visible in the screenshot
    
    Args:
        topic: The topic/title for the video script
        
    Returns:
        List of scene dictionaries
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY not set in environment")
    
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    
    prompt = f"""Generate a short video script about "{topic}" for a 60-90 second video.

Return ONLY valid JSON with this exact structure:
{{
  "title": "Video Title",
  "scenes": [
    {{
      "text": "Narration text for this scene (100-150 words max)",
      "duration": 10,
      "screenshot_prompt": "Visual description for screenshot generation"
    }},
    ...
  ]
}}

Requirements:
- 4-6 scenes total
- Each scene 10-20 seconds
- Text is natural, conversational narration
- screenshot_prompt describes what should appear visually

Return ONLY the JSON, no markdown code blocks or extra text."""
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        
        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()
        
        # Remove markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0].strip()
        
        script_data = json.loads(content)
        return script_data.get("scenes", [])


async def stream_script_generation(topic: str) -> AsyncGenerator[str, None]:
    """
    Stream script generation progress as SSE-compatible JSON lines.
    
    Args:
        topic: The topic for video generation
        
    Yields:
        JSON-formatted progress events
    """
    try:
        yield json.dumps({"status": "generating_script", "message": f"Generating script for '{topic}'..."}) + "\n"
        
        script = await generate_script(topic)
        
        yield json.dumps({
            "status": "script_ready",
            "message": f"Generated {len(script)} scenes",
            "scene_count": len(script),
        }) + "\n"
        
    except Exception as e:
        yield json.dumps({
            "status": "error",
            "message": f"Script generation failed: {str(e)}"
        }) + "\n"
        raise
