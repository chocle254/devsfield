"""
Assembles the final video from segments: splits the full recording into
per-segment clips, pads each to match its voiceover's duration, merges
audio+video per segment, then concatenates everything with the title card.

Every ffmpeg call goes through segment_tool.run_subprocess, which enforces a
hard timeout so a hung encode fails the job cleanly instead of stalling the
whole pipeline forever.

IMPORTANT — why the final video used to be short / silent / smaller than the
segments: the concat *demuxer* (`-f concat`) does NOT re-encode or reconcile
streams. If the pieces disagree on resolution, framerate, pixel format,
timebase or audio layout — or if any piece is missing an audio track (the
title card had none) — the muxed output silently drops audio and can stop at
the first stream boundary, producing a tiny, voiceless, truncated file.

The fix is to normalize EVERY piece to one canonical spec (resolution, fps,
pixel format, SAR, and a real stereo AAC audio track — silent for the title
card) before concatenating. `concat_segments` is shared with the on-demand
download endpoint so downloads glue the exact same way.
"""
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

# Scale to fit inside the frame, then pad to exact WxH so mismatched source
# resolutions never letterbox weirdly or shrink the final video.
_SCALE_PAD = (
    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
    f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
    f"setsar=1,fps={OUT_FPS},format=yuv420p"
)


async def _merge_segment(video_path: str, audio_path: str, output_path: str) -> str:
    """Mux one video clip with its matching voiceover, normalized to spec.

    The video is scaled/padded to the canonical frame and the audio is
    re-encoded to stereo AAC so every merged segment is byte-compatible for
    concatenation.
    """
    cmd = [
        "ffmpeg", "-i", video_path, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", _SCALE_PAD,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-shortest",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Segment merge")
    return output_path


async def _merge_silent_segment(video_path: str, output_path: str) -> str:
    """Normalize a clip and attach a full-length silent stereo track.

    Used when a segment has no voiceover (TTS was non-fatal and produced no
    audio). Every concat input must carry a stereo AAC track or the concat
    demuxer drops audio for the whole video, so we synthesize silence that
    matches the clip's own duration.
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
                             duration: float = 3.0) -> str:
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
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-f", "lavfi", "-t", "0.1",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={OUT_SR}",
        "-filter_complex",
        f"[0:v]{_SCALE_PAD}[v];"
        f"[0:a][1:a]amerge=inputs=2,aresample={OUT_SR},pan=stereo|c0<c0|c1<c1[a]",
        "-map", "[v]", "-map", "[a]",
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

    Uses the concat demuxer with re-encode as a safety net. Because every input
    was produced by `_merge_segment` / `_render_title_card` they share the same
    resolution, fps, pixel format and stereo AAC audio, so the result keeps the
    full length and the voiceover of every segment.
    """
    concat_list_path = f"/tmp/concat_{job_id}.txt"
    with open(concat_list_path, "w") as f:
        for path in clip_paths:
            # Escape single quotes for the concat list format.
            safe = path.replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-movflags", "+faststart",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=CONCAT_TIMEOUT, label="Final concat")
    return output_path


async def assemble(
    full_video_path: str,
    voiced_segments: list[dict],   # from generate_segment_voices, has audio_path
    title_card_path: Optional[str],
    job_id: str,
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

    # Title card as its own 3-second normalized (silent) segment.
    if title_card_path and os.path.exists(title_card_path):
        title_clip_path = f"/tmp/titleclip_{job_id}.mp4"
        try:
            await _render_title_card(title_card_path, title_clip_path)
            concat_entries.append(title_clip_path)
        except (RuntimeError, TimeoutError):
            # A failed/hung title card is non-fatal — continue without it.
            pass

    for seg in voiced_segments:
        seg_id = seg["segment_id"]
        start = seg.get("start_time")
        end = seg.get("end_time")
        audio_path = seg.get("audio_path")
        has_audio = bool(audio_path) and os.path.exists(audio_path)

        raw_clip_path = f"/tmp/rawclip_{job_id}_seg{seg_id}.mp4"

        if start is not None and end is not None:
            await split_clip(full_video_path, start, end, raw_clip_path)
        else:
            # No timing info — use the full video as a fallback clip
            raw_clip_path = full_video_path

        padded_clip_path = f"/tmp/paddedclip_{job_id}_seg{seg_id}.mp4"
        merged_path = f"/tmp/mergedseg_{job_id}_seg{seg_id}.mp4"

        if has_audio:
            # Voiceover drives the segment length so audio and video stay synced.
            target_duration = await get_duration(audio_path)
            await fit_video_to_duration(raw_clip_path, target_duration, padded_clip_path)
            await _merge_segment(padded_clip_path, audio_path, merged_path)
        else:
            # No voiceover for this segment (TTS is non-fatal). Keep the segment
            # at its recorded length (or the clip's own length) and attach a
            # silent track so the concat step still produces continuous audio.
            if start is not None and end is not None:
                target_duration = max(0.5, float(end) - float(start))
            else:
                target_duration = await get_duration(raw_clip_path)
            await fit_video_to_duration(raw_clip_path, target_duration, padded_clip_path)
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

    return {
        "final_video_path": final_video_path,
        "segment_clips": segment_clip_paths,
    }
