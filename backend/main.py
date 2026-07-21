"""
FastAPI backend for Devfields — AI-powered demo video generator.

Endpoints:
- POST /generate      - Start a new video generation job
- GET  /status/{id}   - Check job status
- GET  /result/{id}   - Get final result when complete
- GET  /stream/{id}   - Stream job progress via SSE
- GET  /health        - Health check
"""
import asyncio
import json
import math
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv

from models import GenerateRequest, JobStatus, JobResult
from jobs import create_job, get_job, get_snapshot, reset_for_retry, restore_job
from pipeline import resume_store, storage
from pipeline.orchestrator import run_pipeline

load_dotenv()

app = FastAPI(title="Devfields API")


async def ensure_job_loaded(job_id: str):
    """Return a job, rehydrating it from B2 if it's not in memory.

    After a backend redeploy the in-memory `jobs` dict is empty, so any run
    that was mid-flight or failed would otherwise 404. If it was checkpointed
    to durable storage we rebuild the in-memory entry from `state.json`
    (metadata only — artifact files are pulled back separately, and only when
    a retry actually needs them).
    """
    job = await get_job(job_id)
    if job is not None:
        return job
    state = await resume_store.load_state(job_id)
    if state is None:
        return None
    await restore_job(job_id, state)
    return await get_job(job_id)


def _is_verified_v3_master(result: object) -> bool:
    """Do not trust a partially deployed or pre-contract v3 manifest."""
    if not isinstance(result, dict):
        return False
    try:
        requested = float(result["requested_duration_seconds"])
        actual = float(result["actual_duration_seconds"])
        voiced_count = int(result["voiced_segment_count"])
    except (KeyError, TypeError, ValueError):
        return False
    segments = result.get("segments")
    if (not math.isfinite(requested) or not math.isfinite(actual) or
            abs(actual - requested) > storage._selected_duration_tolerance(requested) or
            not isinstance(segments, list) or not segments or
            voiced_count != len(segments)):
        return False
    return all(
        isinstance(segment, dict) and bool(segment.get("voice_key"))
        for segment in segments
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate")
async def generate(request: GenerateRequest) -> dict:
    """Start a new demo video generation job."""

    # Required environment variables
    # NOTE: ELEVENLABS_API_KEY removed — voice_generator.py now uses
    # genblaze-gmicloud (GMICloudAudioProvider), which only needs
    # GMI_CLOUD_API_KEY. NVIDIA_API_KEY powers the vision fallback used for
    # visually grounded browser interaction. No separate ElevenLabs account
    # is needed.
    if not os.environ.get("GITHUB_TOKEN"):
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: GITHUB_TOKEN not set",
        )
    if not os.environ.get("GMI_CLOUD_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: GMI_CLOUD_API_KEY not set",
        )
    if not os.environ.get("NVIDIA_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: NVIDIA_API_KEY not set",
        )
    if not os.environ.get("B2_BUCKET"):
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: B2_BUCKET not set",
        )

    # Input validation
    if not request.github_url.startswith("https://github.com/"):
        raise HTTPException(
            status_code=400,
            detail="github_url must be a valid GitHub repository URL",
        )
    if not request.app_url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="app_url must be a valid HTTPS URL",
        )

    job_id = str(uuid.uuid4())
    # Store the request so a failed run can be retried (resumed) without the
    # client re-submitting the form.
    await create_job(job_id, request)

    asyncio.create_task(run_pipeline(job_id, request))

    return {"job_id": job_id, "status": "queued"}


@app.post("/retry/{job_id}")
async def retry_job(job_id: str) -> dict:
    """Resume a failed job from the step that broke.

    Reuses the checkpointed output of every step that already completed, so
    only the failed step onward re-runs. Works even after a backend redeploy:
    the run's state and intermediate artifacts are rehydrated from Backblaze
    B2 when they're no longer in memory / on local disk.
    """
    job = await ensure_job_loaded(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only a failed job can be retried",
        )

    request = job.get("request")
    if request is None:
        raise HTTPException(
            status_code=409,
            detail="This run can no longer be retried. Please start a new one.",
        )

    # Pull the checkpointed artifact files back onto local disk if they're not
    # already there (they live only in B2 after a redeploy). Anything that
    # can't be restored is transparently re-run from the earliest missing step.
    try:
        await resume_store.download_artifacts(job_id)
    except Exception:
        pass

    await reset_for_retry(job_id)
    asyncio.create_task(run_pipeline(job_id, request))

    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}")
async def get_status(job_id: str) -> JobStatus:
    """Get the current status of a job."""
    job = await ensure_job_loaded(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatus(
        job_id=job_id,
        status=job["status"],
        current_step=job.get("current_step"),
        steps_completed=job.get("steps_completed", []),
        steps_total=7,
        message=job.get("message"),
        error=job.get("error"),
        snapshots=[
            {key: value for key, value in snapshot.items()
             if key not in ("file_path", "content_hash")}
            for snapshot in job.get("snapshots", [])
        ],
    )


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    """Get the final result of a completed job.

    Works even after a page refresh or backend redeploy: if the job is gone
    from memory (or was never complete in this process), we reconstruct the
    completed result straight from the durable B2 manifest.
    """
    job = await get_job(job_id)
    result = None

    if job is not None and job.get("status") == "complete":
        result = job.get("result") or {}
    else:
        # Not in memory / not complete here — try the durable manifest on B2.
        result = await storage.load_result_from_b2(job_id)
        if result is None:
            if job is not None:
                # In memory but still running/failed: report live status.
                return {"status": job["status"], "message": "Job not complete yet"}
            raise HTTPException(status_code=404, detail="Job not found")

    # Re-mint fresh, browser-loadable URLs from the stored object keys. Stored
    # URLs may be expired presigned links (e.g. after a restart), so we always
    # regenerate on read.
    result = await storage.resolve_result_urls(result)
    return JobResult(
        job_id=job_id,
        status="complete",
        video_url=result.get("video_url"),
        manifest_url=result.get("manifest_url"),
        segments_url=result.get("segments_url"),
        segments=result.get("segments"),
        github_url=result.get("github_url"),
        app_url=result.get("app_url"),
        repo_name=result.get("repo_name"),
        tone=result.get("tone"),
        duration_seconds=result.get("duration_seconds"),
        sha256=result.get("sha256"),
        models_used=result.get("models_used"),
        generated_at=result.get("generated_at"),
    )


@app.get("/download/{job_id}")
async def get_download(job_id: str):
    """Return the canonical final MP4, with legacy re-gluing as fallback.

    v3 ``final_video.mp4`` is assembled and duration/audio-verified by the pipeline,
    so it is the authoritative artifact for new downloads.  Older manifests
    use the repaired segment rebuild once, even if their original master file
    still exists.
    """
    result = await storage.load_result_from_b2(job_id)
    if result is not None:
        result = await storage.resolve_result_urls(result)
        # Only v3 masters were checked against both the selected duration and
        # real narration. Older jobs may be short/silent, so use the legacy
        # rebuild path where possible instead of presenting them as verified.
        try:
            assembly_version = int(result.get("assembly_version", 0))
        except (TypeError, ValueError):
            assembly_version = 0
        if (assembly_version >= storage.ASSEMBLY_VERSION and
                _is_verified_v3_master(result)):
            video_url = result.get("video_url")
            if video_url:
                return {"job_id": job_id, "video_url": video_url}

    # Legacy fallback for jobs that predate the verified v3 assembly.
    glued_url = await storage.get_glued_download_url(job_id)
    if glued_url:
        return {"job_id": job_id, "video_url": glued_url}

    # An older job may not retain individual clips. Its original master is
    # still the best downloadable artifact in that exceptional case.
    if result is not None and result.get("video_url"):
        return {"job_id": job_id, "video_url": result["video_url"]}

    raise HTTPException(status_code=404, detail="Job not found")


@app.get("/library")
async def get_library():
    """List all completed videos found on Backblaze B2 (newest first).

    Reads each job's manifest.json, so the library is complete regardless of
    in-memory state — survives refreshes and redeploys.
    """
    return {"videos": await storage.list_library()}


@app.delete("/library/{job_id}")
async def delete_library_item(job_id: str):
    """Permanently delete a video and all its assets from B2. Irreversible."""
    ok = await storage.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete video")
    return {"job_id": job_id, "deleted": True}


async def sse_generator(job_id: str):
    """Yield SSE events for job progress until complete or failed."""
    while True:
        job = await get_job(job_id)
        if job is None:
            yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
            break

        event_data = {
            "job_id": job_id,
            "status": job["status"],
            "current_step": job.get("current_step"),
            "steps_completed": job.get("steps_completed", []),
            "message": job.get("message"),
            "error": job.get("error"),
            "snapshots": [
                {key: value for key, value in snapshot.items()
                 if key not in ("file_path", "content_hash")}
                for snapshot in job.get("snapshots", [])
            ],
        }

        result = job.get("result")
        if result and result.get("video_url"):
            event_data["video_url"] = result["video_url"]

        yield f"data: {json.dumps(event_data)}\n\n"

        if job["status"] in ("complete", "failed"):
            break

        await asyncio.sleep(1)


@app.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """Stream job progress via Server-Sent Events."""
    job = await ensure_job_loaded(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return StreamingResponse(
        sse_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/snapshot/{job_id}/{snapshot_id}")
async def serve_snapshot(job_id: str, snapshot_id: str):
    """Serve a snapshot only through its owning run and opaque snapshot ID."""
    snapshot = await get_snapshot(job_id, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    file_path = snapshot.get("file_path")
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Snapshot no longer available")

    return FileResponse(
        file_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for Railway."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
