"""
Generates one narration line per navigation segment, using GMI Cloud.
"""
import json
import os
import httpx


async def write_segmented_script(context: dict, segments: list[dict],
                                  tone: str) -> list[dict]:
    """
    Returns a list matching `segments`, each with an added "text" field —
    the narration line for that specific segment.
    """
    tone_descriptions = {
        "pitch": "investor-ready, highlight impact and uniqueness",
        "demo": "user-focused, show how easy it is to use",
        "technical": "developer-focused, explain architecture and implementation",
    }
    tone_description = tone_descriptions.get(tone, "clear and professional")

    segments_summary = [
        {"segment_id": s["segment_id"], "action": s["action"], "reason": s["reason"]}
        for s in segments
    ]

    user_prompt = f"""Project: {context['repo_name']}
Description: {context['description'] or 'No description provided'}
Framework: {context['framework']}
README summary (first 1500 chars):
{context['readme'][:1500]}

Tone: {tone_description}

Below is a list of navigation segments captured while demoing this app.
Write ONE short narration line (15-25 words) for EACH segment, describing
what's happening on screen in a natural, spoken way. The lines together
should read like a cohesive demo narration, in order.

Segments:
{json.dumps(segments_summary, indent=2)}

Return ONLY a valid JSON array, one object per segment, in the same order,
with exactly these fields:
- "segment_id": integer (must match the input segment_id)
- "text": string (narration line for this segment)
- "screen_note": string (brief description of what's shown)

Return ONLY the JSON array. No markdown. No explanation."""

    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise RuntimeError("GMI_CLOUD_API_KEY not set")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.gmi-serving.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {gmi_api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": "deepseek-ai/DeepSeek-V3-0324",
                "messages": [
                    {"role": "system", "content": "You are a professional tech "
                     "demo narrator. Respond ONLY with valid JSON."},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            },
        )

    if response.status_code != 200:
        raise RuntimeError(f"GMI Cloud error: {response.status_code} {response.text}")

    content = response.json()["choices"][0]["message"]["content"].strip()
    if content.startswith("```json"):
        content = content[7:]
    if content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list) and len(parsed) > 0:
            by_id = {p["segment_id"]: p for p in parsed}
            result = []
            for seg in segments:
                match = by_id.get(seg["segment_id"], {})
                result.append({
                    **seg,
                    "text": match.get("text", f"Here's a look at {context['repo_name']}."),
                    "screen_note": match.get("screen_note", seg["action"]),
                })
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: generic line per segment
    return [
        {**seg, "text": f"Here's a look at {context['repo_name']}.",
         "screen_note": seg["action"]}
        for seg in segments
    ]
