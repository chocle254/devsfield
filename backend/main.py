import asyncio
import json
import os
import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from models import GenerateRequest, JobStatus, JobResult
from jobs import create_job, get_job, fail_job
from pipeline.orchestrator import run_pipeline

load_dotenv()

app = FastAPI(title="Devfields Backend")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate")
async def generate(request: GenerateRequest, background_tasks: BackgroundTasks):
    """Start a new video generation job."""
    # Check GITHUB_TOKEN
    if not os.environ.get("GITHUB_TOKEN"):
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: GITHUB_TOKEN not set"
        )
    
    # Validate github_url
    if not request.github_url.startswith("https://github.com/"):
        raise HTTPException(
            status_code=400,
            detail="github_url must be a valid GitHub repository URL"
        )
    
    # Validate app_url
    if not request.app_url.startswith("https://"):
        raise HTTPException(
            status_code=400,
            detail="app_url must be a valid HTTPS URL"
        )
    
    # Create job
    job_id = str(uuid.uuid4())
    await create_job(job_id)
    
    # Launch pipeline in background
    background_tasks.add_task(run_pipeline, job_id, request)
    
    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get current status of a job."""
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatus(
        job_id=job_id,
        status=job["status"],
        current_step=job["current_step"],
        steps_completed=job["steps_completed"],
        steps_total=7,
        message=job["message"],
        error=job["error"],
    )


@app.get("/result/{job_id}")
async def get_result(job_id: str):
    """Get result of a completed job."""
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "complete":
        return {
            "status": job["status"],
            "message": "Job not complete yet"
        }, 202
    
    result = job.get("result", {})
    return JobResult(
        job_id=job_id,
        status=job["status"],
        video_url=result.get("video_url"),
        manifest_url=result.get("manifest_url"),
        sha256=result.get("sha256"),
        models_used=result.get("models_used"),
        duration_seconds=result.get("duration_seconds"),
        generated_at=result.get("generated_at"),
    )


@app.get("/stream/{job_id}")
async def stream_status(job_id: str):
    """Stream job status updates as Server-Sent Events."""
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    async def event_generator():
        while True:
            job_data = await get_job(job_id)
            if job_data is None:
                break
            
            event_data = {
                "job_id": job_id,
                "status": job_data["status"],
                "current_step": job_data["current_step"],
                "steps_completed": job_data["steps_completed"],
                "message": job_data["message"],
                "error": job_data["error"],
            }
            
            yield f"data: {json.dumps(event_data)}\n\n"
            
            if job_data["status"] in ["complete", "failed"]:
                break
            
            await asyncio.sleep(1)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
