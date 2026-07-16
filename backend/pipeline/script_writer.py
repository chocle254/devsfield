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

GMI Cloud retry policy — why it's here:
GMI Cloud's chat-completions endpoint has been observed returning transient
upstream errors that aren't the caller's fault: 429s ("no available
endpoints") and 400s shaped like an internal routing failure (a
Volcengine-style "ResponseMeta"/"Missing Action parameter" body wrapped as
{"type": "backend_error"}) rather than a real client-side bad request. Both
are retried with exponential backoff; a genuine 4xx caused by our own
payload (401 auth, 404, a real validation error without the backend_error
wrapper) is NOT retried, since retrying those would just waste the job's
time budget on a failure that will never succeed.
"""
import asyncio
import json
import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

GMI_CHAT_URL = "https://api.gmi-serving.com/v1/chat/completions"
SCRIPT_MODEL = "deepseek-ai/DeepSeek-V3-0324"

# Comfortable demo narration pace. 145 wpm ≈ 2.4 words/second.
WORDS_PER_SECOND = 2.4

# Retry policy for transient GMI Cloud failures.
GMI_MAX_RETRIES = 3
GMI_BASE_DELAY_S = 2.0

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


def _is_transient_gmi_error(status_code: int, body_text: str) -> bool:
    """True if this response is worth retrying rather than failing the job.

    Always transient: 429 (rate limit / no available endpoints) and 5xx
    (GMI Cloud's own infra having a bad moment).

    Conditionally transient: a 400 whose body identifies itself as
    {"error": {"type": "backend_error", ...}} — this is GMI Cloud's own
    backend failing to route the request internally (e.g. the
    "Missing Action parameter" / ResponseMeta shape), not a rejection of
    what we sent. A 400 WITHOUT that wrapper is treated as a real client
    error and is not retried, since our payload won't change on retry.
    """
    if status_code == 429 or status_code >= 500:
        return True
    if status_code == 400:
        try:
            body = json.loads(body_text)
            error_type = (body.get("error") or {}).get("type")
            return error_type == "backend_error"
        except (ValueError, AttributeError, TypeError):
            return False
    return False


async def _call_gmi_chat(payload: dict, gmi_api_key: str) -> httpx.Response:
    """POST to GMI Cloud's chat completions endpoint, retrying transient
    upstream failures with exponential backoff + jitter. Returns the final
    response (success or the last failed attempt) — callers still check
    status_code themselves for the terminal outcome."""
    last_response: httpx.Response | None = None
    last_exc: Exception | None = None

    for attempt in range(GMI_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    GMI_CHAT_URL,
                    headers={"Authorization": f"Bearer {gmi_api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            if attempt == GMI_MAX_RETRIES:
                raise RuntimeError(
                    f"GMI Cloud unreachable after {GMI_MAX_RETRIES + 1} "
                    f"attempts: {exc}") from exc
            delay = GMI_BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                "GMI Cloud network error (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, GMI_MAX_RETRIES + 1, exc, delay)
            await asyncio.sleep(delay)
            continue

        if response.status_code == 200:
            return response

        last_response = response
        if not _is_transient_gmi_error(response.status_code, response.text):
            return response  # permanent failure — let the caller raise immediately

        if attempt == GMI_MAX_RETRIES:
            break

        delay = GMI_BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
        logger.warning(
            "GMI Cloud transient error %d (attempt %d/%d): %s — retrying in %.1fs",
            response.status_code, attempt + 1, GMI_MAX_RETRIES + 1,
            response.text[:300], delay)
        await asyncio.sleep(delay)

    if last_response is not None:
        return last_response
    raise RuntimeError(f"GMI Cloud call failed with no response: {last_exc}")


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

    payload = {
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
    }

    response = await _call_gmi_chat(payload, gmi_api_key)

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
