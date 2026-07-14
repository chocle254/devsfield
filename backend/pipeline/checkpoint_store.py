"""
Durable resume store on Backblaze B2 (S3-compatible).

When a job fails, we snapshot everything needed to resume it — the original
request, which steps already completed, each step's checkpointed output, and
every intermediate artifact on disk (recording, voiceovers, title card,
assembled clips) — to B2. That way a retry can pick up from the exact step
that broke EVEN AFTER a redeploy, when the in-memory job dict and /tmp are both
wiped.

This uses boto3 directly (already a dependency via genblaze-s3) with the same
B2 credentials the rest of the app uses, so no new integration is required.
"""
import asyncio
import json
import logging
import os
import re
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_STATE_KEY = "jobs/{job_id}/_resume_state.json"
_ARTIFACT_KEY = "jobs/{job_id}/_resume_artifacts/{name}"


def is_enabled() -> bool:
    """Durable resume works only when B2 credentials are configured."""
    return bool(
        os.environ.get("B2_BUCKET")
        and os.environ.get("B2_KEY_ID")
        and os.environ.get("B2_APP_KEY")
    )


def _endpoint() -> str:
    """Resolve the B2 S3 endpoint.

    Prefer an explicit B2_S3_ENDPOINT. Otherwise derive it from B2_PUBLIC_URL
    (e.g. https://f005.backblazeb2.com/... -> https://s3.us-east-005.backblazeb2.com).
    """
    explicit = os.environ.get("B2_S3_ENDPOINT")
    if explicit:
        return explicit.rstrip("/")
    public = os.environ.get("B2_PUBLIC_URL", "")
    m = re.search(r"f(\d+)\.backblazeb2\.com", public)
    cluster = m.group(1) if m else "005"
    return f"https://s3.us-east-{cluster}.backblazeb2.com"


def _region(endpoint: str) -> str:
    m = re.search(r"s3\.([^.]+)\.backblazeb2\.com", endpoint)
    return m.group(1) if m else "us-east-005"


def _client():
    endpoint = _endpoint()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
        region_name=_region(endpoint),
        config=Config(
            signature_version="s3v4",
            # Backblaze rejects the newer AWS default CRC checksums; only send
            # them when the operation actually requires it.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def _bucket() -> str:
    return os.environ["B2_BUCKET"]


# --- sync workers (run via asyncio.to_thread) -------------------------------

def _put_json_sync(job_id: str, state: dict) -> None:
    client = _client()
    client.put_object(
        Bucket=_bucket(),
        Key=_STATE_KEY.format(job_id=job_id),
        Body=json.dumps(state).encode("utf-8"),
        ContentType="application/json",
    )


def _get_json_sync(job_id: str) -> Optional[dict]:
    client = _client()
    try:
        obj = client.get_object(
            Bucket=_bucket(), Key=_STATE_KEY.format(job_id=job_id)
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    return json.loads(obj["Body"].read().decode("utf-8"))


def _put_file_sync(job_id: str, name: str, local_path: str) -> str:
    client = _client()
    key = _ARTIFACT_KEY.format(job_id=job_id, name=name)
    with open(local_path, "rb") as f:
        client.put_object(Bucket=_bucket(), Key=key, Body=f.read())
    return key


def _get_file_sync(key: str, dest_path: str) -> None:
    client = _client()
    obj = client.get_object(Bucket=_bucket(), Key=key)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(obj["Body"].read())


# --- async API --------------------------------------------------------------

async def save_state(job_id: str, state: dict) -> bool:
    if not is_enabled():
        return False
    try:
        await asyncio.to_thread(_put_json_sync, job_id, state)
        return True
    except Exception as e:  # never let persistence crash the pipeline
        logger.warning("Failed to save resume state for %s: %s", job_id, e)
        return False


async def load_state(job_id: str) -> Optional[dict]:
    if not is_enabled():
        return None
    try:
        return await asyncio.to_thread(_get_json_sync, job_id)
    except Exception as e:
        logger.warning("Failed to load resume state for %s: %s", job_id, e)
        return None


async def upload_artifact(job_id: str, name: str, local_path: str) -> Optional[str]:
    if not is_enabled():
        return None
    try:
        return await asyncio.to_thread(_put_file_sync, job_id, name, local_path)
    except Exception as e:
        logger.warning("Failed to upload artifact %s for %s: %s", name, job_id, e)
        return None


async def download_artifact(key: str, dest_path: str) -> bool:
    if not is_enabled():
        return False
    try:
        await asyncio.to_thread(_get_file_sync, key, dest_path)
        return True
    except Exception as e:
        logger.warning("Failed to download artifact %s: %s", key, e)
        return False
