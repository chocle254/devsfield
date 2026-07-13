import os
import shutil
from typing import Optional

from models import GenerateRequest
from jobs import set_step, complete_step, fail_job, complete_job, add_tmp_file, get_tmp_files
from . import github_reader, demo_planner, app_browser, script_writer, image_generator
from . import voice_generator, video_assembler, storage


async def run_pipeline(job_id: str, request: GenerateRequest) -> None:
    try:
        credentials = None
        if request.credentials is not None:
            credentials = {
                "username": request.credentials.username,
                "password": request.credentials.password,
            }

        await set_step(job_id, "github_reader",
                       "Reading your repository and planning the demo...")
        context = await github_reader.read_repo(request.github_url)
        # Repo-aware plan: which features to show, in what order, with a
        # per-beat time budget that fits the requested video length.
        plan = await demo_planner.plan_demo(
            context, request.video_length, has_credentials=credentials is not None)
        await complete_step(job_id, "github_reader")

        await set_step(job_id, "app_browser", "Recording your live app...")
        recording = await app_browser.record_app(
            request.app_url, context,
            demo_plan=plan, credentials=credentials,
            video_length=request.video_length, job_id=job_id)
        await add_tmp_file(job_id, recording["video_path"])
        await complete_step(job_id, "app_browser")

        await set_step(job_id, "script_writer", "Writing narration for each segment...")
        script_segments = await script_writer.write_segmented_script(
            context, recording["segments"], request.tone)
        await complete_step(job_id, "script_writer")

        await set_step(job_id, "image_generator", "Generating title card...")
        title_card_path: Optional[str] = await image_generator.generate_title_card(
            context["repo_name"], context["description"], job_id)
        if title_card_path is not None:
            await add_tmp_file(job_id, title_card_path)
        await complete_step(job_id, "image_generator")

        await set_step(job_id, "voice_generator", "Generating voiceover per segment...")
        voiced_segments = await voice_generator.generate_segment_voices(
            script_segments, job_id, tone=request.tone)
        for seg in voiced_segments:
            await add_tmp_file(job_id, seg["audio_path"])
        await complete_step(job_id, "voice_generator")

        await set_step(job_id, "video_assembler", "Compositing final video...")
        assembly = await video_assembler.assemble(
            recording["video_path"], voiced_segments, title_card_path, job_id)
        await add_tmp_file(job_id, assembly["final_video_path"])
        for clip in assembly["segment_clips"]:
            await add_tmp_file(job_id, clip["clip_path"])
            await add_tmp_file(job_id, clip["merged_path"])
        await complete_step(job_id, "video_assembler")

        await set_step(job_id, "storage", "Uploading to Backblaze B2...")
        result = await storage.upload_all(
            job_id, assembly["final_video_path"], assembly["segment_clips"])
        await complete_step(job_id, "storage")

        await complete_job(job_id, result)

    except Exception as e:
        await fail_job(job_id, str(e))

    finally:
        tmp_files = await get_tmp_files(job_id)
        for file_path in tmp_files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
            except Exception:
                pass
