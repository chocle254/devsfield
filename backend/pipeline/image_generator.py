"""
Title card generation using genblaze-gmicloud (Seedream via GMI Cloud).
Non-fatal — pipeline continues without a title card if this fails.
"""
import os
import logging
from typing import Optional

from genblaze_core import Pipeline, Modality
from genblaze_gmicloud import GMICloudImageProvider

from .voice_generator import materialize_asset

logger = logging.getLogger(__name__)


async def generate_title_card(repo_name: str, description: str, job_id: str) -> Optional[str]:
    try:
        gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
        if not gmi_api_key:
            logger.warning("GMI_CLOUD_API_KEY not set, skipping title card")
            return None

        prompt = (
            f"Clean modern tech startup title card for '{repo_name}'. "
            f"Dark background, teal accent color #00FFB2, minimal design, "
            f"professional, 16:9 aspect ratio, white text. No people. "
            f"Abstract geometric shapes."
        )

        run, manifest = (
            Pipeline(f"devfields-titlecard-{job_id}")
            .step(
                GMICloudImageProvider(api_key=gmi_api_key),
                model="seedream-5.0-lite",
                prompt=prompt,
                modality=Modality.IMAGE,
            )
            .run(timeout=60)
        )

        step = run.steps[0]
        if step.status != "succeeded" or not step.assets:
            logger.warning(f"Title card generation failed: {step.error}")
            return None

        image_path = f"/tmp/titlecard_{job_id}.png"
        await materialize_asset(step.assets[0].url, image_path, timeout=30.0)

        return image_path

    except Exception as e:
        logger.error(f"Title card generation error: {str(e)}")
        return None
