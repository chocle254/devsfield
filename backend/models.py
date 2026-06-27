from pydantic import BaseModel, Field
from typing import Optional


class GenerateRequest(BaseModel):
    """Request to generate a demo video."""
    github_url: str
    app_url: str
    video_length: int = Field(default=180, ge=60, le=300)
    tone: str = Field(default="pitch")  # "pitch", "demo", or "technical"


class JobStatus(BaseModel):
    """Current status of a job."""
    job_id: str
    status: str  # "queued", "in_progress", "complete", "failed"
    current_step: Optional[str] = None
    steps_completed: list[str] = []
    steps_total: int = 6
    message: Optional[str] = None
    error: Optional[str] = None


class JobResult(BaseModel):
    """Result of a completed job."""
    job_id: str
    status: str
    video_url: Optional[str] = None
    manifest_url: Optional[str] = None
    sha256: Optional[str] = None
    models_used: Optional[dict] = None
    duration_seconds: Optional[int] = None
    generated_at: Optional[str] = None
