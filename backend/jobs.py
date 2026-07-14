import asyncio
import os
from typing import Optional

# Global jobs dict stores all job state
jobs: dict = {}
jobs_lock = asyncio.Lock()


async def create_job(job_id: str, request=None) -> None:
    """Create a new job entry with status 'queued'.

    `request` is the original GenerateRequest, stored so a failed job can be
    retried without the client re-submitting the form. `checkpoints` holds the
    output of each completed step so a retry can resume instead of restarting.
    """
    async with jobs_lock:
        jobs[job_id] = {
            "status": "queued",
            "current_step": None,
            "steps_completed": [],
            "message": None,
            "error": None,
            "result": None,
            "tmp_files": [],
            "snapshots": [],
            "request": request,
            "checkpoints": {},
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


async def save_checkpoint(job_id: str, key: str, value) -> None:
    """Store a completed step's output so a retry can reuse it."""
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id].setdefault("checkpoints", {})[key] = value


async def reset_for_retry(job_id: str) -> None:
    """Prepare a failed job to run again from its last successful step.

    Keeps steps_completed, checkpoints, snapshots and tmp_files intact so the
    pipeline resumes rather than starting over. Only the failed step onward
    will re-run.
    """
    async with jobs_lock:
        if job_id in jobs:
            jobs[job_id]["status"] = "queued"
            jobs[job_id]["error"] = None
            jobs[job_id]["current_step"] = None


def _dump_request(request) -> Optional[dict]:
    """Serialize a GenerateRequest (pydantic v1/v2) to a plain dict."""
    if request is None:
        return None
    if hasattr(request, "model_dump"):
        return request.model_dump()
    if hasattr(request, "dict"):
        return request.dict()
    if isinstance(request, dict):
        return request
    return None


async def persist_failed_job(job_id: str) -> None:
    """Snapshot a failed job to durable storage so it can resume after a redeploy.

    Uploads every intermediate artifact still on disk and writes a resume-state
    document (request + completed steps + checkpoints + artifact manifest) to
    Backblaze B2. Best-effort: any failure here is logged and swallowed so it
    never masks the original pipeline error.
    """
    from pipeline import checkpoint_store

    if not checkpoint_store.is_enabled():
        return

    job = await get_job(job_id)
    if job is None:
        return

    # Upload each on-disk artifact, keyed by basename (unique within a job
    # because paths embed the job id / segment id). The manifest maps the
    # ORIGINAL local path -> B2 key so we can restore files to the exact paths
    # the checkpoints reference.
    artifacts: dict[str, str] = {}
    for path in job.get("tmp_files", []):
        if not path or not os.path.isfile(path):
            continue
        name = os.path.basename(path)
        key = await checkpoint_store.upload_artifact(job_id, name, path)
        if key:
            artifacts[path] = key

    state = {
        "status": "failed",
        "error": job.get("error"),
        "steps_completed": job.get("steps_completed", []),
        "checkpoints": job.get("checkpoints", {}),
        "snapshots": job.get("snapshots", []),
        "request": _dump_request(job.get("request")),
        "artifacts": artifacts,
    }
    await checkpoint_store.save_state(job_id, state)


async def rehydrate_job(job_id: str):
    """Rebuild an in-memory job from durable storage (e.g. after a redeploy).

    Downloads every saved artifact back to its original local path so the
    restored checkpoints stay valid, reconstructs the request, and inserts the
    job into memory. Returns the reconstructed GenerateRequest, or None if no
    durable state exists.
    """
    from pipeline import checkpoint_store
    from models import GenerateRequest

    state = await checkpoint_store.load_state(job_id)
    if not state or not state.get("request"):
        return None

    # Restore artifacts to the paths the checkpoints expect.
    for local_path, key in (state.get("artifacts") or {}).items():
        if os.path.isfile(local_path):
            continue
        await checkpoint_store.download_artifact(key, local_path)

    request = GenerateRequest(**state["request"])

    async with jobs_lock:
        jobs[job_id] = {
            "status": "failed",
            "current_step": None,
            "steps_completed": list(state.get("steps_completed", [])),
            "message": None,
            "error": state.get("error"),
            "result": None,
            "tmp_files": list((state.get("artifacts") or {}).keys()),
            "snapshots": list(state.get("snapshots", [])),
            "request": request,
            "checkpoints": dict(state.get("checkpoints", {})),
        }

    return request


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


async def add_snapshot(job_id: str, snapshot: dict, max_snapshots: int = 24) -> None:
    """Append bounded, safe snapshot metadata to a job."""
    async with jobs_lock:
        if job_id not in jobs:
            return
        snapshots = jobs[job_id]["snapshots"]
        snapshots.append(snapshot)
        if len(snapshots) > max_snapshots:
            removed = snapshots.pop(0)
            removed_path = removed.get("file_path")
            if removed_path:
                try:
                    os.remove(removed_path)
                except OSError:
                    pass


async def get_snapshot(job_id: str, snapshot_id: str) -> Optional[dict]:
    """Resolve a snapshot only when it belongs to the requested job."""
    async with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            return None
        for snapshot in job.get("snapshots", []):
            if snapshot.get("id") == snapshot_id:
                return dict(snapshot)
        return None
