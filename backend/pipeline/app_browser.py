"""
Plan-guided app navigation with segment timestamp tracking.

Key behaviors:
- Follows the repo-aware demo plan (beats), in priority order.
- Hard time budget derived from the requested video length. If pages load
  slowly (bad network, cold serverless starts), lower-priority beats are
  dropped instead of blowing the budget.
- Loading dead-time never appears in the final video: each segment's clock
  starts only AFTER the page has finished loading, so spinner time falls
  between segments and is cut during assembly.
- Optional login: if the developer supplied demo credentials, the browser
  detects the login form, fills it, and submits before demoing gated features.
- Every segment records an "observation" — what was actually visible on
  screen (title, headings, visible text) — so the narration can describe
  exactly what the viewer is seeing, not what a script guessed.
"""
import hashlib
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urldefrag

import httpx
from playwright.async_api import async_playwright

from jobs import add_snapshot, add_tmp_file

GMI_CHAT_URL = "https://api.gmi-serving.com/v1/chat/completions"
NAV_MODEL = "deepseek-ai/DeepSeek-V3-0324"

# How long we're willing to wait for a page before moving on (slow networks)
GOTO_TIMEOUT_MS = 25000
SETTLE_TIMEOUT_MS = 6000
ACTION_TIMEOUT_MS = 5000

# Minimum leftover budget worth starting another beat with
MIN_BEAT_SECONDS = 8


async def _safe_goto(page, url: str) -> bool:
    """Navigate with slow-network tolerance. Returns True on success."""
    try:
        await page.goto(url, wait_until="domcontentloaded",
                        timeout=GOTO_TIMEOUT_MS)
    except Exception:
        return False
    # Best-effort settle; never let a chatty page (websockets, analytics)
    # hold us hostage waiting for networkidle.
    try:
        await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
    except Exception:
        pass
    return True


async def _capture_snapshot(page, job_id: str, capture_state: dict) -> None:
    """Capture a safe, deduplicated page preview without blocking the run."""
    snapshot_id = uuid.uuid4().hex
    file_path = f"/tmp/snapshot_{job_id}_{snapshot_id}.jpg"

    try:
        # Playwright masks matching elements in the image itself. Values never
        # enter metadata or the SSE payload.
        sensitive_fields = page.locator(
            "input[type='password'], input[name*='password' i], "
            "input[name*='secret' i], input[name*='token' i], "
            "input[type='email'], input[name*='email' i], "
            "input[name*='user' i], input[autocomplete='username'], "
            "input[autocomplete='current-password'], "
            "input[autocomplete='new-password']"
        )
        await page.screenshot(
            path=file_path,
            type="jpeg",
            quality=65,
            full_page=False,
            animations="disabled",
            caret="hide",
            mask=[sensitive_fields],
        )

        with open(file_path, "rb") as image_file:
            content_hash = hashlib.sha256(image_file.read()).hexdigest()
        normalized_url = urldefrag(page.url)[0].rstrip("/") or page.url

        if (capture_state.get("url") == normalized_url and
                capture_state.get("content_hash") == content_hash):
            os.remove(file_path)
            return

        try:
            title = (await page.title()).strip()
        except Exception:
            title = ""

        snapshot = {
            "id": snapshot_id,
            "url": normalized_url,
            "title": title or "Loaded page",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "image_url": f"/snapshot/{job_id}/{snapshot_id}",
            "file_path": file_path,
            "content_hash": content_hash,
        }
        await add_snapshot(job_id, snapshot)
        await add_tmp_file(job_id, file_path)
        capture_state.update({"url": normalized_url, "content_hash": content_hash})
    except Exception:
        # Visual proof is additive; a screenshot failure must never fail video
        # generation or expose browser internals to the user.
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except OSError:
            pass


async def _observe(page) -> dict:
    """Capture what's actually visible on screen right now."""
    observation = {"url": page.url, "title": "", "headings": [], "visible_text": ""}
    try:
        observation["title"] = await page.title()
    except Exception:
        pass
    try:
        observation["headings"] = await page.evaluate(
            """() => Array.from(document.querySelectorAll('h1, h2'))
                 .slice(0, 6)
                 .map(h => h.innerText.trim())
                 .filter(Boolean)"""
        )
    except Exception:
        pass
    try:
        text = await page.evaluate(
            """() => {
                 const el = document.querySelector('main') || document.body;
                 return el ? el.innerText.slice(0, 600) : '';
               }"""
        )
        observation["visible_text"] = " ".join((text or "").split())[:500]
    except Exception:
        pass
    return observation


async def _attempt_login(page, app_url: str, credentials: dict,
                         job_id: str, capture_state: dict) -> bool:
    """
    Find and complete a login form using developer-supplied credentials.
    Returns True if a login was submitted.
    """
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    if not username or not password:
        return False

    # If there's no password field on the current page, try common login routes
    async def has_password_field() -> bool:
        try:
            return await page.locator("input[type='password']").count() > 0
        except Exception:
            return False

    if not await has_password_field():
        for path in ("/login", "/signin", "/sign-in", "/auth/login", "/auth/signin"):
            if await _safe_goto(page, app_url.rstrip("/") + path):
                await _capture_snapshot(page, job_id, capture_state)
                if await has_password_field():
                    break
        else:
            return False
        if not await has_password_field():
            return False

    try:
        # Username / email field: first visible non-password text-like input
        user_input = page.locator(
            "input[type='email'], input[name*='email' i], "
            "input[name*='user' i], input[type='text']"
        ).first
        await user_input.fill(username, timeout=ACTION_TIMEOUT_MS)

        await page.locator("input[type='password']").first.fill(
            password, timeout=ACTION_TIMEOUT_MS)

        # Submit: prefer an explicit submit button, fall back to Enter
        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Log in'), button:has-text('Login'), "
            "button:has-text('Sign in'), button:has-text('Sign In')"
        ).first
        if await submit.count() > 0:
            await submit.click(timeout=ACTION_TIMEOUT_MS)
        else:
            await page.keyboard.press("Enter")

        # Wait for the app to react (redirect, dashboard load) — capped.
        try:
            await page.wait_for_load_state("networkidle",
                                           timeout=SETTLE_TIMEOUT_MS)
        except Exception:
            await page.wait_for_timeout(2000)
        await _capture_snapshot(page, job_id, capture_state)
        return True
    except Exception:
        return False


async def _get_next_action(observation: dict, beat: dict, actions_taken: list,
                           seconds_left: float, app_summary: str) -> dict:
    """Ask the LLM for the single best next micro-action within this beat."""
    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    default = {"action": "scroll", "selector": None, "value": None,
               "reason": beat.get("talking_point", ""), "beat_complete": False}
    if not gmi_api_key:
        return default

    user_prompt = f"""You are driving a live browser to record a demo video.

App: {app_summary}
Current demo beat (what this part of the video must show):
- Feature: {beat.get('feature')}
- Goal on screen: {beat.get('actions_hint')}
- Talking point: {beat.get('talking_point')}
- Seconds left for this beat: {int(seconds_left)}

What is currently visible:
- URL: {observation.get('url')}
- Page title: {observation.get('title')}
- Headings: {json.dumps(observation.get('headings', []))}
- Visible text: {observation.get('visible_text', '')[:400]}

Actions already taken in this beat:
{json.dumps(actions_taken[-4:], indent=2)}

Choose ONE next action that best shows this beat's feature on camera.
Rules:
- Prefer visible, meaningful interactions (clicking primary buttons,
  typing realistic sample data, scrolling to reveal content).
- Never open external links, settings, or destructive actions
  (delete/remove/sign out).
- Set "beat_complete": true when this beat's goal has been shown.

Return ONLY valid JSON:
{{
  "action": "click" | "type" | "scroll" | "wait",
  "selector": "CSS selector or role hint like button[name='Add'] — null for scroll/wait",
  "value": "text to type, else null",
  "reason": "what the viewer is seeing (one sentence)",
  "beat_complete": true | false
}}"""

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                GMI_CHAT_URL,
                headers={"Authorization": f"Bearer {gmi_api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": NAV_MODEL,
                    "messages": [
                        {"role": "system", "content":
                         "You are an expert product demo director driving a "
                         "browser. Respond ONLY with valid JSON."},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 400,
                },
            )
        if response.status_code != 200:
            return default
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return json.loads(content.strip())
    except Exception:
        return default


async def _perform_action(page, decision: dict) -> bool:
    """Execute a micro-action. Returns True only if its effect on the page
    could be confirmed — a click that didn't error but also didn't change
    anything (checkbox state, DOM) counts as a failure, not a success."""
    action = decision.get("action", "wait")
    selector = decision.get("selector")
    value = decision.get("value")

    try:
        if action == "click" and selector:
            locator = None
            if "name='" in selector:
                role = selector.split("[")[0]
                name = selector.split("name='")[1].rstrip("']")
                candidate = page.get_by_role(role, name=name)
                if await candidate.count() > 0:
                    locator = candidate.first
            if locator is None:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    return False

            input_type = None
            try:
                input_type = await locator.get_attribute("type")
            except Exception:
                pass

            if input_type in ("checkbox", "radio"):
                # Checkboxes need their own success check: a click can land
                # without ever toggling the underlying `checked` property.
                before = await locator.is_checked()
                await locator.check(timeout=ACTION_TIMEOUT_MS)
                after = await locator.is_checked()
                return after and after != before

            await locator.click(timeout=ACTION_TIMEOUT_MS)
            return True

        elif action == "type" and value:
            if selector:
                try:
                    await page.fill(selector, value, timeout=ACTION_TIMEOUT_MS)
                    return True
                except Exception:
                    pass
            locator = page.get_by_role("textbox")
            if await locator.count() > 0:
                await locator.first.fill(value, timeout=ACTION_TIMEOUT_MS)
                return True
            return False

        elif action == "scroll":
            await page.evaluate("window.scrollBy({top: 450, behavior: 'smooth'})")
            return True

        return False  # "wait" — no state change expected
    except Exception:
        return False


async def record_app(app_url: str, repo_context: dict = None,
                     demo_plan: dict = None, credentials: dict = None,
                     video_length: int = 180, job_id: str = "") -> dict:
    """
    Record the app following the demo plan, tracking segment timestamps.

    Returns:
        {
          "video_path": str,
          "segments": [
            {"segment_id": 1, "start_time": 0.0, "end_time": 12.4,
             "feature": "...", "talking_point": "...", "action": "...",
             "reason": "...", "observation": {...}},
            ...
          ]
        }
    """
    if repo_context is None:
        repo_context = {"description": "", "framework": "", "readme": ""}
    if demo_plan is None:
        demo_plan = {"beats": [], "needs_login": False,
                     "app_summary": repo_context.get("description", "")}

    beats = demo_plan.get("beats") or [{
        "priority": 1, "feature": "App overview", "route": "/",
        "actions_hint": "Scroll through the landing page.",
        "talking_point": "What the app is.", "seconds": 30,
    }]
    app_summary = demo_plan.get("app_summary", "")

    # Total wall-clock budget for on-camera time. Loading time is excluded
    # from segments, but still consumes real time — so we track both.
    camera_budget = max(30, video_length - 6)
    # Never let the whole recording session (including slow loads) run more
    # than 2x the camera budget — that's the slow-network kill switch.
    session_budget = camera_budget * 2

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

            recording_start = time.monotonic()
            camera_used = 0.0  # seconds of actual on-camera segment time
            capture_state: dict = {}

            def elapsed() -> float:
                return time.monotonic() - recording_start

            if not await _safe_goto(page, app_url):
                raise RuntimeError(
                    f"Could not load {app_url} — the app did not respond "
                    "within the timeout. Is the deployment up?")
            if job_id:
                await _capture_snapshot(page, job_id, capture_state)

            # Optional login before demoing (kept OUT of segments — viewers
            # don't need to watch credentials being typed).
            if demo_plan.get("needs_login") and credentials:
                await _attempt_login(
                    page, app_url, credentials, job_id, capture_state)
                # Return to home so beat 1 starts where the plan expects.
                if await _safe_goto(page, app_url) and job_id:
                    await _capture_snapshot(page, job_id, capture_state)

            segment_id = 0
            for beat in beats:
                beat_seconds = beat.get("seconds", 20)
                camera_left = camera_budget - camera_used
                if camera_left < MIN_BEAT_SECONDS or elapsed() > session_budget:
                    break  # out of time — drop remaining (lower priority) beats
                beat_seconds = min(beat_seconds, camera_left)

                # Navigate to the beat's route (loading time NOT on camera:
                # the segment clock starts after the page settles).
                route = beat.get("route") or "/"
                target = (app_url.rstrip("/") + route) if route != "/" else app_url
                current_path = page.url.rstrip("/")
                if current_path != target.rstrip("/"):
                    if not await _safe_goto(page, target):
                        continue  # page too slow or broken — skip this beat
                    if job_id:
                        await _capture_snapshot(page, job_id, capture_state)

                beat_camera_start = elapsed()
                actions_taken = []
                max_actions = 6

                for _ in range(max_actions):
                    beat_camera_used = elapsed() - beat_camera_start
                    seconds_left = beat_seconds - beat_camera_used
                    if seconds_left < 3 or elapsed() > session_budget:
                        break

                    segment_start = elapsed()
                    observation = await _observe(page)
                    decision = await _get_next_action(
                        observation, beat, actions_taken, seconds_left,
                        app_summary)

                    url_before_action = urldefrag(page.url)[0]
                    await _perform_action(page, decision)

                    # Let the result of the action settle and be visible on
                    # camera long enough for the viewer to read/absorb it.
                    await page.wait_for_timeout(4000)
                    url_after_action = urldefrag(page.url)[0]
                    if job_id and url_after_action != url_before_action:
                        try:
                            await page.wait_for_load_state(
                                "domcontentloaded", timeout=SETTLE_TIMEOUT_MS)
                        except Exception:
                            pass
                        await _capture_snapshot(page, job_id, capture_state)

                    post_observation = await _observe(page)
                    segment_end = elapsed()
                    segment_id += 1
                    segments.append({
                        "segment_id": segment_id,
                        "start_time": round(segment_start, 2),
                        "end_time": round(segment_end, 2),
                        "feature": beat.get("feature", ""),
                        "talking_point": beat.get("talking_point", ""),
                        "action": decision.get("action", "wait"),
                        "reason": decision.get("reason", ""),
                        "observation": post_observation,
                    })
                    actions_taken.append({
                        "action": decision.get("action"),
                        "selector": decision.get("selector"),
                        "reason": decision.get("reason", ""),
                    })

                    if decision.get("beat_complete"):
                        break

                camera_used += elapsed() - beat_camera_start

            # Small tail so the last frame isn't cut mid-motion
            await page.wait_for_timeout(1500)

            video = page.video
            await context.close()
            await browser.close()

            recorded_path = await video.path()
            shutil.move(str(recorded_path), output_path)
            shutil.rmtree(recording_dir, ignore_errors=True)

            if not segments:
                segments = [{
                    "segment_id": 1, "start_time": 0.0, "end_time": None,
                    "feature": "App overview", "talking_point": "",
                    "action": "view", "reason": "App overview",
                    "observation": {},
                }]

            return {"video_path": output_path, "segments": segments}

    except Exception as e:
        shutil.rmtree(recording_dir, ignore_errors=True)
        raise RuntimeError(f"Screen recording failed: {str(e)}")
