"""Assemble per-segment clips into one continuous MP4.

The previous version concatenated clips of differing resolutions/fps/audio
layouts (and a silent title card with no audio stream at all). The FFmpeg
concat demuxer silently drops audio and truncates output when streams don't
match — that is what produced the short, silent, "smaller than the segments"
final video. Every clip is now normalized to one canonical spec (identical
resolution, fps, pixel format, and a stereo AAC track) before concatenation,
and the title card gets a synthesized silent audio track.
"""

import os

from pipeline.segment_tool import (
    run_subprocess,
    get_duration,
    FFMPEG_TIMEOUT,
)

# Canonical output spec. Every clip is forced to this before concat so the
# concat demuxer never drops audio or truncates on a stream mismatch.
OUT_W = 1280
OUT_H = 720
OUT_FPS = 30
OUT_SR = 44100  # audio sample rate

# Scale to fit inside the frame, then pad to exact size (keeps aspect ratio,
# no cropping) and normalize fps + SAR.
_SCALE_PAD = (
    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
    f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
    f"setsar=1,fps={OUT_FPS},format=yuv420p"
)


async def make_title_card(text: str, duration: float, output_path: str) -> str:
    """Render a title card with a synthesized silent stereo audio track.

    A title card with no audio stream breaks concat for the whole video, so we
    always attach silence here.
    """
    safe = (text or "").replace(":", r"\:").replace("'", r"\'")
    cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", f"color=c=black:s={OUT_W}x{OUT_H}:r={OUT_FPS}:d={duration}",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate={OUT_SR}",
        "-vf",
        (
            f"drawtext=text='{safe}':fontcolor=white:fontsize=48:"
            f"x=(w-text_w)/2:y=(h-text_h)/2"
        ),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-t", str(duration),
        "-shortest",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Title card")
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

    Uses the concat demuxer with stream copy — safe here because every input
    was normalized to the exact same spec by make_title_card / normalize_clip /
    render_segment_clip.
    """
    if not clip_paths:
        raise ValueError("No clips to concatenate")

    list_path = f"/tmp/concat_{job_id}.txt"
    with open(list_path, "w") as f:
        for p in clip_paths:
            # concat demuxer needs escaped single quotes around each path
            escaped = p.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path, "-y",
    ]
    try:
        await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Concat segments")
    except RuntimeError:
        # Stream copy can fail if timestamps are non-monotonic; re-encode.
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
            "-movflags", "+faststart",
            output_path, "-y",
        ]
        await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Concat segments (re-encode)")
    finally:
        try:
            if os.path.isfile(list_path):
                os.remove(list_path)
        except OSError:
            pass
    return output_path


async def render_segment_clip(video_source: str, audio_path: str,
                              output_path: str) -> str:
    """Render one segment clip: screen recording + its voiceover, to spec.

    The clip length follows the voiceover so the narration is never cut off,
    and the video is normalized to the canonical spec so it concatenates
    cleanly with every other clip.
    """
    audio_dur = await get_duration(audio_path)
    cmd = [
        "ffmpeg",
        "-i", video_source,
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", _SCALE_PAD,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", str(OUT_SR), "-ac", "2",
        "-t", str(audio_dur),
        "-shortest",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Segment clip")
    return output_path


async def assemble(segment_clips: list[str], job_id: str,
                   output_path: str = None) -> str:
    """Assemble the final video from ordered, normalized segment clips."""
    if output_path is None:
        output_path = f"/tmp/final_{job_id}.mp4"
    await concat_segments(segment_clips, output_path, job_id)
    return output_path
