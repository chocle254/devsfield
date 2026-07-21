"""
Assembles the final video from segments: splits the full recording into
per-segment clips, preserves each planned on-screen duration, merges
audio+video per segment, then concatenates everything with the title card.

Every ffmpeg call goes through segment_tool.run_subprocess, which enforces a
hard timeout so a hung encode fails the job cleanly instead of stalling the
whole pipeline forever.

IMPORTANT — why the final video can be short / silent / smaller than the
segments: independently rendered MP4 clips can disagree on resolution,
framerate, pixel format, timebase, audio layout, or AAC timing. A naive concat
can then drop audio or stop at a stream boundary, producing a tiny, truncated
file.

The fix is to normalize EVERY piece to one canonical spec (resolution, fps,
pixel format, SAR, and a real stereo AAC audio track — silent for the title
card), concatenate through ffmpeg's filter graph, and verify output duration.
`concat_segments` is shared with the on-demand download endpoint so downloads
glue the exact same way.
"""
import math
import os
from typing import Optional

from pipeline.segment_tool import (
    get_duration,
    split_clip,
    fit_video_to_duration,
    run_subprocess,
    FFMPEG_TIMEOUT,
)

# The final concat re-encodes every segment plus the title card into one file,
# so it needs a larger budget than a single-clip operation.
CONCAT_TIMEOUT = 600

# Canonical output spec. Every clip is forced to match this exactly so the
# concat step produces one continuous, audible, full-size video.
OUT_W = 1280
OUT_H = 720
OUT_FPS = 30
OUT_SR = 44100  # audio sample rate
TITLE_CARD_SECONDS = 3.0
ASSEMBLY_CONTRACT_VERSION = 3
# Normal TTS speaking-rate variation is expected. A larger mismatch means a
# bad narration asset and must not become a silently broken final video.
VOICE_DURATION_TOLERANCE = 0.25


def duration_tolerance(target_duration: float) -> float:
    """Return the small muxing allowance for a requested final duration."""
    # Video frame rounding and AAC priming are normally well under a second.
    # Keep the public result close enough to the selected 3/5-minute option
    # that an incomplete render is never presented as a full one.
    return max(1.0, min(3.0, float(target_duration) * 0.01))

# Scale to fit inside the frame, then pad to exact WxH so mismatched source
# resolutions never letterbox weirdly or shrink the final video.
_SCALE_PAD = (
    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
    f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
    f"setsar=1,fps={OUT_FPS},format=yuv420p"
)


async def _merge_segment(video_path: str, audio_path: str, output_path: str,
                         target_duration: float,
                         source_audio_duration: float | None = None) -> str:
    """Mux one video clip with its matching voiceover, normalized to spec.

    The recorded beat duration owns the timeline. Narration that is slightly
    long or short is tempo-fitted within the accepted tolerance, then padded
    for codec rounding; it never cuts the screen segment down to its length.
    """
    tempo_filter = ""
    if source_audio_duration is not None and source_audio_duration > 0:
        tempo = source_audio_duration / target_duration
        if abs(tempo - 1.0) > 0.01:
            tempo_filter = f",atempo={tempo:.5f}"
    cmd = [
        "ffmpeg", "-i", video_path, "-i", audio_path,
        "-filter_complex",
        f"[0:v]{_SCALE_PAD},setpts=PTS-STARTPTS[v];"
        f"[1:a]aresample={OUT_SR},aformat=channel_layouts=stereo,"
        f"asetpts=PTS-STARTPTS{tempo_filter},"
        f"apad=pad_dur={target_duration:.3f}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-t", f"{target_duration:.3f}",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Segment merge")
    return output_path


async def _merge_silent_segment(video_path: str, output_path: str) -> str:
    """Normalize a clip and attach a full-length silent stereo track.

    Used only when rebuilding legacy clips. Every concat input must carry a
    stereo AAC track or the concat demuxer drops audio for the whole video, so
    this gives an old silent segment a stream that matches its own duration.
    """
    dur = await get_duration(video_path)
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-f", "lavfi", "-t", str(dur),
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={OUT_SR}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", _SCALE_PAD,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-shortest",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Silent segment merge")
    return output_path


async def _render_title_card(title_card_path: str, output_path: str,
                             duration: float = TITLE_CARD_SECONDS) -> str:
    """Render the title card as a normalized clip WITH a silent audio track.

    A missing audio track on this single piece is enough to make the concat
    demuxer drop audio from the whole video, so we always attach silence.
    """
    cmd = [
        "ffmpeg",
        "-loop", "1", "-t", str(duration), "-i", title_card_path,
        "-f", "lavfi", "-t", str(duration),
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={OUT_SR}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", _SCALE_PAD,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Title card render")
    return output_path


async def normalize_clip(input_path: str, output_path: str) -> str:
    """Force an arbitrary clip to the canonical spec (video + stereo AAC).

    Used by the on-demand download endpoint: segment clips already stored on
    B2 (including those from older jobs) may not share a resolution/fps/audio
    layout, so we re-encode each one to spec before gluing. If a clip has no
    audio track, a silent stereo track is synthesized so concat never drops
    audio for the whole video.
    """
    # IMPORTANT: do not merge a tiny silent source into existing audio.  The
    # old implementation used a 0.1-second `anullsrc` with `amerge` and then
    # `-shortest`; ffmpeg correctly stopped each normalized download segment
    # at ~0.1s, so the on-demand glued download was drastically truncated.
    # When audio exists, simply normalize that source audio.  The no-audio
    # fallback below creates silence for the full clip duration instead.
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-map", "0:v:0", "-map", "0:a:0",
        "-vf", _SCALE_PAD,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-shortest",
        output_path, "-y",
    ]
    try:
        await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Clip normalize")
        return output_path
    except RuntimeError:
        # Clip likely had no audio stream at all — fall back to attaching a
        # full-length silent track instead of merging with the source audio.
        dur = await get_duration(input_path)
        cmd = [
            "ffmpeg",
            "-i", input_path,
            "-f", "lavfi", "-t", str(dur),
            "-i", f"anullsrc=channel_layout=stereo:sample_rate={OUT_SR}",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", _SCALE_PAD,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
            "-shortest",
            output_path, "-y",
        ]
        await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Clip normalize (silent)")
        return output_path


async def concat_segments(clip_paths: list[str], output_path: str,
                          job_id: str) -> str:
    """Concatenate already-normalized clips into one continuous MP4.

    Use ffmpeg's concat *filter* rather than its concat demuxer.  The filter
    creates one continuous audio/video timeline even when segment timestamps or
    AAC encoder delay differ slightly, which is common with independently
    rendered clips.  It also lets us verify that the resulting download still
    covers the duration of every input clip.
    """
    if not clip_paths:
        raise ValueError("Cannot concatenate an empty clip list")

    # ``get_duration`` is asynchronous, so resolve each probe before adding
    # them.  Passing an async generator directly to ``sum`` raises before
    # ffmpeg is invoked.
    expected_duration = sum([await get_duration(path) for path in clip_paths])
    input_args: list[str] = []
    filter_inputs = []
    for index, path in enumerate(clip_paths):
        input_args.extend(["-i", path])
        filter_inputs.append(f"[{index}:v:0][{index}:a:0]")
    concat_filter = "".join(filter_inputs) + f"concat=n={len(clip_paths)}:v=1:a=1[v][a]"

    cmd = [
        "ffmpeg", *input_args,
        "-filter_complex", concat_filter,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-movflags", "+faststart",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=CONCAT_TIMEOUT, label="Final concat")

    actual_duration = await get_duration(output_path)
    # Frame rounding and AAC priming can cost a few milliseconds per input;
    # anything larger means a clip was silently dropped or truncated.
    tolerance = max(0.35, len(clip_paths) * 0.08)
    if actual_duration + tolerance < expected_duration:
        raise RuntimeError(
            f"Final concat was truncated ({actual_duration:.2f}s rendered, "
            f"expected about {expected_duration:.2f}s)")
    return output_path


async def assemble(
    full_video_path: str,
    voiced_segments: list[dict],   # from generate_segment_voices, has audio_path
    title_card_path: Optional[str],
    job_id: str,
    target_duration: Optional[float] = None,
) -> dict:
    """
    Returns:
        {
          "final_video_path": str,
          "segment_clips": [
            {"segment_id": 1, "clip_path": str, "voice_path": str}, ...
          ]
        }
    """
    segment_clip_paths = []
    concat_entries = []
    voiced_segment_count = 0
    title_duration = 0.0

    # Title card as its own 3-second normalized (silent) segment.
    if title_card_path and os.path.exists(title_card_path):
        title_clip_path = f"/tmp/titleclip_{job_id}.mp4"
        try:
            await _render_title_card(title_card_path, title_clip_path)
            concat_entries.append(title_clip_path)
            title_duration = TITLE_CARD_SECONDS
        except (RuntimeError, TimeoutError):
            # A failed/hung title card is non-fatal — continue without it.
            pass

    # Recording normally reserves three seconds for the title card. If that
    # optional render is unavailable, preserve the selected duration by
    # holding the final visible product state for the missing title time.
    final_visual_extension = 0.0
    if target_duration is not None and voiced_segments:
        timed_durations = []
        for timed_segment in voiced_segments:
            start = timed_segment.get("start_time")
            end = timed_segment.get("end_time")
            if start is None or end is None:
                timed_durations = []
                break
            timed_durations.append(max(0.5, float(end) - float(start)))
        if timed_durations:
            final_visual_extension = max(
                0.0,
                float(target_duration) - title_duration - sum(timed_durations),
            )

    for seg_index, seg in enumerate(voiced_segments):
        seg_id = seg["segment_id"]
        start = seg.get("start_time")
        end = seg.get("end_time")
        audio_path = seg.get("audio_path")
        has_audio = bool(audio_path) and os.path.exists(audio_path)

        raw_clip_path = f"/tmp/rawclip_{job_id}_seg{seg_id}.mp4"

        if start is not None and end is not None:
            await split_clip(full_video_path, start, end, raw_clip_path)
            visual_duration = max(0.5, float(end) - float(start))
        else:
            # No timing info — use the full video as a fallback clip
            raw_clip_path = full_video_path
            visual_duration = await get_duration(raw_clip_path)

        if seg_index == len(voiced_segments) - 1:
            visual_duration += final_visual_extension

        padded_clip_path = f"/tmp/paddedclip_{job_id}_seg{seg_id}.mp4"
        merged_path = f"/tmp/mergedseg_{job_id}_seg{seg_id}.mp4"

        if has_audio:
            # The recorded/planned screen timeline is authoritative. A voice
            # track must match it closely enough to remain naturally synced.
            audio_duration = await get_duration(audio_path)
            min_audio_duration = visual_duration * (1.0 - VOICE_DURATION_TOLERANCE)
            max_audio_duration = visual_duration * (1.0 + VOICE_DURATION_TOLERANCE)
            if not min_audio_duration <= audio_duration <= max_audio_duration:
                raise RuntimeError(
                    f"Voiceover for segment {seg_id} is {audio_duration:.1f}s, "
                    f"but its planned screen time is {visual_duration:.1f}s. "
                    "Refusing to publish a mismatched narration timeline.")
            await fit_video_to_duration(raw_clip_path, visual_duration, padded_clip_path)
            await _merge_segment(
                padded_clip_path, audio_path, merged_path, visual_duration,
                audio_duration)
            voiced_segment_count += 1
        else:
            # A fresh pipeline run must never turn a missing voice asset into
            # a successful silent download. ``target_duration`` is supplied
            # only by the current generation pipeline; the legacy branch is
            # kept for old, explicitly rebuilt artifacts.
            if target_duration is not None:
                raise RuntimeError(
                    f"Segment {seg_id} has no validated narration asset. "
                    "Refusing to publish a silent video.")
            await fit_video_to_duration(raw_clip_path, visual_duration, padded_clip_path)
            await _merge_silent_segment(padded_clip_path, merged_path)

        segment_clip_paths.append({
            "segment_id": seg_id,
            "clip_path": padded_clip_path,
            "voice_path": audio_path,
            "merged_path": merged_path,
        })
        concat_entries.append(merged_path)

    final_video_path = f"/tmp/final_{job_id}.mp4"
    await concat_segments(concat_entries, final_video_path, job_id)
    actual_duration = await get_duration(final_video_path)
    if target_duration is not None:
        if (not math.isfinite(actual_duration) or
                abs(actual_duration - float(target_duration)) >
                duration_tolerance(float(target_duration))):
            raise RuntimeError(
                f"Final video duration is {actual_duration:.1f}s; requested "
                f"{float(target_duration):.1f}s. Refusing to publish an "
                "incomplete demo.")

    return {
        "final_video_path": final_video_path,
        "segment_clips": segment_clip_paths,
        "actual_duration_seconds": round(actual_duration, 2),
        "voiced_segment_count": voiced_segment_count,
        "assembly_contract_version": ASSEMBLY_CONTRACT_VERSION,
        "requested_duration_seconds": (
            float(target_duration) if target_duration is not None else None
        ),
    }
