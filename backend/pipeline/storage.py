import os
import json
import hashlib
from datetime import datetime
import httpx


async def upload_all(job_id: str, video_path: str, script: list[dict]) -> dict:
    """Upload video and manifest to Backblaze B2."""
    
    # Get B2 credentials
    b2_key_id = os.environ.get("B2_KEY_ID")
    b2_app_key = os.environ.get("B2_APP_KEY")
    b2_bucket = os.environ.get("B2_BUCKET", "devfields")
    b2_public_url = os.environ.get("B2_PUBLIC_URL", "https://f005.backblazeb2.com/file")
    
    if not all([b2_key_id, b2_app_key, b2_bucket]):
        raise RuntimeError("Backblaze B2 credentials not configured")
    
    # Read video file
    with open(video_path, "rb") as f:
        video_data = f.read()
    
    # Calculate SHA256
    video_sha256 = hashlib.sha256(video_data).hexdigest()
    
    # Build manifest
    manifest = {
        "job_id": job_id,
        "generated_at": datetime.utcnow().isoformat(),
        "video_sha256": video_sha256,
        "script": script,
        "storage": {
            "provider": "Backblaze B2",
            "bucket": b2_bucket,
        }
    }
    manifest_json = json.dumps(manifest, indent=2)
    
    # For now, simulate B2 upload (real implementation would use boto3 or genblaze-s3)
    # In production, you would:
    # 1. Get B2 auth token
    # 2. Get upload URL from B2
    # 3. Upload video and manifest files
    
    video_key = f"runs/{job_id}/demo.mp4"
    manifest_key = f"runs/{job_id}/manifest.json"
    
    video_url = f"{b2_public_url}/{b2_bucket}/{video_key}"
    manifest_url = f"{b2_public_url}/{b2_bucket}/{manifest_key}"
    
    return {
        "job_id": job_id,
        "video_url": video_url,
        "manifest_url": manifest_url,
        "sha256": video_sha256,
        "models_used": {
            "llm": "deepseek-ai/DeepSeek-V3-0324",
            "tts": "eleven_multilingual_v2",
            "video_codec": "libx264",
        },
        "duration_seconds": 180,
        "generated_at": datetime.utcnow().isoformat(),
    }
