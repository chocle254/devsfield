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
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv

from models import GenerateRequest, JobStatus, JobResult
from jobs import create_job, get_job, get_snapshot, reset_for_retry, restore_job
from pipeline import resume_store
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
    # GMI_CLOUD_API_KEY. No separate ElevenLabs account needed.
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
    """Get the final result of a completed job."""
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] != "complete":
        return {"status": job["status"], "message": "Job not complete yet"}

    result = job.get("result") or {}
    return JobResult(
        job_id=job_id,
        status=job["status"],
        video_url=result.get("video_url"),
        manifest_url=result.get("manifest_url"),
        segments_url=result.get("segments_url"),   # NEW
        segments=result.get("segments"),            # NEW
        sha256=result.get("sha256"),
        models_used=result.get("models_used"),
        generated_at=result.get("generated_at"),
    )


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
