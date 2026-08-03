"""
Generates one voiceover clip per script segment using genblaze-gmicloud
(GMICloudAudioProvider), defaulting to MiniMax's minimax-tts-speech-01-turbo
model. This uses the SAME GMI_CLOUD_API_KEY the rest of the pipeline already
relies on — no separate ElevenLabs account/tokens are required.

Voice is required for every segment. A generated asset is only accepted after
it has been materialized, checked to be non-empty, and successfully probed by
ffprobe. This prevents the video assembler from quietly producing an all- or
partially-silent final video when a provider returns a bad asset.

Duration fit: script_writer sizes each line's word count assuming a fixed
2.4 words/second speaking pace, but that's a planning estimate — the actual
TTS voice may speak noticeably faster or slower, so a clip can come out
clearly shorter or longer than its segment's on-screen time even though the
word count matched the plan. Rather than only discovering that mismatch at
video_assembler's hard VOICE_DURATION_TOLERANCE gate (after which the whole
job fails), this module checks each clip's duration against its segment as
soon as it's generated and, if it's outside tolerance, rewrites the line to
a word count scaled by the *measured* rate and re-synthesizes — before
assembly ever sees it.
"""
import asyncio
import math
import os
import re
import shutil
from urllib.parse import urlparse

import httpx
from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudAudioProvider

from .script_writer import resize_segment_text
from .segment_tool import get_duration, VOICE_DURATION_TOLERANCE

# --- Workaround for a genblaze-gmicloud payload bug (as of 0.3.5) ----------
# GMICloud's own request-queue API requires the narration text to be sent
# under the key "text". genblaze-gmicloud's audio TTS ModelFamily only
# aliases voice->voice_id and leaves the universal "prompt" key untouched,
# so every submit ships {"prompt": "..."} and GMICloud rejects it with
# "invalid payload parameters: text (Required parameter is missing)" for
# every model in _CANDIDATES below (that's why the fallback chain didn't
# help — the same bug hits all three). genblaze-elevenlabs's own provider
# already does this same prompt->text rename internally, so this patches
# gmicloud's provider to match that established convention. Safe to delete
# once a genblaze-gmicloud release adds the alias upstream.
_orig_prepare_payload = GMICloudAudioProvider.prepare_payload


def _prepare_payload_with_text(self, step, **kwargs):
    payload = _orig_prepare_payload(self, step, **kwargs)
    if step.modality == Modality.AUDIO and "text" not in payload and "prompt" in payload:
        payload["text"] = payload.pop("prompt")
    return payload


GMICloudAudioProvider.prepare_payload = _prepare_payload_with_text
# ---------------------------------------------------------------------------

MAX_CONCURRENT = 1

# Per-segment generation timeout. GMI audio runs through a request queue, so it
# needs a more generous budget than a direct HTTP TTS call.
GEN_TIMEOUT = 120

# A valid narration asset must contain actual, playable audio. ffprobe is
# already bounded by segment_tool's timeout, so this validation cannot hang a
# job indefinitely.
MIN_VALID_AUDIO_SECONDS = 0.05

# How many times to rewrite-and-resynthesize a segment whose clip lands
# outside VOICE_DURATION_TOLERANCE before giving up on this stage. Each
# retry is a full TTS round-trip (bounded by GEN_TIMEOUT), so this is a
# small number by design — video_assembler's hard gate is always the final
# word if a clip still doesn't fit after these attempts.
DURATION_FIT_RETRIES = 2

# Guardrail on the words/second we infer from one measured clip. A very
# short or glitchy clip could otherwise produce an absurd rate and cause a
# wild overcorrection on the next attempt; real spoken narration falls
# comfortably inside this range regardless of voice or language.
MIN_PLAUSIBLE_WPS = 1.0
MAX_PLAUSIBLE_WPS = 5.0


async def materialize_asset(asset_url: str, dest_path: str, timeout: float = 60.0) -> None:
    """
    genblaze providers may return either a remote http(s) URL or a local
    filesystem path (when given an output_dir). Handle both so we never feed a
    bare path into httpx, which raises
    "Request URL is missing an 'http://' or 'https://' protocol".
    """
    parsed = urlparse(asset_url)
    if parsed.scheme in ("http", "https"):
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(asset_url)
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(r.content)
        return

    # Local file (possibly a file:// URL). Copy it into the expected location.
    src = parsed.path if parsed.scheme == "file" else asset_url
    if not os.path.exists(src):
        raise RuntimeError(f"Generated asset not found on disk: {src}")
    if os.path.abspath(src) != os.path.abspath(dest_path):
        shutil.copyfile(src, dest_path)


async def _validate_audio_asset(path: str) -> float:
    """Return a valid asset's duration, or raise a clear validation error."""
    if not os.path.isfile(path):
        raise RuntimeError(f"Generated audio asset was not written: {path}")

    size = os.path.getsize(path)
    if size <= 0:
        raise RuntimeError(f"Generated audio asset is empty: {path}")

    duration = await get_duration(path)
    if not math.isfinite(duration) or duration < MIN_VALID_AUDIO_SECONDS:
        raise RuntimeError(
            f"Generated audio asset has invalid duration ({duration!r}s): {path}")
    return duration


def _remove_incomplete_asset(path: str) -> None:
    """Avoid a failed attempt being mistaken for a later successful one."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# Candidate (model, {gender: voice_id}) combos, ordered by preference. We try
# them in order on the first segment and lock onto the first one that actually
# works on this account, then reuse it for the rest of the segments.
#
# minimax-tts-speech-01-turbo is first because that's the model this account
# is billed for (GMI_CLOUD_API_KEY only — no separate ElevenLabs account).
# MiniMax's preset voice ids (e.g. "presenter_female", "male-qn-qingse") are
# shared across the whole speech-0x/2.x family, so the same ids that work on
# minimax-tts-speech-2.6-turbo work here too. 2.6-turbo and inworld remain as
# same-account GMI fallbacks if speech-01-turbo ever errors; ElevenLabs is
# intentionally not in this list since there are no ElevenLabs tokens.
_CANDIDATES: list[tuple[str, dict[str, str]]] = [
    ("minimax-tts-speech-01-turbo", {"female": "presenter_female",
                                     "male": "male-qn-qingse"}),
    ("minimax-tts-speech-2.6-turbo", {"female": "presenter_female",
                                      "male": "male-qn-qingse"}),
    ("inworld-tts-1.5-mini", {"female": "ashley", "male": "ronald"}),
]

# Map the UI "tone" (and a few explicit voice hints) to a gender preference so
# we pick a sensible voice from whichever candidate model ends up working.
_MALE_TONES = {"pitch", "pitch_demo"}


def _gender_for(tone: str, voice: str | None) -> str:
    if voice:
        v = voice.strip().lower()
        if v in ("male", "man", "ronald", "male-qn-qingse", "male-qn-jingying"):
            return "male"
        if v in ("female", "woman", "ashley", "presenter_female", "female-shaonv"):
            return "female"
    return "male" if (tone or "").lower() in _MALE_TONES else "female"


def _prep_text(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"\s+[—–-]{1,2}\s+", ", ", text)
    text = text.replace("**", "").replace("`", "").replace("#", "")
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _generate_one(job_id: str, segment_id: int, text: str,
                  model: str, voice_id: str, gmi_api_key: str) -> str:
    """Generate a single clip with one GMI audio model. Raises on failure."""
    run, _manifest = (
        Pipeline(f"devfields-voice-{job_id}-seg{segment_id}")
        .step(
            GMICloudAudioProvider(api_key=gmi_api_key),
            model=model,
            prompt=text,
            modality=Modality.AUDIO,
            voice_id=voice_id,
        )
        .run(timeout=GEN_TIMEOUT)
    )
    step = run.steps[0]
    if step.status != "succeeded" or not step.assets:
        raise RuntimeError(
            f"model={model} voice_id={voice_id} error={step.error!r}")
    return step.assets[0].url


def _visual_duration_for(seg: dict) -> float | None:
    """Mirror video_assembler's own start/end -> duration calculation so the
    two stages can never disagree about what a segment's target is."""
    start = seg.get("start_time")
    end = seg.get("end_time")
    if start is None or end is None:
        return None
    return max(0.5, float(end) - float(start))


async def _fit_segment_duration(
    job_id: str, segment_id: int, text: str, audio_path: str, duration: float,
    visual_duration: float, model: str, voice_id: str, gmi_api_key: str,
    repo_name: str, tone: str, feature: str,
) -> tuple[str, float, str]:
    """If `duration` is already within tolerance of `visual_duration`, return
    the inputs unchanged. Otherwise rewrite the line to a word count scaled
    by this voice's *measured* speaking rate and re-synthesize, up to
    DURATION_FIT_RETRIES times, keeping the best attempt so far at each step.
    """
    min_ok = visual_duration * (1.0 - VOICE_DURATION_TOLERANCE)
    max_ok = visual_duration * (1.0 + VOICE_DURATION_TOLERANCE)
    if min_ok <= duration <= max_ok:
        return audio_path, duration, text

    best_path, best_duration, best_text = audio_path, duration, text

    for attempt in range(1, DURATION_FIT_RETRIES + 1):
        words = max(1, len(best_text.split()))
        measured_wps = min(MAX_PLAUSIBLE_WPS,
                           max(MIN_PLAUSIBLE_WPS, words / best_duration))
        new_target_words = max(8, round(visual_duration * measured_wps))

        try:
            new_text = await resize_segment_text(
                best_text, new_target_words, repo_name, tone, feature, gmi_api_key)
            new_path = f"/tmp/voice_{job_id}_seg{segment_id}_fit{attempt}.mp3"
            _remove_incomplete_asset(new_path)
            asset_url = await asyncio.to_thread(
                _generate_one, job_id, segment_id, new_text, model, voice_id,
                gmi_api_key)
            if not isinstance(asset_url, str) or not asset_url.strip():
                raise RuntimeError("provider returned no audio asset URL")
            await materialize_asset(asset_url, new_path, timeout=60.0)
            new_duration = await _validate_audio_asset(new_path)
        except Exception as exc:  # noqa: BLE001 - keep the best asset so far
            print(
                f"[voice] segment {segment_id} duration-fit attempt "
                f"{attempt} failed, keeping previous clip: {exc}",
                flush=True,
            )
            break

        print(
            f"[voice] segment {segment_id} duration-fit attempt {attempt}: "
            f"{new_duration:.2f}s (target {visual_duration:.1f}s, "
            f"was {best_duration:.2f}s)",
            flush=True,
        )
        _remove_incomplete_asset(best_path)
        best_path, best_duration, best_text = new_path, new_duration, new_text

        if min_ok <= best_duration <= max_ok:
            break

    return best_path, best_duration, best_text


async def generate_segment_voices(script_segments: list[dict],
                                  job_id: str,
                                  tone: str = "pitch",
                                  voice: str | None = None,
                                  context: dict | None = None) -> list[dict]:
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        raise ValueError("GMI_CLOUD_API_KEY not set")

    gender = _gender_for(tone, voice)
    repo_name = (context or {}).get("repo_name") or "this project"
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    # Once one (model, voice) combo succeeds we lock it in so we don't re-probe
    # dead models for every segment. Guarded by the semaphore (concurrency 1).
    working: dict[str, tuple[str, str]] = {}

    async def process(seg: dict) -> dict:
        segment_id = seg["segment_id"]
        text = _prep_text(seg.get("text", ""))
        if not text:
            raise ValueError(
                f"Voice generation requires non-empty narration text for "
                f"segment {segment_id}")

        audio_path: str | None = None
        attempt_errors: list[str] = []

        async with semaphore:
            candidates = [(m, voices[gender]) for m, voices in _CANDIDATES]
            if working:
                # Prefer the known-good combination, but if it starts failing
                # (quota, transient provider issue, bad asset), exhaust every
                # remaining candidate before failing this segment.
                locked_combo = working["combo"]
                attempts = [locked_combo] + [
                    combo for combo in candidates if combo != locked_combo
                ]
            else:
                attempts = candidates

            for model, voice_id in attempts:
                path = f"/tmp/voice_{job_id}_seg{segment_id}.mp3"
                try:
                    _remove_incomplete_asset(path)
                    asset_url = await asyncio.to_thread(
                        _generate_one, job_id, segment_id, text,
                        model, voice_id, gmi_api_key)
                    if not isinstance(asset_url, str) or not asset_url.strip():
                        raise RuntimeError("provider returned no audio asset URL")
                    await materialize_asset(asset_url, path, timeout=60.0)
                    duration = await _validate_audio_asset(path)
                    audio_path = path
                    working["combo"] = (model, voice_id)
                    print(
                        f"[voice] segment {segment_id} generated "
                        f"{duration:.2f}s audio with {model}",
                        flush=True,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - try bounded fallbacks
                    _remove_incomplete_asset(path)
                    attempt_errors.append(f"{model}: {exc}")
                    print(
                        f"[voice] segment {segment_id} attempt failed "
                        f"({model}): {exc}",
                        flush=True,
                    )
                    continue

            if audio_path is not None:
                visual_duration = _visual_duration_for(seg)
                if visual_duration is not None:
                    fit_model, fit_voice_id = working["combo"]
                    audio_path, duration, text = await _fit_segment_duration(
                        job_id, segment_id, text, audio_path, duration,
                        visual_duration, fit_model, fit_voice_id, gmi_api_key,
                        repo_name, tone, seg.get("feature", ""))

        if audio_path is None:
            tried_models = ", ".join(model for model, _ in attempts)
            details = "; ".join(attempt_errors)
            raise RuntimeError(
                f"Voice generation failed for segment {segment_id}: no valid "
                f"non-empty audio asset after trying {tried_models}. {details}")
        return {**seg, "text": text, "audio_path": audio_path}

    # Sequential (semaphore=1) so the first success can lock the working combo
    # before the remaining segments run.
    results = []
    for seg in script_segments:
        results.append(await process(seg))
    return results
