# Devfields

**AI-powered demo video generator for hackathon builders.**

Point Devfields at your GitHub repo and your deployed app URL. It reads your
code, intelligently navigates your live app, writes a narrated script, generates
a professional voiceover, composites a final video, and stores everything on
Backblaze B2 — all without you touching OBS, ElevenLabs' dashboard, or a video
editor.

Built for the [Backblaze Generative Media Hackathon](https://backblaze-generative-media.devpost.com/).

---

## The Problem

Great hackathon projects lose because of bad demo videos, not bad code. Recording,
narrating, and editing a 3-minute demo eats hours that should go into the product.
Devfields automates the entire pipeline: from a GitHub URL and a live app URL to
a finished, narrated MP4.

---

## How It Works

Devfields runs a 7-step pipeline for every job:

1. **Read the repo & plan the demo** — fetches the README, file tree, framework,
   and key source files via the GitHub API, then detects the app's real routes
   and whether it uses authentication. An LLM studies all of it and produces a
   prioritized, **time-budgeted shot list** ("beats") that fits the requested
   video length — the AI understands your app before it ever opens a browser.
2. **Record the live app with AI** — a Playwright-controlled headless browser
   follows the plan beat by beat. If the app is behind a login and you provided
   a demo account, the AI signs in first (the login itself is kept out of the
   final video). Each segment records an *observation* of what was actually
   visible on screen.
3. **Write a segmented narration script** — one narration line per segment,
   grounded in that segment's real on-screen observation and word-fitted to the
   segment's exact duration, written in plain spoken language (no AI buzzwords).
4. **Generate a title card** — an AI-generated branded image for the video open
5. **Generate the voiceover** — one voice clip per segment, generated in parallel
6. **Composite the video** — each segment's screen clip is fitted to its
   voiceover length (padded, gently sped up, or trimmed), merged with FFmpeg,
   and concatenated into a final MP4
7. **Upload to Backblaze B2** — the final video, every individual segment (clip +
   voice), a segment manifest, and a SHA-256 provenance manifest are all stored

Progress streams live to the frontend via Server-Sent Events.

### How timing works (3-minute vs 5-minute videos)

The requested video length is a **hard budget**, not a hope:

- The planner allocates seconds per beat so the total fits the target length
  (minus a few seconds reserved for the title card).
- Beats are ordered by priority. If pages load slowly — bad network, cold
  serverless starts — the browser drops the *lowest-priority* beats instead of
  blowing the budget. Your best feature always makes the cut.
- **Loading time never appears in the final video.** Each segment's clock starts
  only after the page has settled, so spinners and blank screens fall between
  segments and are cut during assembly.
- Narration is written to fit each segment's real recorded duration (~145 words
  per minute), so the voice never rushes or trails off into silence.

### Apps behind a login

If your app requires authentication, toggle **Demo login** in the UI (or pass
`credentials` to the API) with a throwaway demo account. The AI detects the
login form, signs in before recording the gated features, and keeps the typing
of credentials out of the final video. Credentials are used once per job and
never stored or uploaded. If auth is detected but no credentials are provided,
the planner sticks to publicly accessible pages.

---

## Architecture

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, deployed on Vercel |
| Backend | FastAPI + Python 3.11, deployed on Railway |
| Browser automation | Playwright (headless Chromium) |
| AI navigation decisions | DeepSeek-V3-0324 via GMI Cloud |
| Narration script writing | DeepSeek-V3-0324 via GMI Cloud |
| Voiceover generation | ElevenLabs TTS v3 via GMI Cloud, orchestrated by **Genblaze** |
| Title card generation | Seedream 5.0 Lite via GMI Cloud, orchestrated by **Genblaze** |
| Video/audio compositing | FFmpeg (deterministic — not an AI step) |
| Storage | Backblaze B2, via **Genblaze**'s S3-compatible storage backend |

---

## Providers & Models Used

- **DeepSeek-V3-0324** (via GMI Cloud) — narration script writing and AI-guided
  app navigation decisions
- **ElevenLabs TTS v3** (via GMI Cloud, orchestrated through Genblaze's
  `GMICloudAudioProvider`) — segment-by-segment voiceover generation
- **Seedream 5.0 Lite** (via GMI Cloud, orchestrated through Genblaze's
  `GMICloudImageProvider`) — title card image generation
- **FFmpeg** — screen recording is split into per-segment clips, padded to match
  voiceover duration, merged with audio, and concatenated into the final video
- **Backblaze B2** (via Genblaze's `S3StorageBackend`) — durable storage for the
  final video, every individual segment, the segment manifest, and the
  SHA-256 provenance manifest

---

## How Devfields Uses Backblaze B2 & Genblaze

**Backblaze B2** stores every generated asset for every job:
jobs/{job_id}/final_video.mp4
jobs/{job_id}/manifest.json           ← SHA-256 hash, models used, timestamp
jobs/{job_id}/segments_manifest.json  ← index of every individual segment
jobs/{job_id}/segments/{segment_id}/clip.mp4
jobs/{job_id}/segments/{segment_id}/voice.mp3
Storing each segment individually — not just the final composited video — means
a specific part of a generated demo can be regenerated and re-composited later
without re-running the entire pipeline.

**Genblaze** orchestrates two distinct generative media modalities across two
GMI Cloud providers:

- `Modality.AUDIO` via `GMICloudAudioProvider` (ElevenLabs TTS v3)
- `Modality.IMAGE` via `GMICloudImageProvider` (Seedream 5.0 Lite)

Both pipelines are written using Genblaze's `Pipeline` API, and their outputs are
uploaded to B2 using Genblaze's `S3StorageBackend` and `ObjectStorageSink`
(`KeyStrategy.HIERARCHICAL`).

---

## Project Structure
devsfield/
├── app/                    # Next.js frontend (App Router) — deployed to Vercel
├── components/
├── lib/
├── public/
├── backend/                # FastAPI backend — deployed to Railway
│   ├── main.py
│   ├── models.py
│   ├── jobs.py
│   ├── pipeline/
│   │   ├── github_reader.py
│   │   ├── app_browser.py       # AI-guided navigation + segmented recording
│   │   ├── script_writer.py     # per-segment narration generation
│   │   ├── image_generator.py   # Genblaze + GMI Cloud (Seedream)
│   │   ├── voice_generator.py   # Genblaze + GMI Cloud (ElevenLabs)
│   │   ├── video_assembler.py   # FFmpeg split/pad/merge/concat
│   │   ├── segment_tools.py     # shared ffprobe/ffmpeg helpers
│   │   ├── storage.py           # Genblaze S3 backend → Backblaze B2
│   │   └── orchestrator.py      # runs all 7 steps in order
│   ├── requirements.txt
│   ├── Dockerfile
│   └── railway.json
├── package.json
└── README.md
---

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.11
- A [Backblaze B2](https://www.backblaze.com/cloud-storage) account and bucket
- A [GMI Cloud](https://cloud.gmi.ai) account (covers LLM, TTS, and image generation)
- A GitHub personal access token

### Frontend

```bash
npm install
npm run dev

###Backend
cd backend
pip install -r requirements.txt --break-system-packages
playwright install chromium
uvicorn main:app --reload

Environment Variables
Create backend/.env:
GITHUB_TOKEN=            # GitHub personal access token — required
GMI_CLOUD_API_KEY=       # Covers LLM, TTS, and image generation via GMI Cloud
B2_BUCKET=devfields-media
B2_PUBLIC_URL=           # e.g. https://f005.backblazeb2.com/file/devfields-media

Backblaze B2 credentials themselves (key ID and application key) are picked up
by Genblaze's S3StorageBackend.for_backblaze() — see the
Genblaze docs for the exact
environment variable names expected by your installed version.
Create a .env.local at the repo root for the frontend:

NEXT_PUBLIC_BACKEND_URL=https://your-railway-backend.up.railway.app


API Reference

Everything the UI does is available as a plain HTTP API:

```bash
# Start a job
curl -X POST https://your-backend/generate \
  -H "Content-Type: application/json" \
  -d '{
    "github_url": "https://github.com/you/your-app",
    "app_url": "https://your-app.vercel.app",
    "video_length": 180,
    "tone": "pitch",
    "credentials": { "username": "demo@example.com", "password": "demo1234" }
  }'
# -> { "job_id": "...", "status": "queued" }

# Poll status            GET /status/{job_id}
# Stream progress (SSE)  GET /stream/{job_id}
# Fetch the result       GET /result/{job_id}
```

- `video_length` — 60 to 300 seconds. This is a hard cap (see "How timing works").
- `tone` — `pitch`, `pitch_demo`, `demo`, or `technical`.
- `credentials` — optional; only needed for apps behind a login. Use a
  throwaway demo account.

Deployment
Frontend — deploys to Vercel from the repo root, unchanged
Backend — deploys to Railway as a separate service, with the service's
root directory set to /backend in Railway's settings. Uses the included
Dockerfile (Playwright + Chromium + FFmpeg) and railway.json
Segment-Based Architecture
Every navigation step during recording is tracked with start/end timestamps.
Narration, voiceover, and video clips are generated per segment rather than as
one continuous file, and every segment is stored individually on B2. This is
the foundation for targeted editing — regenerating a single segment's clip or
voiceover without touching the rest of the video — without needing to re-run
the AI navigation or re-record the whole app.
Demo Video
[Link to demo video — add before submission]
Built With
Next.js · FastAPI · Playwright · FFmpeg · Genblaze · GMI Cloud · DeepSeek-V3 ·
ElevenLabs · Seedream · Backblaze B2
