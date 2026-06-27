import asyncio
from typing import Optional

# Global jobs dict stores all job state
jobs: dict = {}
jobs_lock = asyncio.Lock()


async def create_job(job_id: str) -> None:
    """Create a new job entry with status 'queued'."""
    async with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "current_step": None,
            "steps_completed": [],
            "message": None,
            "error": None,
            "result": None,
            "tmp_files": [],
        }


async def update_job(job_id: str, **kwargs) -> None:
    """Update any fields on the job."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)


async def set_step(job_id: str, step: str, message: str) -> None:
    """Set current_step, status to in_progress, and message."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["current_step"] = step
            jobs[job_id]["status"] = "in_progress"
            jobs[job_id]["message"] = message


async def complete_step(job_id: str, step: str) -> None:
    """Append step to steps_completed and clear current_step."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["steps_completed"].append(step)
            jobs[job_id]["current_step"] = None


async def fail_job(job_id: str, error: str) -> None:
    """Set status to failed, set error, clear current_step."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = error
            jobs[job_id]["current_step"] = None


async def complete_job(job_id: str, result: dict) -> None:
    """Set status to complete and store result."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["status"] = "complete"
            jobs[job_id]["result"] = result


async def get_job(job_id: str) -> Optional[dict]:
    """Return a copy of the job dict, or None if not found."""
    async with jobs_lock:
        if job_id in jobs:
            return dict(jobs[job_id])
        return None


async def add_tmp_file(job_id: str, path: str) -> None:
    """Register a temporary file for cleanup."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["tmp_files"].append(path)


async def get_tmp_files(job_id: str) -> list[str]:
    """Return the list of temporary files to clean up."""
    async with jobs_lock:
        if job_id in jobs:
            return list(jobs[job_id]["tmp_files"])
        return []
