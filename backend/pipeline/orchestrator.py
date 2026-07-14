import os
import shutil
from typing import Optional

from models import GenerateRequest
from jobs import (
    set_step,
    complete_step,
    fail_job,
    complete_job,
    add_tmp_file,
    get_tmp_files,
    get_job,
    save_checkpoint,
    set_resume_state,
)
from . import github_reader, demo_planner, app_browser, script_writer, image_generator
from . import voice_generator, video_assembler, storage, resume_store


async def _advance(job_id: str, step: str) -> None:
    """Mark a step complete and mirror the new checkpoint to durable storage.

    Persistence is best-effort: a B2 hiccup must never fail a generation that
    otherwise succeeded — it only means that particular checkpoint won't be
    resumable after a redeploy.
    """
    await complete_step(job_id, step)
    try:
        await resume_store.persist(job_id)
    except Exception:
        pass


async def run_pipeline(job_id: str, request: GenerateRequest) -> None:
    """Run the full generation pipeline for a job.

    The pipeline is resumable: each step's output is checkpointed as soon as it
    completes. If the job previously failed and is retried, any step already in
    `steps_completed` is skipped and its cached output is reused, so generation
    continues from the exact step that broke instead of starting over.
    """
    try:
        job = await get_job(job_id) or {}

        # Resume safety net: a completed step is only trustworthy if its
        # checkpoint metadata AND the files it produced are actually present.
        # After a redeploy that wiped local disk (even with artifacts pulled
        # back from B2), anything that couldn't be restored is dropped here so
        # we re-run cleanly from the earliest gap instead of crashing on a
        # missing file. Resume as far as possible, else restart cleanly.
        kept_steps, kept_ckpt = resume_store.validate_checkpoints(
            job.get("steps_completed", []), job.get("checkpoints", {}))
        if kept_steps != job.get("steps_completed", []):
            await set_resume_state(job_id, kept_steps, kept_ckpt)

        completed = set(kept_steps)
        ckpt = dict(kept_ckpt)

        credentials = None
        if request.credentials is not None:
            credentials = {
                "username": request.credentials.username,
                "password": request.credentials.password,
            }

        # 1. Read repo + plan the demo
        if "github_reader" in completed and "context" in ckpt and "plan" in ckpt:
            context = ckpt["context"]
            plan = ckpt["plan"]
        else:
            await set_step(job_id, "github_reader",
                           "Reading your repository and planning the demo...")
            context = await github_reader.read_repo(request.github_url)
            # Repo-aware plan: which features to show, in what order, with a
            # per-beat time budget that fits the requested video length.
            plan = await demo_planner.plan_demo(
                context, request.video_length, has_credentials=credentials is not None)
            await save_checkpoint(job_id, "context", context)
            await save_checkpoint(job_id, "plan", plan)
            await _advance(job_id, "github_reader")

        # 2. Record the live app
        if "app_browser" in completed and "recording" in ckpt:
            recording = ckpt["recording"]
        else:
            await set_step(job_id, "app_browser", "Recording your live app...")
            recording = await app_browser.record_app(
                request.app_url, context,
                demo_plan=plan, credentials=credentials,
                video_length=request.video_length, job_id=job_id)
            await add_tmp_file(job_id, recording["video_path"])
            await save_checkpoint(job_id, "recording", recording)
            await _advance(job_id, "app_browser")

        # 3. Write the segmented narration script
        if "script_writer" in completed and "script_segments" in ckpt:
            script_segments = ckpt["script_segments"]
        else:
            await set_step(job_id, "script_writer", "Writing narration for each segment...")
            script_segments = await script_writer.write_segmented_script(
                context, recording["segments"], request.tone)
            await save_checkpoint(job_id, "script_segments", script_segments)
            await _advance(job_id, "script_writer")

        # 4. Generate the title card
        if "image_generator" in completed and "title_card_path" in ckpt:
            title_card_path = ckpt["title_card_path"]
        else:
            await set_step(job_id, "image_generator", "Generating title card...")
            title_card_path: Optional[str] = await image_generator.generate_title_card(
                context["repo_name"], context["description"], job_id)
            if title_card_path is not None:
                await add_tmp_file(job_id, title_card_path)
            await save_checkpoint(job_id, "title_card_path", title_card_path)
            await _advance(job_id, "image_generator")

        # 5. Generate per-segment voiceover
        if "voice_generator" in completed and "voiced_segments" in ckpt:
            voiced_segments = ckpt["voiced_segments"]
        else:
            await set_step(job_id, "voice_generator", "Generating voiceover per segment...")
            voiced_segments = await voice_generator.generate_segment_voices(
                script_segments, job_id, tone=request.tone)
            for seg in voiced_segments:
                await add_tmp_file(job_id, seg["audio_path"])
            await save_checkpoint(job_id, "voiced_segments", voiced_segments)
            await _advance(job_id, "voice_generator")

        # 6. Composite the final video
        if "video_assembler" in completed and "assembly" in ckpt:
            assembly = ckpt["assembly"]
        else:
            await set_step(job_id, "video_assembler", "Compositing final video...")
            assembly = await video_assembler.assemble(
                recording["video_path"], voiced_segments, title_card_path, job_id)
            await add_tmp_file(job_id, assembly["final_video_path"])
            for clip in assembly["segment_clips"]:
                await add_tmp_file(job_id, clip["clip_path"])
                await add_tmp_file(job_id, clip["merged_path"])
            await save_checkpoint(job_id, "assembly", assembly)
            await _advance(job_id, "video_assembler")

        # 7. Upload everything to Backblaze B2 (terminal step, no checkpoint)
        await set_step(job_id, "storage", "Uploading to Backblaze B2...")
        result = await storage.upload_all(
            job_id, assembly["final_video_path"], assembly["segment_clips"],
            request=request, duration_seconds=getattr(request, "video_length", None))
        await complete_step(job_id, "storage")

        await complete_job(job_id, result)

    except Exception as e:
        await fail_job(job_id, str(e))
        # Mirror the failed state (status + error + latest checkpoints) to B2
        # so the run can still be resumed after a backend redeploy.
        try:
            await resume_store.persist(job_id)
        except Exception:
            pass

    finally:
        # Only clean up temp files once the job has completed successfully. On
        # failure we keep the intermediate artifacts on disk so a retry can
        # resume from the step that broke instead of regenerating everything.
        job = await get_job(job_id)
        if job and job.get("status") == "complete":
            # The video is finished — drop the resume scratch on B2 so we only
            # ever retain intermediate artifacts for in-flight/failed runs.
            try:
                await resume_store.cleanup(job_id)
            except Exception:
                pass
            tmp_files = await get_tmp_files(job_id)
            for file_path in tmp_files:
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path, ignore_errors=True)
                except Exception:
                    pass
