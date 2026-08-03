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
import re

import httpx

logger = logging.getLogger(__name__)

GMI_CHAT_URL = "https://api.gmi-serving.com/v1/chat/completions"
SCRIPT_MODEL = "deepseek-ai/DeepSeek-V3.2"

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

# The ±20% instruction given to the model in the main prompt is a request,
# not a guarantee — a batched JSON response covering every segment at once
# can and does drift badly on one or two entries even when every other
# segment lands fine. Left unchecked, that drift is only ever discovered
# downstream at video_assembler's hard VOICE_DURATION_TOLERANCE (0.25) gate
# — after TTS has already been generated for the mismatched segment, and
# late enough to fail the whole job. This corridor is deliberately wider
# than that hard gate (0.6-1.5x vs 0.75-1.25x) so ordinary, harmless
# variance never triggers an unnecessary repair call; only genuine drift
# that would actually fail downstream does.
LENGTH_REPAIR_LOW = 0.6
LENGTH_REPAIR_HIGH = 1.5


def _word_count(text: str) -> int:
    return len(text.split())


def _needs_length_repair(text: str, target_words: int) -> bool:
    words = _word_count(text)
    if words == 0:
        return True
    return not (LENGTH_REPAIR_LOW * target_words <= words <= LENGTH_REPAIR_HIGH * target_words)


# A small rotation of generic, non-fabricating filler clauses for the
# deterministic pad fallback. Only fires when BOTH the main script call
# drifted on a segment AND the single-purpose repair call also failed (rare
# — _call_gmi_chat already retries transient errors 3x with backoff before
# giving up). Cycling through several clauses instead of one avoids visibly
# repeating the same sentence back to back if more than one pad is needed;
# none of them assert anything beyond what the segment already established.
_PAD_TEMPLATES = (
    " That's {feature} at work.",
    " You can see it happening right on screen.",
    " It's a small detail, but it matters.",
    " Nothing complicated about it — it just works.",
    " That's the kind of thing that adds up.",
)


def _pad_or_trim(text: str, target_words: int, feature: str) -> str:
    """Deterministic last-resort fixer if even the repair LLM call fails.

    Converges on target_words itself (the middle of the acceptable
    corridor), not just its nearer edge — TTS speaking pace varies a bit
    from the nominal 2.4 wps planning estimate, so landing at the edge of
    "acceptable" risks tipping over it once real audio is generated.
    """
    words = _word_count(text)
    if words > target_words:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        kept, running = [], 0
        for sentence in sentences:
            kept.append(sentence)
            running += _word_count(sentence)
            if running >= target_words:
                break
        return " ".join(kept).strip() or text
    if words < target_words:
        pieces = [text.rstrip()]
        total = words
        i = 0
        # Each template adds only a handful of words; cap iterations
        # defensively so this can never spin — comfortably covers even a
        # long ~90s segment (~216 target words) many times over.
        while total < target_words and i < 40:
            filler = _PAD_TEMPLATES[i % len(_PAD_TEMPLATES)].format(feature=feature or "this")
            pieces.append(filler.strip())
            total += _word_count(filler)
            i += 1
        return " ".join(pieces).strip()
    return text


async def _repair_segments(
    to_repair: list[dict], context: dict, persona: str, gmi_api_key: str,
) -> dict[int, str]:
    """One follow-up call covering every under/over-length segment at once
    — cheaper and faster than a call per segment, and still small enough
    that it doesn't meaningfully add to the job's time budget."""
    prompt = f"""You already wrote a demo voice-over script for {context['repo_name']}, \
speaking as: a {persona}. The following lines didn't fit their segment's \
timing — rewrite ONLY these lines to hit their target_words (±10%), same \
meaning, same spoken, contraction-heavy style, no banned phrases: \
{json.dumps(BANNED_PHRASES)}.

{json.dumps(to_repair, indent=2)}

Return ONLY a valid JSON array: [{{"segment_id": 1, "text": "rewritten line"}}]
No markdown. No explanation."""

    payload = {
        "model": SCRIPT_MODEL,
        "messages": [
            {"role": "system", "content":
             "You write voice-over scripts that sound like a real "
             "person talking, never like AI marketing copy. "
             "Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 800,
    }
    try:
        response = await _call_gmi_chat(payload, gmi_api_key)
        if response.status_code != 200:
            return {}
        content = response.json()["choices"][0]["message"]["content"].strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            return {}
        return {
            int(item["segment_id"]): str(item["text"]).strip()
            for item in parsed if item.get("text")
        }
    except Exception:  # noqa: BLE001 - any failure here just falls through to _pad_or_trim
        logger.warning("[script] length-repair call failed; using deterministic pad/trim.")
        return {}


def _target_words(segment: dict) -> int:
    """Fit the word budget to the segment's actual recorded duration."""
    start = segment.get("start_time")
    end = segment.get("end_time")
    if start is None or end is None:
        return 20
    duration = max(2.0, end - start)
    # Segments are deliberately held on their successful on-screen result so
    # a 45- or 60-second beat has enough time for a real explanation.  The
    # former 45-word ceiling made every long beat receive only about 19
    # seconds of speech, which left most of a requested three/five-minute
    # video silent.  Keep the lower bound for tiny clips, but let the budget
    # scale with the measured recording duration.
    return max(8, round(duration * WORDS_PER_SECOND))


def _fallback(segments: list[dict], repo_name: str) -> list[dict]:
    result = []
    for seg in segments:
        text = seg.get("talking_point") or f"Here's a look at {repo_name} in action."
        result.append({
            **seg,
            "text": _pad_or_trim(text, _target_words(seg), seg.get("feature", "")),
            "screen_note": seg.get("feature", seg.get("action", "")),
        })
    return result


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


# A single flat number applies to connect/read/write/pool alike. That's wrong
# here: the connect phase should fail fast on a truly dead host, but the read
# phase has to wait out a large, non-streamed completion (max_tokens=2500 of
# narration for every beat in the video, generated in one shot). A flat 90s
# was tight enough that GMI Cloud would sometimes still be generating -- and
# billing tokens for -- a response our client had already given up reading,
# which then triggered a *second* billed attempt on retry.
GMI_TIMEOUT = httpx.Timeout(connect=10.0, read=240.0, write=30.0, pool=10.0)


async def _call_gmi_chat(payload: dict, gmi_api_key: str) -> httpx.Response:
    """POST to GMI Cloud's chat completions endpoint, retrying transient
    upstream failures with exponential backoff + jitter. Returns the final
    response (success or the last failed attempt) — callers still check
    status_code themselves for the terminal outcome."""
    last_response: httpx.Response | None = None
    last_exc: Exception | None = None

    for attempt in range(GMI_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=GMI_TIMEOUT) as client:
                response = await client.post(
                    GMI_CHAT_URL,
                    headers={"Authorization": f"Bearer {gmi_api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_exc = exc
            # httpx's own timeout/network exceptions frequently carry no
            # message text at all, so str(exc) alone renders as blank and
            # looks like a logging bug rather than a real, diagnosable error.
            exc_detail = str(exc) or type(exc).__name__
            if attempt == GMI_MAX_RETRIES:
                raise RuntimeError(
                    f"GMI Cloud unreachable after {GMI_MAX_RETRIES + 1} "
                    f"attempts: {exc_detail}") from exc
            delay = GMI_BASE_DELAY_S * (2 ** attempt) + random.uniform(0, 1)
            logger.warning(
                "GMI Cloud network error (attempt %d/%d): %s — retrying in %.1fs",
                attempt + 1, GMI_MAX_RETRIES + 1, exc_detail, delay)
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
            target_words_by_id = {s["segment_id"]: s["target_words"] for s in segments_for_llm}
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

            # Catch any segment the model drifted badly on now, while it's
            # still cheap to fix — not at the hard publish-time gate after
            # TTS has already been generated for it.
            needs_repair = [
                seg for seg in result
                if _needs_length_repair(seg["text"], target_words_by_id.get(seg["segment_id"], 20))
            ]
            if needs_repair:
                logger.info(
                    "[script] %d segment(s) missed their target length; "
                    "repairing before voice generation.", len(needs_repair))
                repair_payload = [
                    {"segment_id": seg["segment_id"], "text": seg["text"],
                     "target_words": target_words_by_id.get(seg["segment_id"], 20)}
                    for seg in needs_repair
                ]
                repaired = await _repair_segments(repair_payload, context, persona, gmi_api_key)
                by_result_id = {seg["segment_id"]: seg for seg in result}
                for seg in needs_repair:
                    seg_id = seg["segment_id"]
                    target = target_words_by_id.get(seg_id, 20)
                    candidate = repaired.get(seg_id, "")
                    if candidate and not _needs_length_repair(candidate, target):
                        by_result_id[seg_id]["text"] = candidate
                    else:
                        # Repair call unavailable, failed, or still off —
                        # guarantee a fit deterministically rather than
                        # letting this reach video_assembler's hard gate.
                        by_result_id[seg_id]["text"] = _pad_or_trim(
                            candidate or seg["text"], target, seg.get("feature", ""))

            return result
    except json.JSONDecodeError:
        pass

    return _fallback(segments, context["repo_name"])
