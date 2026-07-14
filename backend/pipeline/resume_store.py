"""
Durable, resumable-pipeline state backed by Backblaze B2.

Why this exists
---------------
All live job state (the `jobs` dict) and every intermediate artifact
(recording, voiceovers, composited clips, final video) normally live in
process memory and on the container's local /tmp. When the backend is
redeployed — e.g. after fixing a bug — the process restarts and BOTH are
lost, so the "Retry from failed step" button had nothing to resume from.

This module mirrors the resumable parts of a run into a scratch prefix on
B2 (`jobs/{job_id}/_resume/...`) after every completed step and on failure:

- `state.json`            — status, steps_completed, error, the original
                            request, and the step checkpoints (metadata only).
- `artifacts/<slot>`      — the actual files a later step needs to keep going.

On retry we rebuild the in-memory job from `state.json` (`load_state`) and
re-download the artifact files to local disk (`download_artifacts`). Anything
that can't be restored is left missing so `validate_checkpoints` truncates the
run back to the last fully-intact step — "resume as far as possible, else
restart cleanly".

The scratch prefix is deleted the moment a run completes successfully
(`cleanup`), so B2 only ever holds resume data for in-flight / failed runs.
The permanent deliverables uploaded by `storage.upload_all` live under a
different key space (`jobs/{job_id}/final_video.mp4`, `.../segments/...`) and
are never touched here.
"""
import asyncio
import json
import os
from typing import Callable, Optional

from models import GenerateRequest
from jobs import get_job
from . import storage

# Scratch key space for resume data. Deleted on successful completion.
_RESUME_PREFIX = "jobs/{job_id}/_resume/"
_STATE_KEY = _RESUME_PREFIX + "state.json"
_ARTIFACT_PREFIX = _RESUME_PREFIX + "artifacts/"

# Pipeline steps in execution order, each mapped to the checkpoint keys it
# produces. Used to decide how far a resumed run can be trusted. The terminal
# "storage" step is intentionally absent — it has no checkpoint and always
# re-runs.
_STEP_KEYS: list[tuple[str, list[str]]] = [
    ("github_reader", ["context", "plan"]),
    ("app_browser", ["recording"]),
    ("script_writer", ["script_segments"]),
    ("image_generator", ["title_card_path"]),
    ("voice_generator", ["voiced_segments"]),
    ("video_assembler", ["assembly"]),
]

_CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".wav": "audio/wav",
}


def _content_type(path: str) -> str:
    return _CONTENT_TYPES.get(os.path.splitext(path)[1].lower(),
                              "application/octet-stream")


# ---------------------------------------------------------------------------
# Artifact discovery
# ---------------------------------------------------------------------------
# A "slot" is one file referenced by a checkpoint, described by a stable id
# (used as its B2 key suffix) plus a setter so we can rewrite the checkpoint's
# path field to a freshly downloaded local file on restore.

def _artifact_slots(checkpoints: dict) -> list[tuple[str, str, Callable[[str], None]]]:
    """Return (slot_id, local_path, set_path) for every file in the checkpoints."""
    slots: list[tuple[str, str, Callable[[str], None]]] = []

    rec = checkpoints.get("recording")
    if isinstance(rec, dict) and rec.get("video_path"):
        def _set_rec(p: str, d=rec) -> None:
            d["video_path"] = p
        slots.append(("recording__video.mp4", rec["video_path"], _set_rec))

    tc = checkpoints.get("title_card_path")
    if isinstance(tc, str) and tc:
        ext = os.path.splitext(tc)[1] or ".png"
        def _set_tc(p: str) -> None:
            checkpoints["title_card_path"] = p
        slots.append((f"title_card{ext}", tc, _set_tc))

    voiced = checkpoints.get("voiced_segments")
    if isinstance(voiced, list):
        for i, seg in enumerate(voiced):
            if isinstance(seg, dict) and seg.get("audio_path"):
                def _set_voice(p: str, d=seg) -> None:
                    d["audio_path"] = p
                slots.append((f"voiced__{i}.mp3", seg["audio_path"], _set_voice))

    asm = checkpoints.get("assembly")
    if isinstance(asm, dict):
        if asm.get("final_video_path"):
            def _set_final(p: str, d=asm) -> None:
                d["final_video_path"] = p
            slots.append(("assembly__final.mp4", asm["final_video_path"], _set_final))
        clips = asm.get("segment_clips")
        if isinstance(clips, list):
            for i, clip in enumerate(clips):
                if not isinstance(clip, dict):
                    continue
                for field in ("clip_path", "voice_path", "merged_path"):
                    if clip.get(field):
                        def _set_clip(p: str, d=clip, f=field) -> None:
                            d[f] = p
                        ext = os.path.splitext(clip[field])[1] or ".mp4"
                        slots.append(
                            (f"assembly__clip{i}__{field}{ext}", clip[field], _set_clip))
    return slots


def _files_for_checkpoint(key: str, checkpoints: dict) -> list[str]:
    """Local file paths that must exist for a given checkpoint to be usable."""
    paths: list[str] = []
    if key == "recording":
        rec = checkpoints.get("recording") or {}
        if rec.get("video_path"):
            paths.append(rec["video_path"])
    elif key == "title_card_path":
        # None is a valid, complete result (no title card) — no file required.
        tc = checkpoints.get("title_card_path")
        if isinstance(tc, str) and tc:
            paths.append(tc)
    elif key == "voiced_segments":
        for seg in checkpoints.get("voiced_segments") or []:
            if isinstance(seg, dict) and seg.get("audio_path"):
                paths.append(seg["audio_path"])
    elif key == "assembly":
        asm = checkpoints.get("assembly") or {}
        if asm.get("final_video_path"):
            paths.append(asm["final_video_path"])
        for clip in asm.get("segment_clips") or []:
            if isinstance(clip, dict):
                for field in ("clip_path", "voice_path", "merged_path"):
                    if clip.get(field):
                        paths.append(clip[field])
    return paths


def validate_checkpoints(steps_completed: list, checkpoints: dict) -> tuple[list, dict]:
    """Trim a run back to its last fully-intact step.

    Walks the steps in execution order and keeps a step only if it was marked
    complete AND all of its checkpoint keys exist AND all of the files those
    checkpoints reference are present on local disk. Stops at the first gap.
    Returns the kept steps and a checkpoint dict containing only their keys.
    """
    completed = set(steps_completed)
    kept_steps: list[str] = []
    kept_keys: set[str] = set()

    for step, keys in _STEP_KEYS:
        if step not in completed:
            break
        if not all(k in checkpoints for k in keys):
            break
        files_ok = True
        for k in keys:
            for path in _files_for_checkpoint(k, checkpoints):
                if not os.path.isfile(path):
                    files_ok = False
                    break
            if not files_ok:
                break
        if not files_ok:
            break
        kept_steps.append(step)
        kept_keys.update(keys)

    kept_ckpt = {k: v for k, v in checkpoints.items() if k in kept_keys}
    return kept_steps, kept_ckpt


# ---------------------------------------------------------------------------
# Persist / restore / cleanup
# ---------------------------------------------------------------------------

def _serialize_request(request) -> Optional[dict]:
    if request is None:
        return None
    if hasattr(request, "model_dump"):
        return request.model_dump()
    if isinstance(request, dict):
        return request
    return None


async def persist(job_id: str) -> None:
    """Mirror the current resumable state of a job to B2.

    Uploads any not-yet-uploaded artifact files, then writes state.json. Safe
    to call after every step and on failure; artifacts are content-stable once
    a step completes, so each file is uploaded at most once per process
    (tracked via the in-memory `_persisted_slots` set).
    """
    job = await get_job(job_id)
    if job is None:
        return
    checkpoints = job.get("checkpoints", {}) or {}

    backend = await asyncio.to_thread(storage.make_b2_backend)
    try:
        persisted: set = set(job.get("_persisted_slots") or [])
        for slot_id, local_path, _set in _artifact_slots(checkpoints):
            if slot_id in persisted:
                continue
            if not os.path.isfile(local_path):
                continue
            with open(local_path, "rb") as f:
                data = f.read()
            key = _ARTIFACT_PREFIX.format(job_id=job_id) + slot_id
            await asyncio.to_thread(
                backend.put, key, data, content_type=_content_type(local_path))
            persisted.add(slot_id)

        # Remember what we've uploaded so later steps don't re-push big files.
        from jobs import update_job
        await update_job(job_id, _persisted_slots=persisted)

        state = {
            "job_id": job_id,
            "status": job.get("status"),
            "steps_completed": job.get("steps_completed", []),
            "message": job.get("message"),
            "error": job.get("error"),
            "request": _serialize_request(job.get("request")),
            "checkpoints": checkpoints,
        }
        state_bytes = json.dumps(state).encode()
        await asyncio.to_thread(
            backend.put, _STATE_KEY.format(job_id=job_id), state_bytes,
            content_type="application/json")
    finally:
        await asyncio.to_thread(backend.close)


async def load_state(job_id: str) -> Optional[dict]:
    """Load a run's durable state from B2 (metadata only, no file downloads).

    Returns a dict ready for `jobs.restore_job` — including `request`
    reconstructed as a GenerateRequest — or None if nothing was checkpointed.
    """
    backend = await asyncio.to_thread(storage.make_b2_backend)
    try:
        try:
            raw = await asyncio.to_thread(
                backend.get, _STATE_KEY.format(job_id=job_id))
        except Exception:
            return None
    finally:
        await asyncio.to_thread(backend.close)

    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return None

    req_data = state.get("request")
    request = None
    if isinstance(req_data, dict):
        try:
            request = GenerateRequest(**req_data)
        except Exception:
            request = None

    # We only ever load state in a process that is NOT running this job (it
    # wasn't in memory). So a state that still says "queued"/"in_progress" is
    # an interrupted run — the server restarted mid-generation. Present it as a
    # retryable failure so the user gets the "Retry from failed step" button
    # instead of a spinner that never resolves.
    status = state.get("status") or "failed"
    error = state.get("error")
    if status not in ("failed", "complete"):
        status = "failed"
        error = error or (
            "The run was interrupted when the server restarted. "
            "Retry to resume from where it left off."
        )

    return {
        "status": status,
        "steps_completed": state.get("steps_completed", []),
        "message": state.get("message"),
        "error": error,
        "request": request,
        "checkpoints": state.get("checkpoints", {}) or {},
    }


async def download_artifacts(job_id: str) -> None:
    """Re-download checkpoint artifacts from B2 onto local disk.

    Rewrites each checkpoint's path field to the freshly downloaded file and
    registers it for cleanup. Files that already exist locally (same-process
    retry) are left untouched; files that can't be restored are left missing
    so `validate_checkpoints` will truncate past them on the next run.
    """
    job = await get_job(job_id)
    if job is None:
        return
    checkpoints = job.get("checkpoints", {}) or {}
    slots = _artifact_slots(checkpoints)
    if not slots:
        return

    dest_dir = f"/tmp/resume_{job_id}"
    os.makedirs(dest_dir, exist_ok=True)

    from jobs import add_tmp_file

    backend = await asyncio.to_thread(storage.make_b2_backend)
    try:
        for slot_id, local_path, set_path in slots:
            if os.path.isfile(local_path):
                continue  # already on disk (same-process retry)
            key = _ARTIFACT_PREFIX.format(job_id=job_id) + slot_id
            try:
                data = await asyncio.to_thread(backend.get, key)
            except Exception:
                continue  # not in B2 — leave missing, validation will truncate
            dest_path = os.path.join(dest_dir, slot_id)
            with open(dest_path, "wb") as f:
                f.write(data)
            set_path(dest_path)
            await add_tmp_file(job_id, dest_path)
    finally:
        await asyncio.to_thread(backend.close)

    # Persist the rewritten paths back into the in-memory job.
    from jobs import set_resume_state
    await set_resume_state(job_id, job.get("steps_completed", []), checkpoints)


async def cleanup(job_id: str) -> None:
    """Delete the entire resume scratch prefix for a finished run.

    Called on successful completion so B2 only retains resume data for
    in-flight or failed runs. Best-effort — a cleanup failure never affects
    the delivered result.
    """
    backend = await asyncio.to_thread(storage.make_b2_backend)
    try:
        prefix = _RESUME_PREFIX.format(job_id=job_id)
        await asyncio.to_thread(backend.delete_prefix, prefix, dry_run=False)
    except Exception:
        pass
    finally:
        try:
            await asyncio.to_thread(backend.close)
        except Exception:
            pass
