import os
import shutil
import uuid
from playwright.async_api import async_playwright


async def record_app(app_url: str) -> str:
    """Record the app using Playwright and return the video path."""
    
    recording_dir = f"/tmp/rec_{uuid.uuid4().hex}"
    os.makedirs(recording_dir, exist_ok=True)
    output_path = f"/tmp/screen_{uuid.uuid4().hex}.mp4"
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                ]
            )
            
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=recording_dir,
                record_video_size={"width": 1280, "height": 720},
            )
            
            page = await context.new_page()
            
            try:
                # Navigate to the app
                await page.goto(app_url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(2000)
                
                # Try clicking first nav link
                nav_link = page.locator("nav a").first
                if await nav_link.count() > 0:
                    await nav_link.click()
                    await page.wait_for_timeout(2000)
                    await page.go_back()
                    await page.wait_for_timeout(1000)
                
                # Try clicking first button
                button = page.locator("button").first
                if await button.count() > 0:
                    await button.click()
                    await page.wait_for_timeout(2000)
                
                await page.wait_for_timeout(1000)
                
            except Exception as e:
                raise RuntimeError(f"Error interacting with page: {str(e)}")
            
            # Close and finalize video
            video = page.video
            await context.close()
            await browser.close()
            
            # Get recorded video path
            recorded_path = await video.path()
            
            # Move to output path
            shutil.move(str(recorded_path), output_path)
            
            # Clean up recording dir
            shutil.rmtree(recording_dir, ignore_errors=True)
            
            return output_path
    
    except Exception as e:
        shutil.rmtree(recording_dir, ignore_errors=True)
        raise RuntimeError(f"Screen recording failed: {str(e)}")
