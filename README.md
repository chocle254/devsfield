# Devfields

### AI-powered demo video generator for builders who ship, not present.

---

## What Is Devfields?

Devfields turns a GitHub repo and a deployed app URL into a polished, ready-to-submit 3-minute demo video — automatically.

No OBS. No ElevenLabs tab-switching. No agonizing over what to show. No recording yourself explaining your own project six times.

You paste two URLs. Devfields reads your code, browses your live app, writes a script, generates a human-sounding voiceover, records the app in action, assembles everything into a video, and uploads it to Backblaze B2. You download and submit.

Built for the Backblaze Generative Media Hackathon using Genblaze + Backblaze B2 + GMI Cloud.

---

## The Problem

Every hackathon requires a demo video. Every builder hates making it.

The skills needed to build a great app and the skills needed to present one are completely different. Builders spend days on the product, then scramble to produce a 3-minute video that does it justice — juggling screen recording software, voiceover tools, video editors, and writing a script that covers everything without running long.

The result is almost always underwhelming compared to the actual product.

Devfields solves this for builders.

---

## How It Works

```
GitHub URL + Deployed App URL
          │
          ▼
┌─────────────────────┐
│   GitHub Reader     │  Reads README, key source files, and structure
│   (GMI LLM)        │  Understands what the project does and how
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   App Browser       │  Playwright navigates the live deployed app
│   (Playwright)      │  Screen-records the actual UI working in real time
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Script Writer     │  Combines code understanding + app recording
│   (DeepSeek/Llama   │  Writes a structured, timed narration script
│    via GMI)         │  Decides what to show and in what order
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Voice Generator   │  ElevenLabs eleven_v3 via Genblaze
│   (Genblaze +       │  Generates human-sounding voiceover from script
│    ElevenLabs)      │  Natural pacing, emotional range, not robotic
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Video Assembler   │  GMI Cloud video model via Genblaze Pipeline
│   (Genblaze +       │  Syncs screen recording with voiceover
│    GMI Cloud)       │  Adds transitions, titles, and closing slide
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Backblaze B2      │  All assets stored with SHA-256 provenance
│   (genblaze-s3)     │  Durable URL returned to user
└─────────────────────┘
          │
          ▼
   Download your video.
   Submit to the hackathon.
```

---

## Tech Stack

### Frontend
| Layer | Choice | Why |
|---|---|---|
| Framework | Next.js 14 (App Router) | Vercel-native, fast, familiar |
| Styling | Tailwind CSS | Rapid UI, no overhead |
| Deployment | Vercel | Zero config, instant deploys |
| Real-time | Server-Sent Events (SSE) | Stream pipeline progress to the UI |

### Backend
| Layer | Choice | Why |
|---|---|---|
| Framework | FastAPI | Async-first, perfect for long-running pipeline tasks |
| Job handling | asyncio background tasks | Simple, no Redis needed for hackathon scope |
| Browser automation | Playwright (with video recording) | Built-in MP4 screen recording, headless Chromium |
| Deployment | Railway | Docker support, Playwright-compatible, connects to Vercel |

### AI / Media Pipeline
| Layer | Choice | Why |
|---|---|---|
| SDK | Genblaze | Orchestrates all providers, provenance by default |
| LLM (script) | DeepSeek-V3.2 via GMI Cloud | Code understanding + script writing, free credits |
| TTS (voice) | ElevenLabs eleven_v3 via Genblaze | Most human-sounding output in blind tests |
| Video | GMI Cloud (Seedance / Kling) via Genblaze | Free credits, strong quality |
| Storage | Backblaze B2 via genblaze-s3 | Durable URLs, SHA-256 provenance manifest |

---

## Project Structure

```
devfields/
│
├── frontend/                          # Next.js 14 — deployed to Vercel
│   ├── app/
│   │   ├── layout.tsx                 # Root layout, fonts, global styles
│   │   ├── page.tsx                   # Landing page + URL input
│   │   ├── generate/
│   │   │   └── [jobId]/
│   │   │       └── page.tsx           # Live pipeline progress page
│   │   └── result/
│   │       └── [jobId]/
│   │           └── page.tsx           # Video player + download
│   │
│   ├── components/
│   │   ├── URLInput.tsx               # Dual URL input with validation
│   │   ├── GenerateButton.tsx         # Submit + loading state
│   │   ├── PipelineProgress.tsx       # Step-by-step progress tracker (SSE)
│   │   ├── VideoPlayer.tsx            # Final video player
│   │   └── ProvenanceCard.tsx         # Shows models used, timestamps, B2 hash
│   │
│   ├── lib/
│   │   └── api.ts                     # Backend API calls
│   │
│   ├── .env.local                     # NEXT_PUBLIC_BACKEND_URL
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── package.json
│
├── backend/                           # FastAPI — deployed to Railway
│   ├── main.py                        # App entry point, routes
│   ├── models.py                      # Pydantic schemas (Job, Status, Result)
│   ├── jobs.py                        # In-memory job state management
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── orchestrator.py            # Runs all steps in order, updates job state
│   │   ├── github_reader.py           # Reads repo via GitHub API or cloning
│   │   ├── app_browser.py             # Playwright screen recording of live app
│   │   ├── script_writer.py           # LLM script generation from code + recording
│   │   ├── voice_generator.py         # ElevenLabs TTS via Genblaze
│   │   ├── video_assembler.py         # Genblaze Pipeline → GMI video + audio sync
│   │   └── storage.py                 # Backblaze B2 uploads via genblaze-s3
│   │
│   ├── .env                           # All API keys
│   ├── Dockerfile                     # Includes Playwright + Chromium
│   ├── requirements.txt
│   └── railway.json                   # Railway deployment config
│
└── README.md
```

---

## API Routes

### `POST /generate`
Accepts GitHub URL and deployed app URL. Kicks off the pipeline. Returns a job ID immediately.

**Request:**
```json
{
  "github_url": "https://github.com/username/project",
  "app_url": "https://myproject.vercel.app",
  "video_length": 180,
  "tone": "pitch"
}
```

**Response:**
```json
{
  "job_id": "uuid-here",
  "status": "queued"
}
```

---

### `GET /status/{job_id}`
Returns current pipeline step and progress. Used by SSE to stream updates to the frontend.

**Response:**
```json
{
  "job_id": "uuid-here",
  "status": "in_progress",
  "current_step": "script_writer",
  "steps_completed": ["github_reader", "app_browser"],
  "steps_total": 5,
  "message": "Writing your narration script..."
}
```

---

### `GET /result/{job_id}`
Returns the final video URL and provenance details once complete.

**Response:**
```json
{
  "job_id": "uuid-here",
  "status": "complete",
  "video_url": "https://f005.backblazeb2.com/file/devfields/...",
  "manifest_url": "https://f005.backblazeb2.com/file/devfields/.../manifest.json",
  "sha256": "abc123...",
  "models_used": {
    "llm": "deepseek-v3.2",
    "tts": "eleven_v3",
    "video": "seedance-2-0"
  },
  "duration_seconds": 174,
  "generated_at": "2026-06-24T12:00:00Z"
}
```

---

### `GET /stream/{job_id}`
Server-Sent Events endpoint. Streams pipeline progress to the frontend in real time.

---

## Pipeline Modules — What Each One Does

### `github_reader.py`
- Accepts a GitHub URL
- Uses GitHub API to fetch `README.md`, folder structure, and key source files (detects framework automatically)
- Sends a condensed summary to the LLM: what this project is, what it does, what the tech stack is, what the key features are
- Output: structured project context object

### `app_browser.py`
- Accepts the deployed app URL
- Launches Playwright with `record_video=True` in headless Chromium
- Navigates key flows: landing page → main feature → secondary feature → any auth/onboarding if present
- Records everything as an MP4
- Output: raw screen recording file path + list of visited routes

### `script_writer.py`
- Combines project context (from github_reader) + visited routes (from app_browser)
- Calls DeepSeek-V3.2 via GMI `chat()` with a structured prompt
- Output: a timestamped narration script in JSON format:
```json
[
  { "time": 0, "text": "This is Devfields — it turns your GitHub repo into a demo video in minutes." },
  { "time": 8, "text": "You paste two URLs. Your GitHub repo and your deployed app." },
  ...
]
```

### `voice_generator.py`
- Takes the script text
- Calls ElevenLabs `eleven_v3` via `genblaze-elevenlabs`
- Outputs a human-sounding MP3 voiceover
- Uploads to B2 immediately via `storage.py`

### `video_assembler.py`
- Takes: screen recording MP4 + voiceover MP3
- Calls GMI Cloud video model via Genblaze Pipeline
- Syncs audio to video, adds intro title card, outro with project name
- Output: final assembled MP4

### `storage.py`
- Handles all B2 uploads via `genblaze-s3`
- Uses `KeyStrategy.HIERARCHICAL` for organized bucket layout
- Every asset gets a SHA-256 provenance manifest embedded and stored
- Returns durable credential-free URLs

---

## Environment Variables

### Frontend (`.env.local`)
```env
NEXT_PUBLIC_BACKEND_URL=https://devfields-backend.railway.app
```

### Backend (`.env`)
```env
# GMI Cloud
GMI_API_KEY=gmi-...

# ElevenLabs
ELEVENLABS_API_KEY=...

# Backblaze B2
B2_KEY_ID=...
B2_APP_KEY=...
B2_BUCKET=devfields-media

# GitHub (for private repo reading, optional)
GITHUB_TOKEN=...
```

---

## Genblaze Pipeline Code

### Voice Generation
```python
from genblaze_core import Pipeline, Modality, ObjectStorageSink, KeyStrategy
from genblaze_elevenlabs import ElevenLabsTTSProvider
from genblaze_s3 import S3StorageBackend

storage = ObjectStorageSink(
    S3StorageBackend.for_backblaze("devfields-media"),
    key_strategy=KeyStrategy.HIERARCHICAL,
)

result = (
    Pipeline("devfields-voice")
    .step(
        ElevenLabsTTSProvider(output_dir="output/"),
        model="eleven_v3",
        prompt=script_text,
        modality=Modality.AUDIO,
        voice_id="JBFqnCBsd6RMkjVDRZzb",
    )
    .run(sink=storage)
)

voiceover_url = result.run.steps[0].assets[0].url
```

### Video Assembly
```python
from genblaze_gmicloud import GMICloudVideoProvider

result = (
    Pipeline("devfields-video")
    .step(
        GMICloudVideoProvider(),
        model="seedance-2-0-260128",
        prompt=f"App demo walkthrough with smooth transitions. {project_name} — {project_description}",
        modality=Modality.VIDEO,
        duration=180,
        aspect_ratio="16:9",
    )
    .run(sink=storage, timeout=600)
)

video_url = result.run.steps[0].assets[0].url
manifest_uri = result.manifest.manifest_uri
sha256 = result.manifest.canonical_hash
```

---

## Dockerfile (Backend)

```dockerfile
FROM python:3.11-slim

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libgbm1 libasound2 libxshmfence1 libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and Chromium
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Requirements

```txt
fastapi
uvicorn
playwright
httpx
python-dotenv
pydantic

# Genblaze
genblaze-core
genblaze-s3
genblaze-gmicloud
genblaze-elevenlabs
```

---

## UI Design Direction

**Palette**
- Background: `#080808`
- Surface: `#111111`
- Border: `#1e1e1e`
- Accent: `#00FFB2` (teal — consistent with Arena brand)
- Text primary: `#FFFFFF`
- Text secondary: `#888888`

**Typography**
- Display: Geist (Vercel default, clean and technical)
- Body: Inter
- Monospace: Geist Mono (for URLs, hashes, model names)

**Key UI Moments**
- Landing page: Two URL inputs, dead center, nothing else. The inputs are the entire product.
- Progress page: Vertical pipeline with animated step indicators. Each step lights up as it completes.
- Result page: Full-width video player. Download button. Provenance card below showing models used, SHA-256, B2 URL.

**Signature element:** The pipeline progress visualization — each step is a node in a vertical chain. Active step pulses with the teal accent. Completed steps show a checkmark. It looks like watching the machine think.

---

## Judging Criteria Alignment

| Criterion | How Devfields Scores |
|---|---|
| **Real-World Utility** | Every hackathon builder is the user. The problem is personal and universal. |
| **Production Readiness** | End-to-end pipeline with error handling, job tracking, and durable storage. Not a demo of a demo. |
| **B2 Storage & Data Orchestration** | All assets, manifests, audio, and video stored on B2. Provenance embedded in every MP4. |
| **Use of Genblaze** | Genblaze orchestrates ElevenLabs TTS + GMI video in a multi-step chained Pipeline with provenance by default. |

---

## Hackathon Submission Checklist

- [ ] Working app URL (Vercel frontend + Railway backend)
- [ ] GitHub repo (public, with setup instructions)
- [ ] Providers and models list: DeepSeek-V3.2, ElevenLabs eleven_v3, GMI Cloud Seedance
- [ ] B2 and Genblaze usage explanation
- [ ] 3-minute demo video (generated by Devfields itself — meta points guaranteed)

---

## Timeline (40 days to August 4)

| Week | Focus |
|---|---|
| Week 1 (Jun 24–30) | H0 hackathon deadline first. Start Devfields repo + environment setup. |
| Week 2 (Jul 1–7) | Backend pipeline: github_reader + app_browser working end to end |
| Week 3 (Jul 8–14) | script_writer + voice_generator + Genblaze integration |
| Week 4 (Jul 15–21) | video_assembler + B2 storage + full pipeline connected |
| Week 5 (Jul 22–28) | Frontend: landing, progress, result pages |
| Week 6 (Jul 29–Aug 3) | Polish, testing, demo video, submission |

---

*Devfields — built by a builder, for builders.*
