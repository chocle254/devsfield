"""
Storage and upload to Backblaze B2
"""
import asyncio
import json
import os
from datetime import datetime

from genblaze_core import ObjectStorageSink, KeyStrategy
from genblaze_s3 import S3StorageBackend


async def upload_all(job_id: str, video_path: str, script: list[dict]) -> dict:
    """
    Upload video, script, and manifest to Backblaze B2.
    
    Args:
        job_id: Unique job identifier
        video_path: Path to the final video file
        script: The script data structure
        
    Returns:
        Dict with upload results and URLs
    """
    b2_bucket = os.environ.get("B2_BUCKET")
    b2_public_url = os.environ.get("B2_PUBLIC_URL", "")
    
    if not b2_bucket:
        raise ValueError("B2_BUCKET not set in environment")
    
    # Initialize Backblaze backend
    backend = S3StorageBackend.for_backblaze(
        b2_bucket,
        public_url_base=b2_public_url,
    )
    
    sink = ObjectStorageSink(
        backend,
        prefix=f"jobs/{job_id}",
        key_strategy=KeyStrategy.HIERARCHICAL,
    )
    
    # Upload video
    with open(video_path, "rb") as f:
        video_data = f.read()
    
    video_key = f"jobs/{job_id}/final_video.mp4"
    video_url = await asyncio.to_thread(
        backend.put,
        video_key,
        video_data,
        content_type="video/mp4"
    )
    
    # Upload script as JSON
    script_json = json.dumps(script, indent=2).encode()
    script_key = f"jobs/{job_id}/script.json"
    script_url = await asyncio.to_thread(
        backend.put,
        script_key,
        script_json,
        content_type="application/json"
    )
    
    # Upload manifest
    manifest = {
        "job_id": job_id,
        "video_key": video_key,
        "script_key": script_key,
        "models_used": {
            "llm": "deepseek-ai/DeepSeek-V3-0324",
            "tts": "ElevenLabs-TTS-v3 via GMI Cloud",
            "compositor": "FFmpeg",
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    manifest_json = json.dumps(manifest, indent=2).encode()
    manifest_key = f"jobs/{job_id}/manifest.json"
    manifest_url = await asyncio.to_thread(
        backend.put,
        manifest_key,
        manifest_json,
        content_type="application/json"
    )
    
    backend.close()
    
    return {
        "video_url": video_url or f"{b2_public_url}/{video_key}",
        "manifest_url": manifest_url or f"{b2_public_url}/{manifest_key}",
        "script_url": script_url or f"{b2_public_url}/{script_key}",
        "models_used": manifest["models_used"],
        "generated_at": manifest["generated_at"],
    }
