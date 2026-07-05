"""
AI-guided intelligent app navigation with segment timestamp tracking.
"""
import json
import os
import shutil
import time
import uuid

import httpx
from playwright.async_api import async_playwright


async def get_next_action(page_snapshot, repo_context, actions_taken, step_number):
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        return {"action": "wait", "selector": None, "value": None,
                "reason": "no API key", "done": False}

    system_prompt = (
        "You are an expert product demo director. Your job is to navigate "
        "a web app to show its most impressive features for a demo video. "
        "Decide the single best next action based on the accessibility tree "
        "and README context. Be deliberate. Avoid settings pages, auth "
        "flows unless login is the feature, and error states."
    )

    snapshot_json = json.dumps(page_snapshot, indent=2)[:3000]
    readme_snippet = (repo_context.get("readme") or "")[:1000]

    user_prompt = f"""App description: {repo_context.get('description', '')}
Framework: {repo_context.get('framework', 'Unknown')}
README summary: {readme_snippet}

Current page accessibility tree:
{snapshot_json}

Actions already taken:
{json.dumps(actions_taken, indent=2)}

Step {step_number} of maximum 8 steps.

Return ONLY valid JSON:
{{
  "action": "click" | "type" | "scroll" | "wait" | "navigate" | "done",
  "selector": "role and name e.g. button[name='Sign In']",
  "value": "text to type or URL, else null",
  "reason": "one sentence explaining why this shows a good feature",
  "done": true | false
}}
Never return done on step 1. Return ONLY the JSON object."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.gmi-serving.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {gmi_api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": "deepseek-ai/DeepSeek-V3-0324",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500,
                },
            )
        if response.status_code != 200:
            return {"action": "wait", "selector": None, "value": None,
                    "reason": "LLM call failed", "done": False}

        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())
    except Exception:
        return {"action": "wait", "selector": None, "value": None,
                "reason": "parse error", "done": False}


async def record_app(app_url: str, repo_context: dict = None) -> dict:
    """
    Record the app with AI-guided navigation, tracking segment timestamps.

    Returns:
        {
          "video_path": str,           # full continuous recording
          "segments": [
            {"segment_id": 1, "start_time": 0.0, "end_time": 4.2,
             "action": "click", "reason": "..."},
            ...
          ]
        }
    """
    if repo_context is None:
        repo_context = {"description": "", "framework": "", "readme": ""}

    recording_dir = f"/tmp/rec_{uuid.uuid4().hex}"
    os.makedirs(recording_dir, exist_ok=True)
    output_path = f"/tmp/screen_{uuid.uuid4().hex}.mp4"
    segments = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox",
                      "--disable-gpu", "--disable-software-rasterizer"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=recording_dir,
                record_video_size={"width": 1280, "height": 720},
            )
            page = await context.new_page()

            try:
                recording_start = time.monotonic()
                await page.goto(app_url, wait_until="networkidle", timeout=90000)
                await page.wait_for_timeout(2000)

                actions_taken = []
                max_steps = 8

                for step in range(max_steps):
                    segment_start = time.monotonic() - recording_start
                    try:
                        snapshot = await page.accessibility.snapshot()
                        if snapshot is None:
                            break

                        decision = await get_next_action(
                            snapshot, repo_context, actions_taken, step + 1
                        )

                        if decision.get("done"):
                            await page.wait_for_timeout(1500)
                            break

                        action_type = decision.get("action", "wait")
                        selector = decision.get("selector")
                        value = decision.get("value")

                        if action_type == "click" and selector:
                            try:
                                if "name='" in selector:
                                    role = selector.split("[")[0]
                                    name = selector.split("name='")[1].rstrip("']")
                                    locator = page.get_by_role(role, name=name)
                                    if await locator.count() > 0:
                                        await locator.first.click(timeout=5000)
                                    else:
                                        await page.click(selector, timeout=5000)
                                else:
                                    await page.click(selector, timeout=5000)
                            except Exception:
                                pass

                        elif action_type == "type" and value:
                            try:
                                locator = page.get_by_role("textbox")
                                if await locator.count() > 0:
                                    await locator.first.fill(value, timeout=5000)
                            except Exception:
                                pass

                        elif action_type == "scroll":
                            await page.evaluate("window.scrollBy(0, 400)")

                        elif action_type == "navigate" and value:
                            try:
                                target = value if value.startswith("http") else (
                                    app_url.rstrip("/") + "/" + value.lstrip("/"))
                                await page.goto(target, wait_until="networkidle", timeout=30000)
                            except Exception:
                                pass

                        elif action_type == "wait":
                            await page.wait_for_timeout(2000)

                        await page.wait_for_timeout(2000)

                        segment_end = time.monotonic() - recording_start
                        segments.append({
                            "segment_id": step + 1,
                            "start_time": round(segment_start, 2),
                            "end_time": round(segment_end, 2),
                            "action": action_type,
                            "reason": decision.get("reason", ""),
                        })
                        actions_taken.append({
                            "step": step + 1, "action": action_type,
                            "selector": selector, "reason": decision.get("reason", ""),
                        })

                    except Exception:
                        await page.wait_for_timeout(1000)
                        continue

                await page.wait_for_timeout(2000)

            except Exception as e:
                raise RuntimeError(f"Error interacting with page: {str(e)}")

            video = page.video
            await context.close()
            await browser.close()

            recorded_path = await video.path()
            shutil.move(str(recorded_path), output_path)
            shutil.rmtree(recording_dir, ignore_errors=True)

            # If nothing was captured, make one segment covering the whole video
            if not segments:
                segments = [{"segment_id": 1, "start_time": 0.0, "end_time": None,
                             "action": "view", "reason": "App overview"}]

            return {"video_path": output_path, "segments": segments}

    except Exception as e:
        shutil.rmtree(recording_dir, ignore_errors=True)
        raise RuntimeError(f"Screen recording failed: {str(e)}")
