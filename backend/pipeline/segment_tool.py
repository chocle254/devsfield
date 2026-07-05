"""
Shared FFmpeg/ffprobe helpers for segment-based video editing.
"""
import asyncio
import json


async def get_duration(file_path: str) -> float:
    """Return duration in seconds using ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", file_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode()}")
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
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Clip split failed: {stderr.decode()}")
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
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Video padding failed: {stderr.decode()}")
    return output_path
