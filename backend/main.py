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
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from models import GenerateRequest, JobStatus, JobResult
from jobs import create_job, get_job
from pipeline.orchestrator import run_pipeline

load_dotenv()

app = FastAPI(title="Devfields API")

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
    if not os.environ.get("ELEVENLABS_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: ELEVENLABS_API_KEY not set",
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
    await create_job(job_id)

    # Launch pipeline in the background — this is the line that was
    # missing entirely from the old main.py
    asyncio.create_task(run_pipeline(job_id, request))

    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}")
async def get_status(job_id: str) -> JobStatus:
    """Get the current status of a job."""
    job = await get_job(job_id)
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
    job = await get_job(job_id)
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


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint for Railway."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
