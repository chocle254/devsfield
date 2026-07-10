"""
Repo-aware demo planning.

Before the browser ever opens, an LLM studies the repository (README, routes,
key files, auth setup) and produces a prioritized, time-budgeted "shot list"
of demo beats. The browser then follows this plan, and if time runs short
(slow network, slow pages), the lowest-priority beats are dropped — so the
video always fits the requested length and always leads with the best
features.
"""
import json
import os

import httpx

GMI_CHAT_URL = "https://api.gmi-serving.com/v1/chat/completions"
PLANNER_MODEL = "deepseek-ai/DeepSeek-V3-0324"

# Seconds reserved outside of screen recording (title card + concat buffer)
RESERVED_SECONDS = 6


def _fallback_plan(context: dict, usable_seconds: int) -> dict:
    """Deterministic plan when the LLM is unavailable: tour detected routes."""
    routes = context.get("detected_routes") or ["/"]
    beats = []
    per_beat = max(15, usable_seconds // max(1, min(len(routes), 5)))
    for i, route in enumerate(routes[:5]):
        beats.append({
            "priority": i + 1,
            "feature": f"Page {route}",
            "route": route,
            "actions_hint": "Scroll through the page and interact with the "
                            "primary visible control.",
            "talking_point": f"A look at the {route} page.",
            "seconds": per_beat,
        })
    return {
        "beats": beats,
        "needs_login": bool(context.get("has_auth")),
        "app_summary": context.get("description") or context.get("repo_name", ""),
    }


async def plan_demo(context: dict, video_length: int,
                    has_credentials: bool) -> dict:
    """
    Returns:
        {
          "beats": [
            {"priority": 1, "feature": str, "route": str,
             "actions_hint": str, "talking_point": str, "seconds": int},
            ...
          ],
          "needs_login": bool,
          "app_summary": str,
        }
    """
    usable_seconds = max(30, video_length - RESERVED_SECONDS)

    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    if not gmi_api_key:
        return _fallback_plan(context, usable_seconds)

    key_files_summary = "\n\n".join(
        f"--- {path} ---\n{content[:800]}"
        for path, content in (context.get("key_files") or {}).items()
    )

    user_prompt = f"""You are planning a screen-recorded demo video of a live web app.
Study the repository below and produce a prioritized shot list ("beats").

Project: {context['repo_name']}
Description: {context.get('description') or 'None provided'}
Framework: {context.get('framework', 'Unknown')}
Primary language: {context.get('language', 'Unknown')}

README:
{(context.get('readme') or '')[:2500]}

Detected user-facing routes (from the file tree — these pages really exist):
{json.dumps(context.get('detected_routes') or ['/'])}

Authentication detected: {context.get('has_auth', False)}
Auth hints: {json.dumps(context.get('auth_hints') or [])}
Login credentials provided by the developer: {has_credentials}

Key source files:
{key_files_summary[:2500]}

Constraints:
- Total screen time available: {usable_seconds} seconds. The sum of all beat
  "seconds" MUST NOT exceed {usable_seconds}.
- 3 to 6 beats. Priority 1 = the single most impressive feature — the one
  thing a viewer must see. Order beats by priority (most important first),
  because low-priority beats get dropped if pages load slowly.
- Beat 1 should establish what the app is (usually the landing/home page).
- Only use routes from the detected list, or "/" if unsure. Never invent routes.
- If auth is detected but no credentials were provided, plan only publicly
  accessible beats and never route into login-gated features.
- If credentials were provided, you may include one login beat early
  (priority 2 at most) so gated features can be shown afterward.
- "actions_hint" tells the browser driver what to do on that page in plain
  language (e.g. "type a sample task into the input and click Add").
- "talking_point" is the ONE idea the narration should land during this beat.

Return ONLY valid JSON:
{{
  "beats": [
    {{"priority": 1, "feature": "short name", "route": "/path",
      "actions_hint": "what to do on screen", "talking_point": "one idea",
      "seconds": 25}}
  ],
  "needs_login": true | false,
  "app_summary": "one-sentence summary of what this app does"
}}"""

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                GMI_CHAT_URL,
                headers={"Authorization": f"Bearer {gmi_api_key}",
                         "Content-Type": "application/json"},
                json={
                    "model": PLANNER_MODEL,
                    "messages": [
                        {"role": "system", "content":
                         "You are an expert product demo director. "
                         "Respond ONLY with valid JSON."},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 1500,
                },
            )
        if response.status_code != 200:
            return _fallback_plan(context, usable_seconds)

        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        plan = json.loads(content.strip())

        beats = plan.get("beats") or []
        if not beats:
            return _fallback_plan(context, usable_seconds)

        # Enforce the time budget server-side; never trust the LLM's math.
        beats.sort(key=lambda b: b.get("priority", 99))
        total = 0
        kept = []
        for beat in beats[:6]:
            seconds = max(10, min(60, int(beat.get("seconds", 20))))
            if total + seconds > usable_seconds:
                remaining = usable_seconds - total
                if remaining >= 10:
                    seconds = remaining
                else:
                    break
            beat["seconds"] = seconds
            total += seconds
            kept.append(beat)

        plan["beats"] = kept or _fallback_plan(context, usable_seconds)["beats"]
        plan["needs_login"] = bool(plan.get("needs_login")) and has_credentials
        plan.setdefault("app_summary",
                        context.get("description") or context.get("repo_name", ""))
        return plan

    except Exception:
        return _fallback_plan(context, usable_seconds)
