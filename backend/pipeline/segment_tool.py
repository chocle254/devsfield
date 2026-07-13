"""
Shared FFmpeg/ffprobe helpers for segment-based video editing.

Every subprocess call is wrapped with an asyncio timeout. Without this, a
hung ffmpeg/ffprobe process (for example on a malformed or not-yet-flushed
Playwright recording) would block the whole pipeline forever with no error,
no crash and no progress. With the timeout, a hang becomes a caught, logged
failure that fails the job cleanly instead of stalling silently.
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# Timeouts (seconds). ffprobe is a quick metadata read; ffmpeg transcodes
# can legitimately take a while, so they get a larger budget.
FFPROBE_TIMEOUT = 30
FFMPEG_TIMEOUT = 180


async def run_subprocess(cmd: list[str], *, timeout: float, label: str) -> tuple[bytes, bytes]:
    """
    Run a subprocess with a hard timeout.

    Returns (stdout, stderr) on success. Raises RuntimeError on a non-zero
    exit code, and TimeoutError (after killing the process) if it hangs past
    `timeout` seconds.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error("%s timed out after %ss — killing process", label, timeout)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        # Reap the killed process so we don't leak a zombie / pending transport.
        try:
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        raise TimeoutError(f"{label} timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(f"{label} failed: {stderr.decode(errors='replace')}")

    return stdout, stderr


async def get_duration(file_path: str) -> float:
    """Return duration in seconds using ffprobe."""
    stdout, _ = await run_subprocess(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", file_path,
        ],
        timeout=FFPROBE_TIMEOUT,
        label=f"ffprobe({file_path})",
    )
    data = json.loads(stdout.decode())
    return float(data["format"]["duration"])


async def split_clip(full_video_path: str, start_time: float, end_time: float,
                      output_path: str) -> str:
    """Cut a segment out of the full recording using ffmpeg -ss/-to."""
    cmd = [
        "ffmpeg", "-i", full_video_path,
        "-ss", str(start_time), "-to", str(end_time),
        "-c:v", "libx264", "-an",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Clip split")
    return output_path


async def pad_video_to_duration(video_path: str, target_duration: float,
                                 output_path: str) -> str:
    """Freeze the last frame to stretch a video clip to target_duration."""
    current = await get_duration(video_path)
    pad_seconds = max(0.0, target_duration - current)

    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"tpad=stop_mode=clone:stop_duration={pad_seconds}",
        "-c:v", "libx264",
        output_path, "-y",
    ]
    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Video padding")
    return output_path


async def fit_video_to_duration(video_path: str, target_duration: float,
                                output_path: str) -> str:
    """
    Make a clip exactly target_duration seconds long, choosing the least
    destructive strategy:
    - shorter than target  -> freeze the last frame (pad)
    - up to 30% too long   -> speed up slightly (imperceptible on screen
                              recordings, keeps every action visible)
    - way too long         -> trim the tail
    """
    current = await get_duration(video_path)

    if current <= target_duration + 0.05:
        return await pad_video_to_duration(video_path, target_duration,
                                           output_path)

    ratio = current / target_duration
    if ratio <= 1.3:
        # Gentle speed-up: setpts compresses timestamps by 1/ratio
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"setpts=PTS/{ratio:.5f}",
            "-c:v", "libx264", "-an",
            output_path, "-y",
        ]
    else:
        # Too much dead time — keep the first target_duration seconds
        cmd = [
            "ffmpeg", "-i", video_path,
            "-t", str(target_duration),
            "-c:v", "libx264", "-an",
            output_path, "-y",
        ]

    await run_subprocess(cmd, timeout=FFMPEG_TIMEOUT, label="Video fitting")
    return output_path
