"""
FastAPI backend for video generation pipeline.

Endpoints:
- POST /generate - Start a new video generation job
- GET /status/{job_id} - Check job status
- GET /stream/{job_id} - Stream job progress via SSE
- GET /health - Health check
"""
import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import uvicorn

from pipeline.llm import generate_script, stream_script_generation
from pipeline.tts import generate_scene_audio
from pipeline.video import capture_all_screenshots, assemble_video
from pipeline.storage import upload_all

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Video Generation API")

# In-memory job store (in production, use a database)
jobs: dict[str, dict] = {}
jobs_lock = asyncio.Lock()


class GenerateRequest(BaseModel):
    """Request to generate a video"""
    topic: str


class JobStatus(BaseModel):
    """Job status response"""
    job_id: str
    status: str  # pending, generating_script, capturing_screenshots, generating_audio, assembling_video, uploading, complete, failed
    message: str
    created_at: str
    updated_at: str
    video_url: Optional[str] = None
    error: Optional[str] = None


async def process_job(job_id: str) -> None:
    """
    Main job processing pipeline.
    
    Args:
        job_id: The unique job identifier
    """
    try:
        topic = jobs[job_id]["topic"]
        
        # Step 1: Generate script
        await update_job_status(job_id, "generating_script", "Generating video script...")
        try:
            script = await generate_script(topic)
            jobs[job_id]["script"] = script
        except Exception as e:
            raise RuntimeError(f"Script generation failed: {str(e)}")
        
        # Step 2: Capture screenshots
        await update_job_status(job_id, "capturing_screenshots", f"Capturing {len(script)} screenshots...")
        try:
            screenshots = await capture_all_screenshots(script)
            jobs[job_id]["screenshots"] = screenshots
        except Exception as e:
            raise RuntimeError(f"Screenshot capture failed: {str(e)}")
        
        # Step 3: Generate audio
        await update_job_status(job_id, "generating_audio", f"Generating audio for {len(script)} scenes...")
        try:
            audio_files = await generate_scene_audio(script)
            jobs[job_id]["audio_files"] = audio_files
        except Exception as e:
            raise RuntimeError(f"Audio generation failed: {str(e)}")
        
        # Step 4: Assemble video
        await update_job_status(job_id, "assembling_video", "Assembling final video...")
        try:
            video_path = f"/tmp/final_{job_id}.mp4"
            video_path = assemble_video(
                script,
                screenshots,
                audio_files,
                video_path,
            )
            jobs[job_id]["video_path"] = video_path
        except Exception as e:
            raise RuntimeError(f"Video assembly failed: {str(e)}")
        
        # Step 5: Upload to storage
        await update_job_status(job_id, "uploading", "Uploading to cloud storage...")
        try:
            upload_result = await upload_all(job_id, video_path, script)
            jobs[job_id]["upload_result"] = upload_result
            jobs[job_id]["video_url"] = upload_result.get("video_url")
        except Exception as e:
            raise RuntimeError(f"Upload failed: {str(e)}")
        
        # Mark complete
        await update_job_status(job_id, "complete", "Video generation complete!")
        
        # Cleanup
        try:
            if os.path.exists(video_path):
                os.unlink(video_path)
        except:
            pass
        
    except Exception as e:
        error_msg = str(e)
        await update_job_status(job_id, "failed", f"Job failed: {error_msg}", error=error_msg)


async def update_job_status(
    job_id: str,
    status: str,
    message: str,
    error: Optional[str] = None,
) -> None:
    """
    Update job status safely.
    
    Args:
        job_id: The job identifier
        status: New status
        message: Status message
        error: Error message if applicable
    """
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["status"] = status
            jobs[job_id]["message"] = message
            jobs[job_id]["updated_at"] = datetime.utcnow().isoformat() + "Z"
            if error:
                jobs[job_id]["error"] = error


@app.post("/generate")
async def generate(request: GenerateRequest) -> dict:
    """
    Start a new video generation job.
    
    Args:
        request: GenerateRequest with topic
        
    Returns:
        Job details with job_id
    """
    # Validate GitHub token
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        raise HTTPException(
            status_code=400,
            detail="Server configuration error: GITHUB_TOKEN not set",
        )
    
    # Create job
    job_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat() + "Z"
    
    async with jobs_lock:
        jobs[job_id] = {
            "topic": request.topic,
            "status": "pending",
            "message": "Queued for processing",
            "created_at": now,
            "updated_at": now,
            "error": None,
            "video_url": None,
        }
    
    # Start background processing
    asyncio.create_task(process_job(job_id))
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Job queued for processing",
        "created_at": now,
    }


@app.get("/status/{job_id}")
async def get_status(job_id: str) -> JobStatus:
    """
    Get the current status of a job.
    
    Args:
        job_id: The job identifier
        
    Returns:
        Job status details
    """
    async with jobs_lock:
        if job_id not in jobs:
            raise HTTPException(status_code=404, detail="Job not found")
        
        job = jobs[job_id]
        return JobStatus(
            job_id=job_id,
            status=job["status"],
            message=job["message"],
            created_at=job["created_at"],
            updated_at=job["updated_at"],
            video_url=job.get("video_url"),
            error=job.get("error"),
        )


async def job_stream_generator(job_id: str):
    """
    Generate SSE events for job progress.
    
    Args:
        job_id: The job identifier
        
    Yields:
        SSE-formatted event strings
    """
    seen_statuses = set()
    
    while True:
        async with jobs_lock:
            if job_id not in jobs:
                yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                break
            
            job = jobs[job_id]
            status = job["status"]
            
            # Only send if status changed
            if status not in seen_statuses:
                seen_statuses.add(status)
                event_data = {
                    "job_id": job_id,
                    "status": status,
                    "message": job["message"],
                    "updated_at": job["updated_at"],
                }
                if job.get("video_url"):
                    event_data["video_url"] = job["video_url"]
                if job.get("error"):
                    event_data["error"] = job["error"]
                
                yield f"data: {json.dumps(event_data)}\n\n"
            
            # Stop if complete or failed
            if status in ("complete", "failed"):
                break
        
        # Wait before polling again
        await asyncio.sleep(1)


@app.get("/stream/{job_id}")
async def stream_job(job_id: str):
    """
    Stream job progress via Server-Sent Events.
    
    Args:
        job_id: The job identifier
        
    Returns:
        StreamingResponse with SSE events
    """
    return StreamingResponse(
        job_stream_generator(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/health")
async def health_check() -> dict:
    """
    Health check endpoint.
    
    Returns:
        Health status
    """
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
    )
>>>>>>> main
