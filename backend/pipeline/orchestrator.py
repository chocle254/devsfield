import os
import shutil
from typing import Optional

from models import GenerateRequest
from jobs import (
    set_step, complete_step, fail_job, complete_job,
    add_tmp_file, get_tmp_files
)

from . import github_reader, app_browser, script_writer, image_generator
from . import voice_generator, video_assembler, storage


async def run_pipeline(job_id: str, request: GenerateRequest) -> None:
    """Run the complete demo video generation pipeline."""
    try:
        # Step 1: Read GitHub repo
        await set_step(job_id, "github_reader", "Reading your repository...")
        context = await github_reader.read_repo(request.github_url)
        await complete_step(job_id, "github_reader")
        
        # Step 2: Record app
        await set_step(job_id, "app_browser", "Recording your live app...")
        recording_path = await app_browser.record_app(request.app_url)
        await add_tmp_file(job_id, recording_path)
        await complete_step(job_id, "app_browser")
        
        # Step 3: Write script
        await set_step(job_id, "script_writer", "Writing your narration script...")
        script = await script_writer.write_script(
            context, request.tone, request.video_length
        )
        await complete_step(job_id, "script_writer")
        
        # Step 4: Generate title card
        await set_step(job_id, "image_generator", "Generating title card...")
        title_card_path: Optional[str] = await image_generator.generate_title_card(
            context["repo_name"], context["description"], job_id
        )
        if title_card_path is not None:
            await add_tmp_file(job_id, title_card_path)
        await complete_step(job_id, "image_generator")
        
        # Step 5: Generate voiceover
        await set_step(job_id, "voice_generator", "Generating voiceover...")
        voiceover_path = await voice_generator.generate_voice(script, job_id)
        await add_tmp_file(job_id, voiceover_path)
        await complete_step(job_id, "voice_generator")
        
        # Step 6: Assemble video
        await set_step(job_id, "video_assembler", "Compositing final video...")
        final_video_path = await video_assembler.assemble(
            recording_path, voiceover_path, title_card_path, job_id
        )
        await add_tmp_file(job_id, final_video_path)
        await complete_step(job_id, "video_assembler")
        
        # Step 7: Upload to storage
        await set_step(job_id, "storage", "Uploading to Backblaze B2...")
        result = await storage.upload_all(job_id, final_video_path, script)
        await complete_step(job_id, "storage")
        
        # Mark job as complete
        await complete_job(job_id, result)
        
    except Exception as e:
        await fail_job(job_id, str(e))
    
    finally:
        # Clean up temporary files
        tmp_files = await get_tmp_files(job_id)
        for file_path in tmp_files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path, ignore_errors=True)
            except Exception:
                pass
