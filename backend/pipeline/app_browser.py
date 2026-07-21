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
- Every action that's supposed to change the page (click, checkbox, type) is
  verified, not assumed. A click that throws no exception but also doesn't
  change anything (overlay, unbound JS, animation) is treated as a failure,
  the beat is ended early instead of burning its time budget on a stuck
  screen, and the failure is logged with enough detail to diagnose.
- Narration data ("observation") is captured AFTER an action is confirmed to
  have worked, never before — so the script never describes a page the
  recording hasn't actually reached yet.
- Goal-oriented account setup: if the developer supplied demo credentials,
  log in with them. If no credentials were supplied and the app requires an
  account, sign up as a brand-new user (temp inbox, consent checkboxes,
  email verification, onboarding wizard) so gated features can still be
  demoed instead of being skipped outright. If signup can't be confirmed
  within its budget, the agent falls back to demoing public pages only —
  it never guesses that a login succeeded.
- We never attempt to drive a third-party OAuth popup (Google/etc.) — it's
  closed and ignored if one appears.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urldefrag

import httpx
from playwright.async_api import async_playwright

from jobs import add_snapshot, add_tmp_file

logger = logging.getLogger(__name__)

GMI_CHAT_URL = "https://api.gmi-serving.com/v1/chat/completions"
NAV_MODEL = "deepseek-ai/DeepSeek-V3.2"
NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
VISION_NAV_MODEL = "qwen/qwen3.5-397b-a17b"

# How long we're willing to wait for a page before moving on (slow networks)
GOTO_TIMEOUT_MS = 25000
SETTLE_TIMEOUT_MS = 6000
ACTION_TIMEOUT_MS = 5000
INTERACTION_SETTLE_MS = 900
MAX_LIVE_CONTROLS = 36
SENSITIVE_FIELD_SELECTOR = (
    "input[type='password'], input[name*='password' i], "
    "input[name*='secret' i], input[name*='token' i], "
    "input[type='email'], input[name*='email' i], "
    "input[name*='user' i], input[autocomplete='username'], "
    "input[autocomplete='current-password'], "
    "input[autocomplete='new-password']"
)
# NVIDIA accepts inline images only below its documented 180 KB threshold.
# Keep the raw JPEG smaller so its base64 data URL remains safely inline.
MAX_INLINE_REASONING_FRAME_BYTES = 130 * 1024

# The model is allowed to demonstrate product workflows, not mutate account,
# billing, publishing, or other high-impact state.  Authentication has its own
# explicit, credential-gated path below and is never driven through this list.
UNSAFE_CONTROL_TERMS = {
    "delete", "remove", "destroy", "logout", "log out", "sign out",
    "unsubscribe", "billing", "checkout", "purchase", "pay now",
    "transfer", "withdraw", "deploy", "publish", "invite", "share",
    "password", "passcode", "secret", "token", "api key", "api-key",
    "credit card", "card number", "cvv", "email", "username", "user name",
    "phone", "settings", "profile",
}
SAFE_ACTIONS = {"click", "type", "select", "toggle", "press", "scroll"}
ALLOWED_KEYS = {"Enter", "Space", "ArrowDown", "ArrowUp", "Escape", "Tab"}

# Minimum leftover budget worth starting another beat with
MIN_BEAT_SECONDS = 8

# Goal-oriented signup: off-camera budget for the whole
# form-fill -> submit -> (maybe) email-verify -> onboarding flow.
SIGNUP_BUDGET_SECONDS = 90
TEMP_MAIL_API = "https://api.mail.tm"
INBOX_POLL_INTERVAL_S = 3
INBOX_POLL_TIMEOUT_S = 45
ONBOARDING_MAX_STEPS = 6


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
        sensitive_fields = page.locator(SENSITIVE_FIELD_SELECTOR)
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


async def _capture_reasoning_frame(page) -> str | None:
    """Return a masked, inline JPEG for visual navigation reasoning.

    This intentionally stays in memory: it is model input only, never a
    snapshot asset.  It uses the same sensitive-field mask as reel snapshots
    and refuses images too large for NVIDIA's inline image limit.
    """
    try:
        sensitive_fields = page.locator(SENSITIVE_FIELD_SELECTOR)
        # A first pass keeps detail for small/simple UIs; a second pass makes
        # dense pages fit the provider's inline image limit without uploads.
        for quality in (55, 30):
            image = await page.screenshot(
                type="jpeg",
                quality=quality,
                full_page=False,
                animations="disabled",
                caret="hide",
                mask=[sensitive_fields],
            )
            if len(image) <= MAX_INLINE_REASONING_FRAME_BYTES:
                return base64.b64encode(image).decode("ascii")
    except Exception:
        pass
    return None


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


def _control_is_safe(control: dict) -> bool:
    """Apply the same high-impact-action guard to every live DOM control."""
    haystack = " ".join(
        str(control.get(key) or "")
        for key in ("name", "label", "placeholder", "type", "href")
    ).lower()
    if any(term in haystack for term in UNSAFE_CONTROL_TERMS):
        return False
    if control.get("disabled"):
        return False
    if control.get("role") == "link" and not control.get("internal_link"):
        return False
    return bool(control.get("name") or control.get("label") or control.get("placeholder"))


async def _discover_live_controls(page) -> list[dict]:
    """Return a safe, accessibility-oriented inventory of visible controls.

    The inventory intentionally contains no CSS selector and no input values.
    The model can choose only a short-lived control id from this list; Python
    resolves that id through accessible locators immediately before acting.
    """
    try:
        controls = await page.evaluate(
            """() => {
              const max = 50;
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' &&
                  style.display !== 'none' && Number(style.opacity || 1) > 0 &&
                  rect.width > 1 && rect.height > 1;
              };
              const squash = (value) => String(value || '')
                .replace(/\\s+/g, ' ').trim().slice(0, 140);
              const labelFor = (el) => {
                const id = el.getAttribute('id');
                const explicit = id
                  ? document.querySelector(`label[for="${CSS.escape(id)}"]`)
                  : null;
                const parent = el.closest('label');
                return squash((explicit || parent)?.innerText || '');
              };
              const inferredRole = (el) => {
                const explicit = el.getAttribute('role');
                if (explicit) return explicit;
                const tag = el.tagName.toLowerCase();
                const type = el.tagName.toLowerCase() === 'select'
                  ? 'select' : (el.getAttribute('type') || '').toLowerCase();
                if (tag === 'button') return 'button';
                if (tag === 'a') return 'link';
                if (tag === 'select') return 'combobox';
                if (tag === 'textarea' || el.isContentEditable) return 'textbox';
                if (tag === 'input') {
                  if (type === 'checkbox' || type === 'radio') return type;
                  if (type === 'number') return 'spinbutton';
                  return 'textbox';
                }
                return '';
              };
              const selector = [
                'button', '[role="button"]', 'a[href]', 'input:not([type="hidden"])',
                'textarea', 'select', '[role="tab"]', '[role="switch"]',
                '[role="checkbox"]', '[role="radio"]', '[role="combobox"]',
                '[contenteditable="true"]'
              ].join(',');
              const result = [];
              for (const el of Array.from(document.querySelectorAll(selector))) {
                if (!visible(el) || el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
                const role = inferredRole(el);
                const type = el.tagName.toLowerCase() === 'select'
                  ? 'select' : (el.getAttribute('type') || '').toLowerCase();
                const label = squash(el.getAttribute('aria-label') || labelFor(el));
                const placeholder = squash(el.getAttribute('placeholder'));
                const name = squash(label || el.innerText || el.textContent ||
                  placeholder || el.getAttribute('title') || el.getAttribute('name') ||
                  el.getAttribute('id'));
                const href = el.tagName.toLowerCase() === 'a'
                  ? (el.getAttribute('href') || '') : '';
                const options = el.tagName.toLowerCase() === 'select'
                  ? Array.from(el.options).filter((option) => !option.disabled)
                    .map((option) => squash(option.textContent || option.value)).filter(Boolean).slice(0, 12)
                  : [];
                let internalLink = true;
                try {
                  internalLink = !href || new URL(href, window.location.href).origin === window.location.origin;
                } catch (_) { internalLink = false; }
                result.push({
                  id: `control-${result.length + 1}`,
                  role, name, label, placeholder, type,
                  test_id: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
                  element_id: el.getAttribute('id') || '',
                  dom_name: el.getAttribute('name') || '',
                  href, options, internal_link: internalLink,
                  disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
                });
                if (result.length >= max) break;
              }
              return result;
            }"""
        )
        return [control for control in controls if _control_is_safe(control)][:MAX_LIVE_CONTROLS]
    except Exception:
        return []


def _normalise_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _action_matches_control(action: str, control: dict) -> bool:
    role = control.get("role")
    if action == "type":
        return role in {"textbox", "spinbutton", "combobox"}
    if action == "select":
        return role in {"combobox", "listbox"}
    if action == "toggle":
        return role in {"checkbox", "radio", "switch"}
    if action == "press":
        return role in {"textbox", "spinbutton", "combobox", "button"}
    if action == "click":
        return role in {"button", "link", "tab", "checkbox", "radio", "switch", "combobox"}
    return action == "scroll"


def _target_score(control: dict, target: object) -> float:
    target_text = _normalise_text(target)
    if not target_text:
        return 0.0
    fields = [
        _normalise_text(control.get("name")),
        _normalise_text(control.get("label")),
        _normalise_text(control.get("placeholder")),
        _normalise_text(control.get("test_id")),
    ]
    best = 0.0
    target_words = set(target_text.split())
    for field in fields:
        if not field:
            continue
        if field == target_text:
            return 1.0
        if target_text in field or field in target_text:
            best = max(best, 0.82)
        field_words = set(field.split())
        if target_words and field_words:
            best = max(best, len(target_words & field_words) / len(target_words | field_words))
    return best


def _ground_planned_step(step: dict | None, controls: list[dict]) -> dict | None:
    """Bind a repository-planned intention to one current, safe control."""
    if not isinstance(step, dict):
        return None
    action = str(step.get("action") or "").lower()
    if action == "scroll":
        return {
            "action": "scroll", "control_id": None, "value": None,
            "reason": "Reveal the next learned section.", "beat_complete": False,
            "expected_result": step.get("expected_result", ""), "planned_step": True,
        }
    candidates = [
        (control, _target_score(control, step.get("target")))
        for control in controls
        if _action_matches_control(action, control)
    ]
    if not candidates:
        return None
    control, score = max(candidates, key=lambda item: item[1])
    if score < 0.5:
        return None
    # Opening a native <select> is not a visible, durable result. Let the live
    # model choose one of the discovered options as a verified select action.
    if action == "click" and control.get("type") == "select":
        return None
    return {
        "action": action,
        "control_id": control["id"],
        "value": step.get("value"),
        "reason": f"Perform the learned {action} on {control.get('name') or step.get('target')}.",
        "beat_complete": False,
        "expected_result": step.get("expected_result", ""),
        "planned_step": True,
    }


def _fallback_action(controls: list[dict], actions_taken: list,
                     planned_step: dict | None, beat: dict) -> dict:
    """Choose a grounded local action when the navigation model is unavailable."""
    grounded = _ground_planned_step(planned_step, controls)
    if grounded:
        return grounded

    used = {entry.get("control_id") for entry in actions_taken}
    # A new text field is a useful, visible low-risk interaction even without
    # an LLM response.  Sensitive/account fields were filtered before here.
    for control in controls:
        if (control.get("id") not in used and control.get("role") == "textbox" and
                _action_matches_control("type", control)):
            return {
                "action": "type", "control_id": control["id"], "value": "Demo example",
                "reason": f"Enter a demo value in {control.get('name')}.",
                "beat_complete": False, "expected_result": "", "planned_step": False,
            }

    preferred_terms = ("add", "create", "generate", "start", "try", "next", "open",
                       "show", "view", "search", "filter", "explore", "continue")
    for control in controls:
        if control.get("id") in used or not _action_matches_control("click", control):
            continue
        name = _normalise_text(control.get("name"))
        if control.get("role") == "tab" or any(term in name for term in preferred_terms):
            return {
                "action": "click", "control_id": control["id"], "value": None,
                "reason": f"Open the {control.get('name')} section.",
                "beat_complete": False, "expected_result": "", "planned_step": False,
            }
    return {
        "action": "scroll", "control_id": None, "value": None,
        "reason": beat.get("talking_point", ""), "beat_complete": False,
        "expected_result": "", "planned_step": False,
    }


async def _first_usable(locator):
    try:
        count = min(await locator.count(), 5)
        for index in range(count):
            candidate = locator.nth(index)
            if await candidate.is_visible() and await candidate.is_enabled():
                return candidate
    except Exception:
        pass
    return None


async def _resolve_control(page, control: dict | None, target: object = ""):
    """Resolve a control through stable accessibility attributes, never model CSS."""
    if not control:
        return None
    locators = []
    test_id = control.get("test_id")
    if test_id:
        locators.append(page.get_by_test_id(test_id))
    role = control.get("role")
    name = control.get("name") or control.get("label") or control.get("placeholder")
    if role and name:
        try:
            locators.append(page.get_by_role(role, name=re.compile(rf"^{re.escape(name)}$", re.I)))
        except Exception:
            pass
    label = control.get("label")
    if label:
        locators.append(page.get_by_label(label, exact=True))
    placeholder = control.get("placeholder")
    if placeholder:
        locators.append(page.get_by_placeholder(placeholder, exact=True))
    element_id = control.get("element_id")
    if element_id:
        locators.append(page.locator(f"[id={json.dumps(element_id)}]"))
    dom_name = control.get("dom_name")
    if dom_name:
        locators.append(page.locator(f"[name={json.dumps(dom_name)}]"))

    # The final target lookup is useful when a plan is source-accurate but the
    # live control omitted an optional accessibility attribute.
    target_text = str(target or "").strip()
    if target_text:
        if role:
            locators.append(page.get_by_role(role, name=re.compile(re.escape(target_text), re.I)))
        locators.append(page.get_by_label(target_text, exact=False))
        locators.append(page.get_by_placeholder(target_text, exact=False))

    for locator in locators:
        resolved = await _first_usable(locator)
        if resolved is not None:
            return resolved
    return None


async def _interaction_state(page) -> dict:
    """Collect an in-memory fingerprint for post-action verification only."""
    try:
        return await page.evaluate(
            """() => {
              const root = document.querySelector('main') || document.body;
              const text = String(root?.innerText || '').replace(/\\s+/g, ' ').slice(0, 2400);
              const controls = Array.from(document.querySelectorAll(
                'button, a[href], input, textarea, select, [role="button"], [role="tab"], [role="switch"]'
              )).slice(0, 40).map((el) => [
                el.tagName, el.getAttribute('role') || '', el.getAttribute('aria-expanded') || '',
                el.getAttribute('aria-selected') || '', el.getAttribute('aria-checked') || '',
                el.checked === undefined ? '' : String(el.checked), el.disabled ? 'disabled' : ''
              ].join('|')).join('||');
              return {url: window.location.href, text, controls, scroll_y: Math.round(window.scrollY)};
            }"""
        )
    except Exception:
        return {"url": page.url, "text": "", "controls": "", "scroll_y": 0}


def _state_changed(before: dict, after: dict, expected_result: object = "") -> bool:
    if before.get("url") != after.get("url"):
        return True
    if before.get("text") != after.get("text"):
        return True
    if before.get("controls") != after.get("controls"):
        return True
    if abs(int(before.get("scroll_y", 0)) - int(after.get("scroll_y", 0))) > 8:
        return True
    expected = _normalise_text(expected_result)
    return bool(expected and expected in _normalise_text(after.get("text")))


async def _close_unexpected_popups(page) -> None:
    """Close any extra window a login/signup click may have opened (e.g. a
    Google OAuth popup). We never drive third-party auth UIs — closing the
    popup and falling back to the base page is more reliable than trying to
    automate another company's login form, and safer to do without asking."""
    try:
        for p in list(page.context.pages):
            if p is not page:
                try:
                    await p.close()
                except Exception:
                    pass
                logger.info("Closed a secondary login window (likely OAuth) "
                           "— continuing on the main page")
    except Exception:
        pass


async def _looks_authenticated(page, url_before: str) -> bool:
    """Heuristic check that a login/signup submission actually worked: the
    URL moved away from the auth page, or the password field disappeared —
    and the page isn't showing an email-verification prompt or an error."""
    try:
        still_has_password_field = await page.locator(
            "input[type='password']").count() > 0
        url_changed = urldefrag(page.url)[0] != url_before
        body_text = (await page.locator("body").inner_text())[:1000].lower()
        verify_pending = any(
            k in body_text for k in ("verify your email", "confirm your email",
                                      "check your inbox", "check your email"))
        error_shown = any(
            k in body_text for k in ("invalid password", "incorrect password",
                                      "invalid credentials", "user not found"))
        return ((url_changed or not still_has_password_field)
                and not verify_pending and not error_shown)
    except Exception:
        return False


async def _attempt_login(page, app_url: str, credentials: dict,
                         job_id: str, capture_state: dict) -> bool:
    """
    Find and complete a login form using developer-supplied credentials.
    Returns True only if the submission could be confirmed to have actually
    logged in — not just "no exception was thrown".
    """
    username = credentials.get("username", "")
    password = credentials.get("password", "")
    if not username or not password:
        return False

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
        user_input = page.locator(
            "input[type='email'], input[name*='email' i], "
            "input[name*='user' i], input[type='text']"
        ).first
        await user_input.fill(username, timeout=ACTION_TIMEOUT_MS)
        await page.locator("input[type='password']").first.fill(
            password, timeout=ACTION_TIMEOUT_MS)

        url_before = urldefrag(page.url)[0]
        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Log in'), button:has-text('Login'), "
            "button:has-text('Sign in'), button:has-text('Sign In')"
        ).first
        if await submit.count() > 0:
            await submit.click(timeout=ACTION_TIMEOUT_MS)
        else:
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except Exception:
            await page.wait_for_timeout(2000)

        await _close_unexpected_popups(page)
        await _capture_snapshot(page, job_id, capture_state)
        return await _looks_authenticated(page, url_before)
    except Exception:
        return False


async def _create_temp_inbox() -> Optional[dict]:
    """Create a disposable inbox via mail.tm. Returns
    {"address": str, "password": str, "token": str} or None on failure.

    Used only when the developer supplied no login credentials but the app
    requires an account — lets the agent sign up as a real new user instead
    of skipping every gated feature. Some apps reject disposable-email
    domains outright; that's a legitimate signup failure, not a bug here —
    it just means signup falls back to public-pages-only.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            domains_res = await client.get(f"{TEMP_MAIL_API}/domains")
            domains_res.raise_for_status()
            domains = domains_res.json().get("hydra:member", [])
            if not domains:
                return None
            domain = domains[0]["domain"]

            address = f"demo{uuid.uuid4().hex[:10]}@{domain}"
            password = secrets.token_urlsafe(12)

            create_res = await client.post(
                f"{TEMP_MAIL_API}/accounts",
                json={"address": address, "password": password},
            )
            if create_res.status_code not in (200, 201):
                return None

            token_res = await client.post(
                f"{TEMP_MAIL_API}/token",
                json={"address": address, "password": password},
            )
            token_res.raise_for_status()
            token = token_res.json().get("token")
            if not token:
                return None

            return {"address": address, "password": password, "token": token}
    except Exception:
        logger.warning("Temp inbox creation failed — signup will be skipped")
        return None


async def _poll_temp_inbox_for_link(token: str,
                                    timeout: float = INBOX_POLL_TIMEOUT_S) -> Optional[str]:
    """Poll the temp inbox for the first message and pull out a verification
    link. Returns the URL, or None if nothing arrives within `timeout`."""
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        while time.monotonic() < deadline:
            try:
                res = await client.get(f"{TEMP_MAIL_API}/messages", headers=headers)
                res.raise_for_status()
                messages = res.json().get("hydra:member", [])
                if messages:
                    msg_id = messages[0]["id"]
                    detail_res = await client.get(
                        f"{TEMP_MAIL_API}/messages/{msg_id}", headers=headers)
                    detail_res.raise_for_status()
                    body = detail_res.json()

                    text_parts = []
                    if isinstance(body.get("text"), str):
                        text_parts.append(body["text"])
                    html_field = body.get("html")
                    if isinstance(html_field, list):
                        text_parts.extend(h for h in html_field if isinstance(h, str))
                    elif isinstance(html_field, str):
                        text_parts.append(html_field)
                    text = " ".join(text_parts)

                    urls = re.findall(r'https?://[^\s"\'<>]+', text)
                    for u in urls:
                        if any(k in u.lower() for k in ("verify", "confirm", "activate")):
                            return u
                    if urls:
                        return urls[0]
            except Exception:
                pass
            await asyncio.sleep(INBOX_POLL_INTERVAL_S)
    return None


async def _has_signup_form(page) -> bool:
    """Heuristic: a signup form has a password field AND either a second
    password field (confirm) or explicit signup wording nearby."""
    try:
        password_count = await page.locator("input[type='password']").count()
        if password_count == 0:
            return False
        text = (await page.locator("body").inner_text())[:2000].lower()
        return password_count >= 2 or any(
            k in text for k in ("create account", "sign up", "register", "get started"))
    except Exception:
        return False


async def _find_signup_entry_point(page, app_url: str, job_id: str,
                                   capture_state: dict) -> bool:
    """Get a signup form on screen: use it if already visible, otherwise
    click a 'Sign up' link, otherwise try common signup routes."""
    if await _has_signup_form(page):
        return True

    try:
        signup_link = page.get_by_role(
            "link", name=re.compile("sign up|register|create account|get started", re.I))
        if await signup_link.count() > 0:
            await signup_link.first.click(timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(1500)
            if job_id:
                await _capture_snapshot(page, job_id, capture_state)
            if await _has_signup_form(page):
                return True
    except Exception:
        pass

    for path in ("/signup", "/sign-up", "/register", "/auth/signup", "/auth/register"):
        if await _safe_goto(page, app_url.rstrip("/") + path):
            if job_id:
                await _capture_snapshot(page, job_id, capture_state)
            if await _has_signup_form(page):
                return True
    return False


async def _check_all_consent_checkboxes(page) -> int:
    """Check every visible checkbox on the page (terms, age confirmation,
    etc.) — required consent boxes block submission otherwise. Each check is
    verified against the box's actual state, not assumed from a clean click.
    Returns how many are confirmed checked."""
    confirmed = 0
    try:
        boxes = page.locator("input[type='checkbox']")
        count = await boxes.count()
        for i in range(count):
            box = boxes.nth(i)
            try:
                if not await box.is_visible():
                    continue
                if await box.is_checked():
                    confirmed += 1
                    continue
                await box.check(timeout=ACTION_TIMEOUT_MS)
                if await box.is_checked():
                    confirmed += 1
            except Exception:
                continue
    except Exception:
        pass
    return confirmed


async def _attempt_signup(page, app_url: str, job_id: str,
                          capture_state: dict) -> Optional[dict]:
    """
    Goal-oriented autonomous signup: create a temp inbox, fill and submit the
    signup form, check every consent checkbox, verify by email if the app
    demands it, and confirm the account actually landed logged-in before
    handing control back to the beat loop.

    Returns the credentials used on confirmed success, or None if signup
    could not be completed/verified — in which case the caller falls back to
    demoing public pages only, exactly as if no credentials had ever been
    supplied. We never guess that signup worked.
    """
    deadline = time.monotonic() + SIGNUP_BUDGET_SECONDS

    if not await _find_signup_entry_point(page, app_url, job_id, capture_state):
        logger.info("No signup form found — continuing with public pages only")
        return None

    inbox = await _create_temp_inbox()
    if inbox is None:
        logger.warning("Could not create a temp inbox — skipping signup")
        return None

    account_password = secrets.token_urlsafe(10) + "Aa1!"  # meets typical complexity rules

    try:
        email_input = page.locator(
            "input[type='email'], input[name*='email' i], "
            "input[name*='user' i], input[type='text']"
        ).first
        await email_input.fill(inbox["address"], timeout=ACTION_TIMEOUT_MS)

        password_inputs = page.locator("input[type='password']")
        pw_count = await password_inputs.count()
        if pw_count >= 1:
            await password_inputs.nth(0).fill(account_password, timeout=ACTION_TIMEOUT_MS)
        if pw_count >= 2:
            await password_inputs.nth(1).fill(account_password, timeout=ACTION_TIMEOUT_MS)

        await _check_all_consent_checkboxes(page)

        url_before = urldefrag(page.url)[0]
        submit = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Sign up'), button:has-text('Sign Up'), "
            "button:has-text('Create account'), button:has-text('Register'), "
            "button:has-text('Get started')"
        ).first
        if await submit.count() > 0:
            await submit.click(timeout=ACTION_TIMEOUT_MS)
        else:
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except Exception:
            await page.wait_for_timeout(2000)

        await _close_unexpected_popups(page)
        if job_id:
            await _capture_snapshot(page, job_id, capture_state)
    except Exception as e:
        logger.warning("Signup form fill/submit failed: %s", e)
        return None

    if await _looks_authenticated(page, url_before):
        return {"username": inbox["address"], "password": account_password}

    # Email verification required — poll the temp inbox and follow the link.
    logger.info("Signup appears to require email verification — polling temp inbox")
    remaining = max(10.0, deadline - time.monotonic())
    verify_link = await _poll_temp_inbox_for_link(inbox["token"], timeout=remaining)
    if not verify_link:
        logger.warning("No verification email arrived within budget — "
                       "continuing with public pages only")
        return None

    if not await _safe_goto(page, verify_link):
        logger.warning("Verification link did not load — continuing with public pages only")
        return None
    if job_id:
        await _capture_snapshot(page, job_id, capture_state)

    # Some apps verify then redirect to a login page rather than auto-signing in.
    if await page.locator("input[type='password']").count() > 0:
        try:
            await page.locator(
                "input[type='email'], input[name*='email' i], "
                "input[name*='user' i], input[type='text']"
            ).first.fill(inbox["address"], timeout=ACTION_TIMEOUT_MS)
            await page.locator("input[type='password']").first.fill(
                account_password, timeout=ACTION_TIMEOUT_MS)

            relogin_url_before = urldefrag(page.url)[0]
            submit = page.locator(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Log in'), button:has-text('Sign in')"
            ).first
            if await submit.count() > 0:
                await submit.click(timeout=ACTION_TIMEOUT_MS)
            else:
                await page.keyboard.press("Enter")
            try:
                await page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
            except Exception:
                await page.wait_for_timeout(2000)
            if job_id:
                await _capture_snapshot(page, job_id, capture_state)
            url_before = relogin_url_before
        except Exception:
            pass

    if await _looks_authenticated(page, url_before):
        return {"username": inbox["address"], "password": account_password}

    logger.warning("Could not confirm signup succeeded — continuing with public pages only")
    return None


async def _complete_onboarding(page, job_id: str, capture_state: dict) -> None:
    """Click through a post-signup onboarding wizard (Next/Continue/Skip/
    Get Started/Finish) until it's gone or the step cap is hit. Kept off
    camera — the viewer sees the finished app, not the wizard."""
    for _ in range(ONBOARDING_MAX_STEPS):
        try:
            btn = page.get_by_role(
                "button",
                name=re.compile("next|continue|skip|finish|done|get started|let's go", re.I),
            )
            if await btn.count() == 0:
                return
            url_before = urldefrag(page.url)[0]
            await btn.first.click(timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(1200)
            if job_id and urldefrag(page.url)[0] != url_before:
                await _capture_snapshot(page, job_id, capture_state)
        except Exception:
            return


async def _legacy_get_next_action(observation: dict, beat: dict, actions_taken: list,
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


async def _legacy_perform_action(page, decision: dict) -> bool:
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
                candidate = page.locator(selector)
                if await candidate.count() == 0:
                    return False
                locator = candidate.first

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


def _normalise_live_decision(raw: object, controls: list[dict], fallback: dict,
                             planned_step: dict | None) -> dict:
    """Reject model output that is not grounded to the supplied live controls."""
    if not isinstance(raw, dict):
        return fallback
    action = str(raw.get("action") or "").lower().strip()
    if action not in SAFE_ACTIONS:
        return fallback
    if action == "scroll":
        return {
            "action": "scroll", "control_id": None, "value": None,
            "reason": str(raw.get("reason") or fallback.get("reason") or "")[:240],
            "beat_complete": bool(raw.get("beat_complete")),
            "expected_result": "", "planned_step": False,
        }

    control_id = str(raw.get("control_id") or "")
    control = next((item for item in controls if item.get("id") == control_id), None)
    if control is None or not _control_is_safe(control) or not _action_matches_control(action, control):
        return fallback

    planned_action = str((planned_step or {}).get("action") or "").lower()
    value = raw.get("value")
    if planned_action == action and planned_step and planned_step.get("value") is not None:
        value = planned_step.get("value")
    if value is not None:
        value = str(value).strip()[:240]
    if action in {"type", "select", "press"} and not value:
        return fallback
    if action == "press" and value not in ALLOWED_KEYS:
        return fallback

    matches_plan = bool(
        planned_step and planned_action == action and
        _target_score(control, planned_step.get("target")) >= 0.5
    )
    return {
        "action": action,
        "control_id": control_id,
        "value": value,
        "target": (planned_step or {}).get("target") or control.get("name", ""),
        "reason": str(raw.get("reason") or "")[:240],
        "beat_complete": bool(raw.get("beat_complete")),
        "expected_result": str(
            raw.get("expected_result") or (planned_step or {}).get("expected_result") or ""
        )[:180],
        "planned_step": matches_plan,
    }


async def _get_next_action(observation: dict, beat: dict, actions_taken: list,
                           seconds_left: float, app_summary: str,
                           controls: list[dict],
                           planned_step: dict | None = None, page=None) -> dict:
    """Choose one action from the live, safe control inventory.

    A repository-planned step is executed directly when it cleanly matches a
    current control.  The model is used only to disambiguate a drifted layout
    or choose the next safe section; it can never invent a selector.
    """
    fallback = _fallback_action(controls, actions_taken, planned_step, beat)
    grounded = _ground_planned_step(planned_step, controls)
    if grounded is not None:
        return grounded

    gmi_api_key = os.environ.get("GMI_CLOUD_API_KEY")
    nvidia_api_key = os.environ.get("NVIDIA_API_KEY")
    if not gmi_api_key or not nvidia_api_key or page is None:
        return fallback

    reasoning_frame = await _capture_reasoning_frame(page)
    if not reasoning_frame:
        return fallback

    control_summary = [
        {
            "id": control.get("id"), "role": control.get("role"),
            "name": control.get("name"), "label": control.get("label"),
            "placeholder": control.get("placeholder"), "type": control.get("type"),
            "options": control.get("options", []),
        }
        for control in controls
    ]
    user_prompt = f"""You are driving a live browser to record a product demo.

App: {app_summary}
Current demo beat:
- Feature: {beat.get('feature')}
- Learned workflow: {beat.get('actions_hint')}
- Talking point: {beat.get('talking_point')}
- Seconds left: {int(seconds_left)}

Next repository-planned interaction (may be null if all planned steps are done):
{json.dumps(planned_step or None)}

What is currently visible:
- URL: {observation.get('url')}
- Page title: {observation.get('title')}
- Headings: {json.dumps(observation.get('headings', []))}
- Visible text: {observation.get('visible_text', '')[:500]}

Live safe controls. You may use ONLY one of these ids; never write a CSS
selector or a control name that is not in this list:
{json.dumps(control_summary, ensure_ascii=False)}

Actions already taken in this beat:
{json.dumps(actions_taken[-4:], indent=2)}

Choose one meaningful, safe action. Prefer the repository-planned interaction
when it has a matching live control. Do not open external links, edit account
or billing settings, send/share/invite, sign out, delete/remove, pay, publish,
or deploy. Use type only for a non-sensitive visible field and give realistic
demo text. Set beat_complete true only after the learned result is on screen.

Return ONLY valid JSON:
{{
  "action": "click" | "type" | "select" | "toggle" | "press" | "scroll",
  "control_id": "control-1" | null,
  "value": "text, option, or an allowed key for type/select/press; otherwise null",
  "expected_result": "optional visible text after the action",
  "reason": "one short sentence",
  "beat_complete": true | false
}}"""

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                NVIDIA_CHAT_URL,
                headers={"Authorization": f"Bearer {nvidia_api_key}",
                         "Accept": "application/json",
                         "Content-Type": "application/json"},
                json={
                    "model": VISION_NAV_MODEL,
                    "messages": [
                        {"role": "system", "content":
                         "You are an expert product-demo browser operator. "
                         "Respond only with valid JSON and use only supplied control ids."},
                        {"role": "user", "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/jpeg;base64,{reasoning_frame}",
                            }},
                        ]},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 500,
                },
            )
        if response.status_code != 200:
            return fallback
        content = response.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        return _normalise_live_decision(json.loads(content.strip()), controls, fallback, planned_step)
    except Exception:
        return fallback


async def _perform_action(page, decision: dict, controls: list[dict]) -> dict:
    """Execute and verify one grounded interaction before it is recorded."""
    action = decision.get("action", "")
    control = next(
        (item for item in controls if item.get("id") == decision.get("control_id")),
        None,
    )
    before = await _interaction_state(page)

    try:
        if action == "scroll":
            await page.evaluate("window.scrollBy({top: 450, behavior: 'smooth'})")
            await page.wait_for_timeout(INTERACTION_SETTLE_MS)
            after = await _interaction_state(page)
            return {"succeeded": _state_changed(before, after), "effect": "scroll", "state": after}

        locator = await _resolve_control(page, control, decision.get("target", ""))
        if locator is None:
            return {"succeeded": False, "effect": "control-not-found", "state": before}

        value = decision.get("value")
        if action == "type":
            await locator.fill(str(value), timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(250)
            after = await _interaction_state(page)
            try:
                succeeded = (await locator.input_value()) == str(value)
            except Exception:
                succeeded = _state_changed(before, after)
            return {"succeeded": succeeded, "effect": "field-filled", "state": after}

        if action == "select":
            try:
                previous_value = await locator.input_value()
            except Exception:
                previous_value = None
            try:
                await locator.select_option(label=str(value), timeout=ACTION_TIMEOUT_MS)
            except Exception:
                await locator.select_option(value=str(value), timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(INTERACTION_SETTLE_MS)
            after = await _interaction_state(page)
            try:
                selected_value = await locator.input_value()
            except Exception:
                selected_value = None
            return {
                "succeeded": (selected_value != previous_value or
                              _state_changed(before, after, decision.get("expected_result"))),
                "effect": "option-selected", "state": after,
            }

        if action == "toggle" and control and control.get("role") in {"checkbox", "radio"}:
            await locator.check(timeout=ACTION_TIMEOUT_MS)
            succeeded = await locator.is_checked()
        elif action == "press":
            key = str(value)
            if key not in ALLOWED_KEYS:
                return {"succeeded": False, "effect": "unsafe-key", "state": before}
            await locator.press(key, timeout=ACTION_TIMEOUT_MS)
            succeeded = True
        elif action == "click" or action == "toggle":
            await locator.click(timeout=ACTION_TIMEOUT_MS)
            succeeded = True
        else:
            return {"succeeded": False, "effect": "unsupported-action", "state": before}

        await page.wait_for_timeout(INTERACTION_SETTLE_MS)
        after = await _interaction_state(page)
        # A click that throws no exception but leaves the app unchanged is not
        # a successful demo interaction.  This closes the old no-op loophole.
        succeeded = succeeded and _state_changed(before, after, decision.get("expected_result"))
        return {"succeeded": succeeded, "effect": action, "state": after}
    except Exception:
        return {"succeeded": False, "effect": "action-error", "state": before}


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
    # The final assembler adds a three-second title card.  Keep the recorded
    # screen time aligned with the requested total duration rather than
    # reserving an unexplained extra three seconds.
    camera_budget = max(30, video_length - 3)
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

            # Goal-oriented account setup. We check for a gate two ways: the
            # planner's `needs_login` flag, OR the landing page itself already
            # being an auth wall (some apps land directly on sign-in) — the
            # planner's flag is a hint, not the only signal.
            landing_has_password_field = False
            try:
                landing_has_password_field = await page.locator(
                    "input[type='password']").count() > 0
            except Exception:
                pass
            app_is_gated = demo_plan.get("needs_login") or landing_has_password_field

            if app_is_gated and credentials:
                logged_in = await _attempt_login(
                    page, app_url, credentials, job_id, capture_state)
                if not logged_in:
                    logger.warning("Login with supplied credentials failed — "
                                   "continuing with public pages only")
                if await _safe_goto(page, app_url) and job_id:
                    await _capture_snapshot(page, job_id, capture_state)
            elif app_is_gated and not credentials:
                signup_creds = await _attempt_signup(
                    page, app_url, job_id, capture_state)
                if signup_creds:
                    await _complete_onboarding(page, job_id, capture_state)
                else:
                    logger.info("Signup could not be completed/verified — "
                               "continuing with public pages only")
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
                beat_start_segment_id = segment_id
                beat_completed = False
                beat_stuck = False
                actions_taken = []
                planned_steps = [
                    step for step in beat.get("interaction_steps", [])
                    if isinstance(step, dict)
                ]
                planned_step_index = 0
                # Leave room for a live-DOM follow-up while ensuring every
                # repo-learned workflow step gets a chance on camera.
                max_actions = min(10, max(4, len(planned_steps) + 3))

                for _ in range(max_actions):
                    beat_camera_used = elapsed() - beat_camera_start
                    seconds_left = beat_seconds - beat_camera_used
                    if seconds_left < 3 or elapsed() > session_budget:
                        break

                    segment_start = elapsed()
                    observation = await _observe(page)
                    controls = await _discover_live_controls(page)
                    planned_step = (
                        planned_steps[planned_step_index]
                        if planned_step_index < len(planned_steps) else None
                    )
                    decision = await _get_next_action(
                        observation, beat, actions_taken, seconds_left,
                        app_summary, controls, planned_step, page=page)

                    url_before_action = urldefrag(page.url)[0]
                    action_result = await _perform_action(page, decision, controls)
                    action_succeeded = bool(action_result.get("succeeded"))

                    # Let the result of the action settle and be visible on
                    # camera long enough for the viewer to read/absorb it.
                    await page.wait_for_timeout(2800)
                    url_after_action = urldefrag(page.url)[0]
                    if job_id and (action_succeeded or url_after_action != url_before_action):
                        try:
                            await page.wait_for_load_state(
                                "domcontentloaded", timeout=SETTLE_TIMEOUT_MS)
                        except Exception:
                            pass
                        await _capture_snapshot(page, job_id, capture_state)

                    post_observation = await _observe(page)

                    # Stuck detection: the action reported failure AND nothing
                    # about the page changed (no navigation, no visible text
                    # change). Recording a segment here would show the viewer
                    # a static screen while narration claims progress — so we
                    # drop this attempt instead of banking it as a segment,
                    # and free the beat early rather than looping blind.
                    page_unchanged = (
                        url_after_action == url_before_action
                        and post_observation.get("visible_text") == observation.get("visible_text")
                    )
                    if not action_succeeded and page_unchanged:
                        actions_taken.append({
                            "action": decision.get("action"),
                            "control_id": decision.get("control_id"),
                            "reason": "STUCK — no visible effect, skipping",
                        })
                        logger.warning(
                            "Beat '%s' stuck on action %s (selector=%s) — "
                            "no page change detected, ending beat early",
                            beat.get("feature"), decision.get("action"),
                            decision.get("control_id"))
                        beat_stuck = True
                        break  # reclaim remaining beat_seconds for later beats

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
                        # Narration should describe what's actually on screen
                        # AFTER the action, not the pre-action guess.
                        "observation": post_observation,
                    })
                    actions_taken.append({
                        "action": decision.get("action"),
                        "control_id": decision.get("control_id"),
                        "reason": decision.get("reason", ""),
                    })

                    if decision.get("planned_step") and planned_step_index < len(planned_steps):
                        planned_step_index += 1

                    # Once the intended repository-informed workflow is
                    # visible, move to the next learned section rather than
                    # spending the rest of the beat on generic scrolling.
                    if (decision.get("beat_complete") or
                            (planned_steps and planned_step_index >= len(planned_steps))):
                        beat_completed = True
                        break

                if (not beat_stuck and segment_id > beat_start_segment_id and
                        (not planned_steps or
                         planned_step_index >= len(planned_steps))):
                    beat_completed = True

                # ``seconds`` is a requested on-camera duration, not merely
                # an action-loop timeout. Keep a meaningful visible state on
                # screen for the rest of every beat so the selected 3/5-minute
                # target survives interaction drift and reaches assembly.
                remaining = beat_seconds - (elapsed() - beat_camera_start)
                session_remaining = session_budget - elapsed()
                hold_seconds = min(remaining, session_remaining)
                if hold_seconds >= 0.25:
                    if segment_id > beat_start_segment_id:
                        await page.wait_for_timeout(int(hold_seconds * 1000))
                        # Narrate the last successful/visible state instead of
                        # throwing away the remaining planned screen time.
                        segments[-1]["end_time"] = round(elapsed(), 2)
                    else:
                        # A custom canvas or broken control can leave a beat
                        # without an action segment. Preserve the safe visible
                        # overview so the script can explain what is on screen
                        # rather than silently losing this part of the video.
                        await page.wait_for_timeout(int(hold_seconds * 1000))
                        overview = await _observe(page)
                        segment_id += 1
                        segments.append({
                            "segment_id": segment_id,
                            "start_time": round(beat_camera_start, 2),
                            "end_time": round(elapsed(), 2),
                            "feature": beat.get("feature", ""),
                            "talking_point": beat.get("talking_point", ""),
                            "action": "view",
                            "reason": "Show the visible product state.",
                            "observation": overview,
                        })

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
