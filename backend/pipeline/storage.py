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


# Presigned URLs are minted at read time (see resolve_result_urls). B2 caps a
# presigned GET at 7 days, so we sign for the max — but because every /result
# call re-signs, the effective lifetime is unbounded for anyone actively using
# the app or a share link.
_PRESIGN_TTL_SEC = 7 * 24 * 3600


def _url_for(backend, key: str) -> str:
    """Return a browser-loadable URL for a stored object key.

    Since genblaze 0.3.0 ``backend.put`` returns the *key*, not a URL, so we
    must derive the URL ourselves. When a public CDN base (``B2_PUBLIC_URL``)
    is configured we hand out a credential-free durable URL; otherwise the
    bucket is private and we mint a presigned GET so the ``<video>`` element
    can actually fetch the file instead of 404ing on a bare key.
    """
    if os.environ.get("B2_PUBLIC_URL"):
        return backend.get_durable_url(key)
    return backend.presigned_get_url(key, expires_in=_PRESIGN_TTL_SEC)


async def resolve_result_urls(result: dict) -> dict:
    """Re-mint fresh, loadable URLs for a stored result from its keys.

    Results persist only the stable object *keys*; the actual URLs (which may
    be short-lived presigned links) are regenerated on every read so the video
    and assets never go stale. Best-effort: if B2 is unreachable we return the
    result untouched so the rest of the page still renders.
    """
    if not result:
        return result
    try:
        backend = make_b2_backend()
    except Exception:
        return result
    try:
        out = dict(result)
        if result.get("video_key"):
            out["video_url"] = await asyncio.to_thread(_url_for, backend, result["video_key"])
        if result.get("manifest_key"):
            out["manifest_url"] = await asyncio.to_thread(_url_for, backend, result["manifest_key"])
        if result.get("segments_key"):
            out["segments_url"] = await asyncio.to_thread(_url_for, backend, result["segments_key"])
        segs = result.get("segments")
        if isinstance(segs, list):
            resolved = []
            for seg in segs:
                s = dict(seg)
                if seg.get("clip_key"):
                    s["clip_url"] = await asyncio.to_thread(_url_for, backend, seg["clip_key"])
                if seg.get("voice_key"):
                    s["voice_url"] = await asyncio.to_thread(_url_for, backend, seg["voice_key"])
                resolved.append(s)
            out["segments"] = resolved
        return out
    except Exception:
        return result
    finally:
        try:
            backend.close()
        except Exception:
            pass


def _repo_name(github_url: str) -> str:
    """Derive a friendly repo name (owner/repo → repo) for library display."""
    if not github_url:
        return ""
    slug = github_url.rstrip("/").split("github.com/")[-1]
    slug = slug.removesuffix(".git")
    parts = [p for p in slug.split("/") if p]
    return parts[-1] if parts else slug


async def upload_all(job_id: str, final_video_path: str,
                      segment_clips: list[dict],
                      request=None, duration_seconds: int = None) -> dict:
    backend = make_b2_backend()

    # Upload final video
    with open(final_video_path, "rb") as f:
        video_data = f.read()
    video_key = f"jobs/{job_id}/final_video.mp4"
    await asyncio.to_thread(
        backend.put, video_key, video_data, content_type="video/mp4")
    video_url = await asyncio.to_thread(_url_for, backend, video_key)

    # Upload each segment's clip + voice individually — this is what
    # enables editing a single segment later without touching the rest
    segment_manifest = []
    for seg in segment_clips:
        seg_id = seg["segment_id"]

        with open(seg["merged_path"], "rb") as f:
            clip_data = f.read()
        clip_key = f"jobs/{job_id}/segments/{seg_id}/clip.mp4"
        await asyncio.to_thread(
            backend.put, clip_key, clip_data, content_type="video/mp4")
        clip_url = await asyncio.to_thread(_url_for, backend, clip_key)

        with open(seg["voice_path"], "rb") as f:
            voice_data = f.read()
        voice_key = f"jobs/{job_id}/segments/{seg_id}/voice.mp3"
        await asyncio.to_thread(
            backend.put, voice_key, voice_data, content_type="audio/mpeg")
        voice_url = await asyncio.to_thread(_url_for, backend, voice_key)

        segment_manifest.append({
            "segment_id": seg_id,
            "clip_key": clip_key,
            "clip_url": clip_url,
            "voice_key": voice_key,
            "voice_url": voice_url,
        })

    # Upload segment manifest — the foundation for chat-based editing later
    segments_json = json.dumps(segment_manifest, indent=2).encode()
    segments_key = f"jobs/{job_id}/segments_manifest.json"
    await asyncio.to_thread(
        backend.put, segments_key, segments_json, content_type="application/json")
    segments_url = await asyncio.to_thread(_url_for, backend, segments_key)

    # Library metadata pulled from the originating request. Stored in the
    # manifest so the /library listing can label each video (repo, app URL,
    # duration, tone) without any in-memory job state — it survives restarts.
    github_url = getattr(request, "github_url", "") if request else ""
    app_url = getattr(request, "app_url", "") if request else ""
    tone = getattr(request, "tone", None) if request else None
    if duration_seconds is None and request is not None:
        duration_seconds = getattr(request, "video_length", None)

    # Provenance manifest
    manifest = {
        "job_id": job_id,
        "video_key": video_key,
        "segments_key": segments_key,
        "github_url": github_url,
        "app_url": app_url,
        "repo_name": _repo_name(github_url),
        "tone": tone,
        "duration_seconds": duration_seconds,
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
    await asyncio.to_thread(
        backend.put, manifest_key, manifest_json, content_type="application/json")
    manifest_url = await asyncio.to_thread(_url_for, backend, manifest_key)

    backend.close()

    # Persist stable object *keys* alongside the freshly-minted URLs. The URLs
    # are re-generated on every read (resolve_result_urls) so they never expire
    # from the user's perspective, while the keys are what survive restarts.
    return {
        "video_key": video_key,
        "manifest_key": manifest_key,
        "segments_key": segments_key,
        "video_url": video_url,
        "manifest_url": manifest_url,
        "segments_url": segments_url,
        "segments": segment_manifest,
        "github_url": manifest["github_url"],
        "app_url": manifest["app_url"],
        "repo_name": manifest["repo_name"],
        "tone": manifest["tone"],
        "duration_seconds": manifest["duration_seconds"],
        "sha256": manifest["sha256"],
        "models_used": manifest["models_used"],
        "generated_at": manifest["generated_at"],
    }


# ---------------------------------------------------------------------------
# Library: reconstruct completed results from B2 (survives refresh / redeploy)
# ---------------------------------------------------------------------------

def _result_from_manifest(manifest: dict, segments: list = None) -> dict:
    """Build a JobResult-shaped dict from a stored manifest (+ optional segments).

    Contains only stable object *keys*; call resolve_result_urls() to mint
    fresh browser-loadable URLs before returning to a client.
    """
    return {
        "video_key": manifest.get("video_key"),
        "manifest_key": manifest.get("manifest_key")
            or f"jobs/{manifest.get('job_id')}/manifest.json",
        "segments_key": manifest.get("segments_key"),
        "segments": segments or [],
        "github_url": manifest.get("github_url", ""),
        "app_url": manifest.get("app_url", ""),
        "repo_name": manifest.get("repo_name", ""),
        "tone": manifest.get("tone"),
        "duration_seconds": manifest.get("duration_seconds"),
        "sha256": manifest.get("sha256"),
        "models_used": manifest.get("models_used"),
        "generated_at": manifest.get("generated_at"),
    }


async def load_result_from_b2(job_id: str) -> dict | None:
    """Reconstruct a completed job's result purely from its B2 manifest.

    Lets /result work after the in-memory job is gone (page refresh, backend
    redeploy). Returns None if this job has no final manifest on B2 (i.e. it
    never completed). URLs are NOT resolved here — the caller does that.
    """
    backend = make_b2_backend()
    try:
        manifest_key = f"jobs/{job_id}/manifest.json"
        try:
            raw = await asyncio.to_thread(backend.get, manifest_key)
        except Exception:
            return None
        try:
            manifest = json.loads(raw)
        except (ValueError, TypeError):
            return None
        manifest.setdefault("manifest_key", manifest_key)

        segments = []
        seg_key = manifest.get("segments_key") or f"jobs/{job_id}/segments_manifest.json"
        try:
            seg_raw = await asyncio.to_thread(backend.get, seg_key)
            segments = json.loads(seg_raw)
        except Exception:
            segments = []

        return _result_from_manifest(manifest, segments)
    finally:
        try:
            await asyncio.to_thread(backend.close)
        except Exception:
            pass


async def list_library() -> list[dict]:
    """List every completed video by reading each job's manifest.json from B2.

    Independent of in-memory state, so the library is complete after any
    refresh or redeploy. Each entry has enough to render a card plus a fresh
    playable/downloadable video URL. Sorted newest-first.
    """
    backend = make_b2_backend()
    items: list[dict] = []
    try:
        # Enumerate all manifest.json keys under jobs/ (paginated).
        manifest_keys: list[str] = []
        token = None
        while True:
            page = await asyncio.to_thread(
                backend.list, "jobs/", continuation_token=token)
            for entry in page.entries:
                if entry.key.endswith("/manifest.json"):
                    manifest_keys.append(entry.key)
            token = page.next_token
            if not token:
                break

        for mkey in manifest_keys:
            try:
                raw = await asyncio.to_thread(backend.get, mkey)
                manifest = json.loads(raw)
            except Exception:
                continue
            manifest.setdefault("manifest_key", mkey)
            job_id = manifest.get("job_id") or mkey.split("/")[1]
            video_key = manifest.get("video_key") or f"jobs/{job_id}/final_video.mp4"
            try:
                video_url = await asyncio.to_thread(_url_for, backend, video_key)
            except Exception:
                video_url = None
            items.append({
                "job_id": job_id,
                "repo_name": manifest.get("repo_name", ""),
                "github_url": manifest.get("github_url", ""),
                "app_url": manifest.get("app_url", ""),
                "tone": manifest.get("tone"),
                "duration_seconds": manifest.get("duration_seconds"),
                "generated_at": manifest.get("generated_at"),
                "video_url": video_url,
                "status": "complete",
            })

        items.sort(key=lambda x: x.get("generated_at") or "", reverse=True)
        return items
    finally:
        try:
            await asyncio.to_thread(backend.close)
        except Exception:
            pass
            
async def get_glued_download_url(job_id: str) -> str | None:
    """Return a URL to the full video with every segment glued together.

    The stored ``final_video.mp4`` was produced by the pipeline; if it looks
    truncated (or you simply always want the segments re-glued at download
    time), this rebuilds one continuous MP4 from the per-segment clips —
    played back to back, with each segment's voiceover, no black frames — and
    caches it on B2 as ``final_glued.mp4`` so repeat downloads are instant.

    Returns a fresh, browser-loadable URL, or None if the job has no segments
    to glue (in which case callers fall back to the original video).
    """
    backend = make_b2_backend()
    tmp_files: list[str] = []
    try:
        # Serve the cached glued video if we've already built it. We probe the
        # object with a lightweight get; if it's present we just re-mint a URL
        # for the existing key instead of rebuilding.
        glued_key = f"jobs/{job_id}/final_glued.mp4"
        try:
            await asyncio.to_thread(backend.get, glued_key)
            return await asyncio.to_thread(_url_for, backend, glued_key)
        except Exception:
            pass  # not built yet — fall through and build it

        # Load the segment manifest (ordered per-segment clip keys).
        seg_key = f"jobs/{job_id}/segments_manifest.json"
        try:
            seg_raw = await asyncio.to_thread(backend.get, seg_key)
            segments = json.loads(seg_raw)
        except Exception:
            return None
        if not isinstance(segments, list) or not segments:
            return None

        segments = sorted(segments, key=lambda s: s.get("segment_id", 0))

        # Import here to avoid any import cycle at module load time.
        from pipeline import video_assembler

        normalized_paths: list[str] = []
        for seg in segments:
            clip_key = seg.get("clip_key")
            if not clip_key:
                continue
            seg_id = seg.get("segment_id", len(normalized_paths))
            raw_path = f"/tmp/dl_{job_id}_seg{seg_id}.mp4"
            data = await asyncio.to_thread(backend.get, clip_key)
            with open(raw_path, "wb") as f:
                f.write(data)
            tmp_files.append(raw_path)

            norm_path = f"/tmp/dlnorm_{job_id}_seg{seg_id}.mp4"
            await video_assembler.normalize_clip(raw_path, norm_path)
            tmp_files.append(norm_path)
            normalized_paths.append(norm_path)

        if not normalized_paths:
            return None

        glued_path = f"/tmp/glued_{job_id}.mp4"
        tmp_files.append(glued_path)
        await video_assembler.concat_segments(normalized_paths, glued_path, job_id)

        with open(glued_path, "rb") as f:
            glued_data = f.read()
        await asyncio.to_thread(
            backend.put, glued_key, glued_data, content_type="video/mp4")
        return await asyncio.to_thread(_url_for, backend, glued_key)
    except Exception:
        return None
    finally:
        for p in tmp_files:
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                pass
        try:
            await asyncio.to_thread(backend.close)
        except Exception:
            pass

async def delete_job(job_id: str) -> bool:
    """Permanently delete all B2 objects for a job (jobs/{job_id}/...).

    Irreversible. Returns True on success. Used by the library Delete action.
    """
    backend = make_b2_backend()
    try:
        await asyncio.to_thread(
            backend.delete_prefix, f"jobs/{job_id}/", dry_run=False)
        return True
    except Exception:
        return False
    finally:
        try:
            await asyncio.to_thread(backend.close)
        except Exception:
            pass
