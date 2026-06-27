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
    }
