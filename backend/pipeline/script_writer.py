import json
import os
import httpx


async def write_script(context: dict, tone: str, video_length: int) -> list[dict]:
    """Generate a narration script using GMI Cloud."""
    
    # Build tone description
    tone_descriptions = {
        "pitch": "investor-ready, highlight impact and uniqueness",
        "demo": "user-focused, show how easy it is to use",
        "technical": "developer-focused, explain architecture and implementation",
    }
    tone_description = tone_descriptions.get(tone, "clear and professional")
    
    # Build user prompt
    user_prompt = f"""Project: {context['repo_name']}
Description: {context['description'] or 'No description provided'}
Framework: {context['framework']}
Language: {context['language']}
README summary (first 2000 chars):
{context['readme'][:2000]}

Write a narration script for a {video_length}-second demo video.
Tone: {tone_description}

Return ONLY a valid JSON array. No markdown. No explanation. No preamble.
Each object in the array must have exactly these fields:
- "time": integer (seconds from start when this line is spoken)
- "text": string (what the narrator says out loud)
- "screen_note": string (what should be visible on screen at this moment)

The script must:
- Start at time 0
- End before {video_length} seconds
- Cover: opening hook, core feature demo, key differentiator, call to action
- Sound natural when read aloud
- Be specific to THIS project, not generic

Return ONLY the JSON array, nothing else."""
    
    # Call GMI Cloud
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise RuntimeError("GMI_CLOUD_API_KEY not set")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.gmi-serving.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {gmi_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-ai/DeepSeek-V3-0324",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional tech demo narrator. Respond ONLY with valid JSON. No markdown, no explanation."
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 2000
            }
        )
        
        if response.status_code != 200:
            raise RuntimeError(f"GMI Cloud error: {response.status_code} {response.text}")
        
        # Parse response
        content = response.json()["choices"][0]["message"]["content"].strip()
        
        # Remove markdown code block if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        # Parse JSON
        try:
            script = json.loads(content)
            if isinstance(script, list):
                return script
        except json.JSONDecodeError:
            pass
    
    # Fallback script if parsing fails
    return [
        {
            "time": 0,
            "text": f"Welcome to {context['repo_name']}.",
            "screen_note": "Landing page"
        },
        {
            "time": 10,
            "text": "Here is what it does.",
            "screen_note": "Main feature"
        },
        {
            "time": 25,
            "text": f"Built with {context['framework']}.",
            "screen_note": "Tech stack"
        },
        {
            "time": 40,
            "text": "Try it today.",
            "screen_note": "Call to action"
        }
    ]
