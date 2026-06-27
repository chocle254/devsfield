"""
Video composition: screenshot capture and FFmpeg assembly
"""
import asyncio
import os
import subprocess
import tempfile
from typing import Optional

from playwright.async_api import async_playwright


async def capture_screenshot(prompt: str, output_path: str) -> str:
    """
    Capture a screenshot using Playwright and a local HTML render.
    
    In a real implementation, this would use an image generation API
    or render HTML dynamically. For now, create a simple HTML page
    and screenshot it.
    
    Args:
        prompt: Description of what should appear in the screenshot
        output_path: Where to save the screenshot
        
    Returns:
        Path to the screenshot file
    """
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Screenshot</title>
        <style>
            body {{
                margin: 0;
                padding: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                color: white;
            }}
            .content {{
                text-align: center;
                padding: 40px;
                background: rgba(0, 0, 0, 0.2);
                border-radius: 10px;
                max-width: 80%;
            }}
            h1 {{
                font-size: 3em;
                margin: 0 0 20px 0;
            }}
            p {{
                font-size: 1.5em;
                margin: 0;
                opacity: 0.9;
            }}
        </style>
    </head>
    <body>
        <div class="content">
            <h1>Video Scene</h1>
            <p>{prompt}</p>
        </div>
    </body>
    </html>
    """
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--disable-dev-shm-usage", "--no-sandbox"]
        )
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        # Write HTML to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(html_content)
            html_file = f.name
        
        try:
            await page.goto(f"file://{html_file}", wait_until="networkidle")
            await page.screenshot(path=output_path)
        finally:
            await browser.close()
            os.unlink(html_file)
    
    return output_path


async def capture_all_screenshots(scenes: list[dict]) -> dict[int, str]:
    """
    Capture screenshots for all scenes.
    
    Args:
        scenes: List of scene dicts with 'screenshot_prompt' keys
        
    Returns:
        Dict mapping scene index to screenshot path
    """
    screenshots = {}
    
    for i, scene in enumerate(scenes):
        prompt = scene.get("screenshot_prompt", "Scene " + str(i + 1))
        output_path = f"/tmp/screenshot_scene_{i}.png"
        
        try:
            path = await capture_screenshot(prompt, output_path)
            screenshots[i] = path
        except Exception as e:
            raise RuntimeError(f"Failed to capture screenshot for scene {i}: {str(e)}")
    
    return screenshots


def assemble_video(
    scenes: list[dict],
    screenshots: dict[int, str],
    audio_files: dict[int, str],
    output_path: str,
) -> str:
    """
    Assemble video from screenshots and audio using FFmpeg.
    
    Args:
        scenes: List of scene dicts with 'duration' keys
        screenshots: Dict mapping scene index to screenshot path
        audio_files: Dict mapping scene index to audio file path
        output_path: Where to save the final video
        
    Returns:
        Path to the final video file
    """
    # Create an FFmpeg concat file with all scenes
    concat_file = "/tmp/concat.txt"
    audio_files_list = []
    total_duration = 0
    
    with open(concat_file, "w") as f:
        for i, scene in enumerate(scenes):
            screenshot = screenshots.get(i)
            audio_file = audio_files.get(i)
            duration = scene.get("duration", 10)
            total_duration += duration
            
            if screenshot:
                f.write(f"file '{screenshot}'\n")
                f.write(f"duration {duration}\n")
                audio_files_list.append(audio_file)
    
    # Concatenate all audio files
    combined_audio = "/tmp/combined_audio.mp3"
    if audio_files_list:
        concat_audio_file = "/tmp/concat_audio.txt"
        with open(concat_audio_file, "w") as f:
            for audio_file in audio_files_list:
                if audio_file and os.path.exists(audio_file):
                    f.write(f"file '{audio_file}'\n")
        
        # Use FFmpeg to concatenate audio
        subprocess.run(
            [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_audio_file,
                "-c", "copy",
                combined_audio,
            ],
            check=True,
            capture_output=True,
        )
    
    # Create video from screenshots with audio
    cmd = [
        "ffmpeg",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
    ]
    
    if os.path.exists(combined_audio):
        cmd.extend(["-i", combined_audio, "-c:a", "aac", "-shortest"])
    
    cmd.append(output_path)
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr}")
    
    # Cleanup temp files
    for i in range(len(scenes)):
        screenshot = screenshots.get(i)
        if screenshot and os.path.exists(screenshot):
            os.unlink(screenshot)
        audio_file = audio_files.get(i)
        if audio_file and os.path.exists(audio_file):
            os.unlink(audio_file)
    
    if os.path.exists(combined_audio):
        os.unlink(combined_audio)
    os.unlink(concat_file)
    if os.path.exists(concat_audio_file):
        os.unlink(concat_audio_file)
    
    return output_path
