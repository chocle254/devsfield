from pydantic import BaseModel, Field
from typing import Optional


class AppCredentials(BaseModel):
    """Optional demo-account login for apps behind authentication.
    Used ONLY during the recording session; never stored or uploaded."""
    username: str
    password: str


class StoryboardStep(BaseModel):
    """One concrete, developer-specified action within a beat.

    `target` should match the visible label, placeholder, or name of the
    control (e.g. "Add task", "Email address") — the browser grounds this
    against the real page's accessible controls before acting, so it does
    NOT need to be a CSS selector or element id. `expected_result`, when
    given, is checked against the page's actual state after the action runs.
    """
    action: str = Field(..., description="click, type, select, toggle, press, or scroll")
    target: str = Field(..., min_length=1, max_length=120)
    value: Optional[str] = Field(default=None, max_length=240)
    expected_result: Optional[str] = Field(default="", max_length=180)


class StoryboardBeat(BaseModel):
    """One shot of the demo: a page, what happens on it, and what to say."""
    route: str = Field(default="/", max_length=200)
    feature: Optional[str] = Field(default=None, max_length=160)
    actions_hint: Optional[str] = Field(default=None, max_length=300)
    talking_point: Optional[str] = Field(default=None, max_length=300)
    seconds: Optional[int] = Field(default=None, ge=1, le=300)
    interaction_steps: list[StoryboardStep] = Field(default_factory=list)


class GenerateRequest(BaseModel):
    """Request to generate a demo video."""
    github_url: str
    app_url: str
    video_length: int = Field(default=180, ge=60, le=300)
    tone: str = Field(default="pitch")  # "pitch", "pitch_demo", "demo", or "technical"
    voice: Optional[str] = None
    credentials: Optional[AppCredentials] = None
    # Developer-authored shot list. When provided, the planner skips the LLM
    # entirely and builds the plan straight from these beats (still passed
    # through the same safety normalizer as an AI-generated plan). Omit or
    # leave empty to keep the default AI-planned behavior.
    storyboard: Optional[list[StoryboardBeat]] = None


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
    # Verified final MP4 duration can include frame/AAC rounding, so preserve
    # it as a float instead of rejecting a successful result such as 180.03.
    duration_seconds: Optional[float] = None
    generated_at: Optional[str] = None
