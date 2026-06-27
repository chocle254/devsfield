import os
import asyncio
from typing import Optional


async def assemble(
    video_path: str,
    audio_path: str,
    title_card_path: Optional[str],
    job_id: str
) -> str:
    """Assemble the final video using FFmpeg."""
    
    output_path = f"/tmp/final_{job_id}.mp4"
    
    # Build FFmpeg command
    if title_card_path and os.path.exists(title_card_path):
        # With title card: loop image for 3 seconds, then concat with video
        cmd = [
            "ffmpeg",
            "-loop", "1", "-t", "3", "-i", title_card_path,
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            "[0:v]scale=1280:720,setsar=1[tc];[1:v]scale=1280:720,setsar=1[sv];[tc][sv]concat=n=2:v=1[v];[2:a]adelay=3000|3000[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            output_path, "-y"
        ]
    else:
        # Without title card: just mux video and audio
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            "-movflags", "+faststart",
            output_path, "-y"
        ]
    
    # Run FFmpeg
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed: {stderr.decode()}"
        )
    
    return output_path
