from pydantic import BaseModel, Field
from typing import Optional


class AppCredentials(BaseModel):
    """Optional demo-account login for apps behind authentication.
    Used ONLY during the recording session; never stored or uploaded."""
    username: str
    password: str


class GenerateRequest(BaseModel):
    """Request to generate a demo video."""
    github_url: str
    app_url: str
    video_length: int = Field(default=180, ge=60, le=300)
    tone: str = Field(default="pitch")  # "pitch", "pitch_demo", "demo", or "technical"
    credentials: Optional[AppCredentials] = None


class NavigationSnapshot(BaseModel):
    """Safe metadata for a browser screenshot captured during a run."""
    id: str
    url: str
    title: str
    captured_at: str
    image_url: str


class JobStatus(BaseModel):
    """Current status of a job."""
    job_id: str
    status: str  # "queued", "in_progress", "complete", "failed"
    current_step: Optional[str] = None
    steps_completed: list[str] = []
    steps_total: int = 7
    message: Optional[str] = None
    error: Optional[str] = None
    snapshots: list[NavigationSnapshot] = Field(default_factory=list)


class JobResult(BaseModel):
    job_id: str
    status: str
    video_url: Optional[str] = None
    manifest_url: Optional[str] = None
    segments_url: Optional[str] = None
    segments: Optional[list[dict]] = None
    github_url: Optional[str] = None        # library metadata
    app_url: Optional[str] = None           # library metadata
    repo_name: Optional[str] = None         # library metadata
    tone: Optional[str] = None              # library metadata
    sha256: Optional[str] = None
    models_used: Optional[dict] = None
    duration_seconds: Optional[int] = None
    generated_at: Optional[str] = None
