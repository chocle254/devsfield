import asyncio
import base64
import html
import os
import re

import httpx


# Reading only a README and a root `app/page.tsx` is enough to find a route,
# but not enough to understand what a person can *do* on that route.  Keep the
# repository pass deliberately bounded, while prioritising page and component
# source that describes the visible product UI.
MAX_UI_SOURCE_FILES = 12
MAX_UI_SOURCE_CHARS = 6000
SOURCE_EXTENSIONS = (".tsx", ".jsx", ".ts", ".js", ".vue", ".svelte", ".html")
EXCLUDED_SOURCE_PARTS = {
    "node_modules", ".next", "dist", "build", "coverage", "vendor", ".git",
}
SENSITIVE_CONTROL_TERMS = {
    "password", "passcode", "secret", "token", "api key", "api-key",
    "credit card", "card number", "cvv", "social security", "ssn",
}
UNSAFE_CONTROL_TERMS = {
    "delete", "remove", "destroy", "logout", "log out", "sign out",
    "unsubscribe", "billing", "checkout", "purchase", "pay now",
    "transfer", "withdraw", "deploy", "publish", "invite", "share",
}


async def read_repo(github_url: str) -> dict:
    """Read and analyze a GitHub repository."""
    
    # Parse the URL
    try:
        # Remove protocol and split
        parts = github_url.replace("https://github.com/", "").rstrip("/").split("/")
        if len(parts) < 2:
            raise ValueError("Invalid GitHub URL format")
        owner = parts[0]
        repo = parts[1].replace(".git", "")
    except Exception:
        raise ValueError("Invalid GitHub URL format")
    
    # Set up headers
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Use async client for all requests
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # Fetch README
        readme = ""
        try:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/readme",
                headers=headers
            )
            if resp.status_code == 200:
                content = resp.json()["content"]
                readme = base64.b64decode(content).decode()[:3000]
        except Exception:
            pass
        
        # Fetch file tree
        file_paths = []
        try:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1",
                headers=headers
            )
            if resp.status_code == 200:
                for item in resp.json()["tree"]:
                    if item["type"] == "blob":
                        file_paths.append(item["path"])
        except Exception:
            pass
        
        # Detect framework
        framework = "Unknown"
        if any(f in file_paths for f in ["next.config.js", "next.config.mjs", "next.config.ts"]):
            framework = "Next.js"
        elif "package.json" in file_paths and "src/App.tsx" in file_paths:
            framework = "React"
        elif any(f in file_paths for f in ["requirements.txt", "pyproject.toml"]):
            framework = "Python"
        elif "Cargo.toml" in file_paths:
            framework = "Rust"
        
        # Fetch repo metadata
        description = ""
        stars = 0
        language = "Unknown"
        try:
            resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers
            )
            if resp.status_code == 200:
                data = resp.json()
                description = data.get("description", "") or ""
                stars = data.get("stargazers_count", 0)
                language = data.get("language", "Unknown") or "Unknown"
            elif resp.status_code == 403:
                raise RuntimeError(
                    "GitHub API rate limit hit or token invalid. Check GITHUB_TOKEN."
                )
            elif resp.status_code == 404:
                raise RuntimeError(
                    f"Repository {owner}/{repo} not found or is private."
                )
        except httpx.HTTPError as e:
            if resp.status_code == 403:
                raise RuntimeError(
                    "GitHub API rate limit hit or token invalid. Check GITHUB_TOKEN."
                )
            raise
        
        # Read the route components and nearby UI components, rather than a
        # handful of hard-coded root files.  This is the information the
        # planner uses to learn sections, forms, tabs, and safe workflows.
        source_paths = _select_ui_source_paths(file_paths)
        source_results = await asyncio.gather(
            *[_fetch_source_file(client, owner, repo, path, headers)
              for path in source_paths],
            return_exceptions=True,
        )
        key_files = {
            path: content
            for path, content in zip(source_paths, source_results)
            if isinstance(content, str) and content
        }

        # Detect user-facing routes from both the file tree and React Router
        # declarations found in the source we just read.  The planner still
        # treats these as candidates, never as a licence to invent a route.
        detected_routes = _detect_routes(file_paths, key_files)

        # Detect whether the app has authentication, so the browser knows
        # to expect (and handle) a login flow.
        auth_info = _detect_auth(file_paths, readme)

        # A compact, source-derived catalog travels with the context.  It
        # deliberately contains labels/roles rather than raw CSS selectors:
        # the browser will ground these intentions against the live DOM before
        # it clicks anything, so stale code cannot cause blind interaction.
        interaction_catalog = _build_interaction_catalog(key_files)
    
    return {
        "repo_name": repo,
        "owner": owner,
        "description": description,
        "framework": framework,
        "readme": readme,
        "file_structure": file_paths[:50],
        "key_files": key_files,
        "stars": stars,
        "language": language,
        "detected_routes": detected_routes,
        "has_auth": auth_info["has_auth"],
        "auth_hints": auth_info["hints"],
        "interaction_catalog": interaction_catalog,
    }


async def _fetch_source_file(client: httpx.AsyncClient, owner: str, repo: str,
                             path: str, headers: dict) -> str:
    """Fetch one text source file without making a bad file non-fatal."""
    try:
        response = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=headers,
        )
        if response.status_code != 200:
            return ""
        data = response.json()
        encoded = data.get("content") or ""
        if data.get("encoding") == "base64":
            return base64.b64decode(encoded).decode("utf-8", errors="replace")[:MAX_UI_SOURCE_CHARS]
        return str(encoded)[:MAX_UI_SOURCE_CHARS]
    except Exception:
        return ""


def _is_ui_source_path(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    lower = path.lower()
    return (
        lower.endswith(SOURCE_EXTENSIONS)
        and not any(part.lower() in EXCLUDED_SOURCE_PARTS for part in parts)
        and not lower.endswith((".d.ts", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx"))
    )


def _route_from_source_path(path: str) -> str | None:
    """Map a conventional page file to a static URL, if it has one."""
    normalized = path.replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]

    for prefix in ("app/", "src/app/", "frontend/app/"):
        if normalized.startswith(prefix) and filename.startswith("page."):
            parts = normalized[len(prefix):].split("/")[:-1]
            parts = [part for part in parts if not part.startswith("(")]
            if parts and parts[0] == "api":
                return None
            route = "/" + "/".join(parts)
            return None if "[" in route else (route or "/")

    for prefix in ("pages/", "src/pages/"):
        if normalized.startswith(prefix) and normalized.endswith(SOURCE_EXTENSIONS):
            sub = normalized[len(prefix):].rsplit(".", 1)[0]
            if sub.startswith(("api/", "_")):
                return None
            route = "/" + ("" if sub == "index" else sub)
            return None if "[" in route else (route or "/")
    return None


def _source_priority(path: str) -> tuple:
    """Sort files by their likelihood of defining a visible interaction."""
    normalized = path.replace("\\", "/")
    lower = normalized.lower()
    route = _route_from_source_path(normalized)
    filename = lower.rsplit("/", 1)[-1]
    is_component = "/components/" in lower or "/ui/" in lower
    is_app_entry = filename in {"app.tsx", "app.jsx", "main.tsx", "main.jsx"}
    return (
        0 if route is not None else 1,
        0 if filename.startswith("page.") else 1,
        0 if is_component else 1,
        0 if is_app_entry else 1,
        len(normalized),
        normalized,
    )


def _select_ui_source_paths(file_paths: list[str]) -> list[str]:
    """Pick a compact, representative UI corpus from a repository tree."""
    candidates = [path for path in file_paths if _is_ui_source_path(path)]
    return sorted(candidates, key=_source_priority)[:MAX_UI_SOURCE_FILES]


def _clean_ui_text(value: str) -> str:
    """Turn a tiny HTML/JSX fragment into a useful accessible-name hint."""
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = re.sub(r"\{[^{}]*\}", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n'\"")
    return value[:120]


def _attributes(raw: str) -> dict[str, str]:
    """Extract literal JSX/HTML attributes; expressions are intentionally skipped."""
    attrs: dict[str, str] = {}
    for match in re.finditer(
        r"([:\w-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", raw or ""
    ):
        attrs[match.group(1).lower()] = match.group(2) or match.group(3) or ""
    return attrs


def _control_is_safe(control: dict) -> bool:
    terms = " ".join(
        str(control.get(key) or "")
        for key in ("name", "label", "placeholder", "type", "href")
    ).lower()
    return not any(term in terms for term in SENSITIVE_CONTROL_TERMS | UNSAFE_CONTROL_TERMS)


def _build_interaction_catalog(source_files: dict[str, str]) -> list[dict]:
    """Build source-derived UI intentions, never executable selectors."""
    catalog: list[dict] = []
    for path, source in source_files.items():
        controls = _extract_controls(source)
        sections = _extract_sections(source)
        if not controls and not sections:
            continue
        catalog.append({
            "source_file": path,
            "route": _route_from_source_path(path),
            "sections": sections,
            "controls": controls,
        })
    return catalog


def _extract_sections(source: str) -> list[str]:
    sections: list[str] = []
    seen: set[str] = set()
    pattern = re.compile(r"<h[1-3]\b[^>]*>(.*?)</h[1-3]>", re.I | re.S)
    for match in pattern.finditer(source):
        name = _clean_ui_text(match.group(1))
        key = name.lower()
        if name and key not in seen:
            sections.append(name)
            seen.add(key)
        if len(sections) >= 12:
            break
    return sections


def _extract_controls(source: str) -> list[dict]:
    controls: list[dict] = []
    seen: set[tuple] = set()

    labels_by_id: dict[str, str] = {}
    for match in re.finditer(
        r"<label\b(?P<attrs>[^>]*)>(?P<body>.*?)</label>", source,
        re.I | re.S,
    ):
        attrs = _attributes(match.group("attrs"))
        target_id = attrs.get("for") or attrs.get("htmlfor")
        label = _clean_ui_text(match.group("body"))
        if target_id and label:
            labels_by_id[target_id] = label

    def add(role: str, attrs: dict[str, str], body: str = "", href: str = "") -> None:
        control_type = attrs.get("type", "").lower()
        label = attrs.get("aria-label") or labels_by_id.get(attrs.get("id", ""), "")
        placeholder = attrs.get("placeholder", "")
        name = label or _clean_ui_text(body) or attrs.get("title", "")
        if not name:
            name = attrs.get("name", "") or placeholder or attrs.get("id", "")
        if control_type in {"checkbox", "radio"}:
            role = control_type
        elif role == "input":
            role = "combobox" if control_type in {"select", "date", "number"} else "textbox"
        candidate = {
            "role": role,
            "name": _clean_ui_text(name),
            "label": _clean_ui_text(label),
            "placeholder": _clean_ui_text(placeholder),
            "test_id": attrs.get("data-testid", "") or attrs.get("data-test", ""),
            "type": control_type,
            "href": href or attrs.get("href", ""),
        }
        if not candidate["name"] or not _control_is_safe(candidate):
            return
        if candidate["role"] == "link" and candidate["href"].startswith(("http://", "https://", "mailto:")):
            return
        key = tuple(candidate.get(item, "") for item in ("role", "name", "label", "placeholder", "test_id"))
        if key not in seen:
            controls.append(candidate)
            seen.add(key)

    paired_pattern = re.compile(
        r"<(?P<tag>button|a|link|tabs(?:trigger)?|accordiontrigger|selecttrigger)"
        r"\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        re.I | re.S,
    )
    for match in paired_pattern.finditer(source):
        tag = match.group("tag").lower()
        role = "link" if tag in {"a", "link"} else "button"
        if "tab" in tag:
            role = "tab"
        elif "select" in tag:
            role = "combobox"
        add(role, _attributes(match.group("attrs")), match.group("body"))

    field_pattern = re.compile(r"<(input|textarea|select)\b(?P<attrs>[^>]*)/?>", re.I | re.S)
    for match in field_pattern.finditer(source):
        tag = match.group(1).lower()
        attrs = _attributes(match.group("attrs"))
        add("combobox" if tag == "select" else "input", attrs)

    return controls[:20]


def _extract_react_routes(source: str) -> set[str]:
    """Find literal React Router paths in the small source corpus."""
    candidates: set[str] = set()
    patterns = (
        r"<Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"']",
        r"\bpath\s*:\s*[\"']([^\"']+)[\"']",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, source, re.I):
            route = match.group(1).strip()
            if not route or route.startswith(("http://", "https://")):
                continue
            route = route if route.startswith("/") else f"/{route}"
            if not any(token in route for token in (":", "*", "[")):
                candidates.add(route)
    return candidates


def _detect_routes(file_paths: list[str], source_files: dict[str, str] | None = None) -> list[str]:
    """Infer user-facing routes from the repository file tree."""
    routes: set[str] = set()

    for path in file_paths:
        route = None

        # Next.js App Router: app/**/page.{tsx,jsx,ts,js}
        for prefix in ("app/", "src/app/", "frontend/app/"):
            if path.startswith(prefix) and path.rsplit("/", 1)[-1].startswith("page."):
                sub = path[len(prefix):]
                parts = sub.split("/")[:-1]  # drop page.tsx
                # skip route groups (parens) and api routes
                parts = [p for p in parts if not p.startswith("(")]
                if parts and parts[0] == "api":
                    break
                route = "/" + "/".join(parts)
                break

        # Next.js Pages Router: pages/**/*.{tsx,jsx,ts,js}
        if route is None:
            for prefix in ("pages/", "src/pages/"):
                if path.startswith(prefix) and path.endswith((".tsx", ".jsx", ".ts", ".js")):
                    sub = path[len(prefix):].rsplit(".", 1)[0]
                    if sub.startswith(("api/", "_")):
                        break
                    route = "/" + ("" if sub == "index" else sub)
                    break

        if route is not None:
            # skip fully dynamic routes ([id]) — can't navigate blind
            if "[" not in route:
                routes.add(route or "/")

    for source in (source_files or {}).values():
        routes.update(_extract_react_routes(source))

    ordered = sorted(routes, key=lambda r: (r != "/", r.count("/"), r))
    return ordered[:30]


def _detect_auth(file_paths: list[str], readme: str) -> dict:
    """Heuristically detect whether the app has an auth/login flow."""
    hints: list[str] = []
    joined = "\n".join(file_paths).lower()

    library_markers = {
        "next-auth": "next-auth", "better-auth": "better-auth",
        "@clerk": "Clerk", "supabase": "Supabase Auth",
        "firebase": "Firebase Auth", "auth0": "Auth0",
        "lucia": "Lucia", "passport": "Passport",
    }
    for marker, label in library_markers.items():
        if marker in joined:
            hints.append(label)

    route_markers = ["login", "signin", "sign-in", "signup", "sign-up",
                     "auth/", "/auth", "register"]
    for marker in route_markers:
        if marker in joined:
            hints.append(f"route:{marker}")

    readme_lower = (readme or "").lower()
    for phrase in ("log in", "login", "sign in", "sign up", "authentication"):
        if phrase in readme_lower:
            hints.append(f"readme:{phrase}")
            break

    return {"has_auth": len(hints) > 0, "hints": hints[:6]}
