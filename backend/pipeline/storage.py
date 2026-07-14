"""
Uploads the final video AND every individual segment (clip + voice) to
Backblaze B2, plus a segment manifest that makes future editing possible.
"""
import asyncio
import hashlib
import json
import os
from datetime import datetime

from genblaze_core import ObjectStorageSink, KeyStrategy
from genblaze_s3 import S3StorageBackend


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def make_b2_backend() -> S3StorageBackend:
    """Build a Backblaze B2 backend from the environment.

    The region MUST be passed explicitly: buckets in regions like
    ``us-east-005`` reject cross-region requests with a 403 instead of a
    301 redirect, so genblaze's auto-detect can't recover — it never sees a
    region header. We default to ``us-east-005`` (this project's bucket
    region) and let ``$B2_REGION`` override it. This is the single place
    both final uploads and resume checkpoints construct their backend, so
    the region fix applies everywhere at once.
    """
    b2_bucket = os.environ.get("B2_BUCKET")
    if not b2_bucket:
        raise ValueError("B2_BUCKET not set in environment")
    b2_region = os.environ.get("B2_REGION", "us-east-005")
    b2_public_url = os.environ.get("B2_PUBLIC_URL", "")
    return S3StorageBackend.for_backblaze(
        b2_bucket, region=b2_region, public_url_base=b2_public_url)


async def upload_all(job_id: str, final_video_path: str,
                      segment_clips: list[dict]) -> dict:
    b2_public_url = os.environ.get("B2_PUBLIC_URL", "")
    backend = make_b2_backend()

    # Upload final video
    with open(final_video_path, "rb") as f:
        video_data = f.read()
    video_key = f"jobs/{job_id}/final_video.mp4"
    video_url = await asyncio.to_thread(
        backend.put, video_key, video_data, content_type="video/mp4")

    # Upload each segment's clip + voice individually — this is what
    # enables editing a single segment later without touching the rest
    segment_manifest = []
    for seg in segment_clips:
        seg_id = seg["segment_id"]

        with open(seg["merged_path"], "rb") as f:
            clip_data = f.read()
        clip_key = f"jobs/{job_id}/segments/{seg_id}/clip.mp4"
        clip_url = await asyncio.to_thread(
            backend.put, clip_key, clip_data, content_type="video/mp4")

        with open(seg["voice_path"], "rb") as f:
            voice_data = f.read()
        voice_key = f"jobs/{job_id}/segments/{seg_id}/voice.mp3"
        voice_url = await asyncio.to_thread(
            backend.put, voice_key, voice_data, content_type="audio/mpeg")

        segment_manifest.append({
            "segment_id": seg_id,
            "clip_key": clip_key,
            "clip_url": clip_url or f"{b2_public_url}/{clip_key}",
            "voice_key": voice_key,
            "voice_url": voice_url or f"{b2_public_url}/{voice_key}",
        })

    # Upload segment manifest — the foundation for chat-based editing later
    segments_json = json.dumps(segment_manifest, indent=2).encode()
    segments_key = f"jobs/{job_id}/segments_manifest.json"
    segments_url = await asyncio.to_thread(
        backend.put, segments_key, segments_json, content_type="application/json")

    # Provenance manifest
    manifest = {
        "job_id": job_id,
        "video_key": video_key,
        "segments_key": segments_key,
        "sha256": _sha256_file(final_video_path),
        "models_used": {
            "llm": "deepseek-ai/DeepSeek-V3-0324 via GMI Cloud",
            "navigation": "deepseek-ai/DeepSeek-V3-0324 via GMI Cloud",
            "tts": "elevenlabs-tts-v3 via GMI Cloud (Genblaze)",
            "image": "seedream-5.0-lite via GMI Cloud (Genblaze)",
            "compositor": "FFmpeg",
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    manifest_json = json.dumps(manifest, indent=2).encode()
    manifest_key = f"jobs/{job_id}/manifest.json"
    manifest_url = await asyncio.to_thread(
        backend.put, manifest_key, manifest_json, content_type="application/json")

    backend.close()

    return {
        "video_url": video_url or f"{b2_public_url}/{video_key}",
        "manifest_url": manifest_url or f"{b2_public_url}/{manifest_key}",
        "segments_url": segments_url or f"{b2_public_url}/{segments_key}",
        "segments": segment_manifest,
        "sha256": manifest["sha256"],
        "models_used": manifest["models_used"],
        "generated_at": manifest["generated_at"],
    }
