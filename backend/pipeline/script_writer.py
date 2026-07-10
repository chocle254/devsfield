"""
Generates natural, duration-fitted narration — one line per segment.

Why the narration sounds human and matches the screen:
1. Every segment carries an "observation" of what was ACTUALLY visible
   (URL, title, headings, text) when it was recorded — the narrator
   describes reality, not a guess.
2. Word counts are fitted to each segment's real duration at a natural
   speaking pace (~2.4 words/second), so the voice never has to rush or
   leave awkward silence.
3. A strict spoken-language style guide bans the tells of AI writing
   ("seamlessly", "leverage", "robust"...) and forces contractions, short
   sentences, and a conversational through-line from segment to segment.
"""
import json
import os

import httpx

GMI_CHAT_URL = "https://api.gmi-serving.com/v1/chat/completions"
SCRIPT_MODEL = "deepseek-ai/DeepSeek-V3-0324"

# Comfortable demo narration pace. 145 wpm ≈ 2.4 words/second.
WORDS_PER_SECOND = 2.4

BANNED_PHRASES = [
    "seamlessly", "seamless", "leverage", "leveraging", "robust",
    "cutting-edge", "state-of-the-art", "revolutionize", "game-changer",
    "delve", "empower", "unleash", "elevate", "streamline", "harness",
    "in today's fast-paced world", "look no further", "dive in",
    "user-friendly interface", "intuitive interface", "welcome to",
]


def _target_words(segment: dict) -> int:
    """Fit the word budget to the segment's actual recorded duration."""
    start = segment.get("start_time")
    end = segment.get("end_time")
    if start is None or end is None:
        return 20
    duration = max(2.0, end - start)
    return max(8, min(45, round(duration * WORDS_PER_SECOND)))


def _fallback(segments: list[dict], repo_name: str) -> list[dict]:
    return [
        {**seg,
         "text": seg.get("talking_point")
                 or f"Here's a look at {repo_name} in action.",
         "screen_note": seg.get("feature", seg.get("action", ""))}
        for seg in segments
    ]


async def write_segmented_script(context: dict, segments: list[dict],
                                 tone: str) -> list[dict]:
    """
    Returns the same list of segments, each with an added "text" field —
    the narration line for that specific segment.
    """
    tone_descriptions = {
        "pitch": "confident founder walking an investor through their product",
        "pitch_demo": "confident founder: quick pitch energy, then a hands-on walkthrough",
        "demo": "friendly teammate showing a colleague how the product works",
        "technical": "senior engineer explaining the interesting parts to another developer",
    }
    persona = tone_descriptions.get(tone, "clear, friendly product presenter")

    segments_for_llm = []
    for seg in segments:
        obs = seg.get("observation") or {}
        segments_for_llm.append({
            "segment_id": seg["segment_id"],
            "feature": seg.get("feature", ""),
            "talking_point": seg.get("talking_point", ""),
            "what_the_ai_did": seg.get("reason", seg.get("action", "")),
            "on_screen": {
                "page_title": obs.get("title", ""),
                "headings": obs.get("headings", [])[:4],
                "visible_text": (obs.get("visible_text", "") or "")[:250],
            },
            "target_words": _target_words(seg),
        })

    user_prompt = f"""You are writing the voice-over for a screen-recorded demo video.
You are speaking as: a {persona}.

Project: {context['repo_name']}
What it does: {context.get('description') or 'See README'}
README (for background only — the screen is the source of truth):
{(context.get('readme') or '')[:1200]}

Below are the recorded segments IN ORDER. For each one you know:
- what feature it shows and the one talking point to land
- what the AI presenter actually did on screen
- what was ACTUALLY VISIBLE on screen (title, headings, text) when recorded
- target_words: how many words fit this segment's real duration

Write ONE narration line per segment.

HARD RULES — the difference between sounding human and sounding like AI:
1. Describe what the viewer can actually SEE, using the on_screen data.
   Never mention things that aren't on screen.
2. Stay within ±20% of each segment's target_words. This is a timing
   constraint, not a suggestion — the voice must fit the clip.
3. Talk like a person: contractions (it's, we're, you'll), short sentences,
   occasional sentence fragments are fine. Read each line out loud in your
   head — if it sounds like marketing copy, rewrite it.
4. NEVER use any of these words/phrases: {json.dumps(BANNED_PHRASES)}.
5. Don't read UI labels verbatim ("now I click the button labeled Submit").
   Say what's happening and why it matters ("add a task and it shows up
   instantly").
6. Segments must flow as ONE continuous take: vary sentence openings, use
   connective tissue ("so", "now", "from here", "and that's"), never repeat
   the project name more than twice across the whole script.
7. First segment: hook the viewer with what this app IS in plain words.
   Last segment: land a short, confident close — not a sales pitch.
8. No emojis, no exclamation marks more than once in the whole script.

Segments:
{json.dumps(segments_for_llm, indent=2)}

Return ONLY a valid JSON array, one object per segment, same order:
[
  {{"segment_id": 1, "text": "narration line", "screen_note": "brief note of what's shown"}}
]
No markdown. No explanation."""

    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise RuntimeError("GMI_CLOUD_API_KEY not set")

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.post(
            GMI_CHAT_URL,
            headers={"Authorization": f"Bearer {gmi_api_key}",
                     "Content-Type": "application/json"},
            json={
                "model": SCRIPT_MODEL,
                "messages": [
                    {"role": "system", "content":
                     "You write voice-over scripts that sound like a real "
                     "person talking, never like AI marketing copy. "
                     "Respond ONLY with valid JSON."},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.8,
                "max_tokens": 2500,
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
                text = (match.get("text") or "").strip()
                if not text:
                    text = seg.get("talking_point") or (
                        f"Here's a look at {context['repo_name']} in action.")
                result.append({
                    **seg,
                    "text": text,
                    "screen_note": match.get("screen_note",
                                             seg.get("feature", seg.get("action", ""))),
                })
            return result
    except json.JSONDecodeError:
        pass

    return _fallback(segments, context["repo_name"])
