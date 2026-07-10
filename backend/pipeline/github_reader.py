import base64
import os
import httpx


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
        
        # Detect user-facing routes from the file tree (Next.js app/pages
        # router, plain React router files). These tell the demo planner
        # which pages actually exist without guessing.
        detected_routes = _detect_routes(file_paths)

        # Detect whether the app has authentication, so the browser knows
        # to expect (and handle) a login flow.
        auth_info = _detect_auth(file_paths, readme)

        # Fetch key source files
        key_file_priorities = [
            "README.md", "main.py", "app/page.tsx", "src/App.tsx",
            "index.js", "app.py", "src/index.ts"
        ]
        key_files = {}
        
        for file_path in key_file_priorities:
            if len(key_files) >= 3:
                break
            try:
                resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}",
                    headers=headers
                )
                if resp.status_code == 200:
                    content = resp.json()["content"]
                    decoded = base64.b64decode(content).decode()[:1500]
                    key_files[file_path] = decoded
            except Exception:
                pass
    
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
    }


def _detect_routes(file_paths: list[str]) -> list[str]:
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

    ordered = sorted(routes, key=lambda r: (r != "/", r.count("/"), r))
    return ordered[:20]


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
