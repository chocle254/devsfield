"""
Assembles the final video from segments: splits the full recording into
per-segment clips, pads each to match its voiceover's duration, merges
audio+video per segment, then concatenates everything with the title card.
"""
import asyncio
import os
from typing import Optional

from pipeline.segment_tool import get_duration, split_clip, pad_video_to_duration


async def _merge_segment(video_path: str, audio_path: str, output_path: str) -> str:
    """Mux one video clip with its matching audio clip."""
    cmd = [
        "ffmpeg", "-i", video_path, "-i", audio_path,
        "-c:v", "libx264", "-c:a", "aac",
        "-map", "0:v:0", "-map", "1:a:0",
        output_path, "-y",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Segment merge failed: {stderr.decode()}")
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
    concat_list_path = f"/tmp/concat_{job_id}.txt"
    concat_entries = []

    # Title card as its own 3-second segment, no audio (silent)
    if title_card_path and os.path.exists(title_card_path):
        title_clip_path = f"/tmp/titleclip_{job_id}.mp4"
        cmd = [
            "ffmpeg", "-loop", "1", "-t", "3", "-i", title_card_path,
            "-vf", "scale=1280:720,setsar=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            title_clip_path, "-y",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        if proc.returncode == 0:
            concat_entries.append(title_clip_path)

    for seg in voiced_segments:
        seg_id = seg["segment_id"]
        start = seg.get("start_time")
        end = seg.get("end_time")
        audio_path = seg["audio_path"]

        raw_clip_path = f"/tmp/rawclip_{job_id}_seg{seg_id}.mp4"

        if start is not None and end is not None:
            await split_clip(full_video_path, start, end, raw_clip_path)
        else:
            # No timing info — use the full video as a fallback clip
            raw_clip_path = full_video_path

        audio_duration = await get_duration(audio_path)
        padded_clip_path = f"/tmp/paddedclip_{job_id}_seg{seg_id}.mp4"
        await pad_video_to_duration(raw_clip_path, audio_duration, padded_clip_path)

        merged_path = f"/tmp/mergedseg_{job_id}_seg{seg_id}.mp4"
        await _merge_segment(padded_clip_path, audio_path, merged_path)

        segment_clip_paths.append({
            "segment_id": seg_id,
            "clip_path": padded_clip_path,
            "voice_path": audio_path,
            "merged_path": merged_path,
        })
        concat_entries.append(merged_path)

    # Write concat list for ffmpeg concat demuxer
    with open(concat_list_path, "w") as f:
        for path in concat_entries:
            f.write(f"file '{path}'\n")

    final_video_path = f"/tmp/final_{job_id}.mp4"
    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-c:v", "libx264", "-c:a", "aac",
        "-movflags", "+faststart",
        final_video_path, "-y",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Final concat failed: {stderr.decode()}")

    return {
        "final_video_path": final_video_path,
        "segment_clips": segment_clip_paths,
    }
