import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


async def generate_title_card(repo_name: str, description: str, job_id: str) -> Optional[str]:
    """Generate a title card image. Non-fatal if it fails."""
    
    try:
        gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
        if not gmi_api_key:
            logger.warning("GMI_CLOUD_API_KEY not set, skipping title card")
            return None
        
        # Build prompt
        prompt = f"Clean modern tech startup title card for '{repo_name}'. Dark background, teal accent color #00FFB2, minimal design, professional, 16:9 aspect ratio, white text. No people. Abstract geometric shapes."
        
        # Call GMI Cloud image generation
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.gmi-serving.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {gmi_api_key}",
                },
                json={
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "prompt": prompt,
                    "n": 1,
                    "size": "1280x720"
                }
            )
            
            if response.status_code != 200:
                logger.warning(f"Image generation failed: {response.status_code}")
                return None
            
            # Extract image URL
            image_url = response.json()["data"][0]["url"]
            
            # Download the image
            async with httpx.AsyncClient() as client:
                img_response = await client.get(image_url, timeout=30.0)
            
            image_path = f"/tmp/titlecard_{job_id}.png"
            with open(image_path, "wb") as f:
                f.write(img_response.content)
            
            return image_path
    
    except Exception as e:
        logger.error(f"Title card generation error: {str(e)}")
        return None
