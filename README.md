# socra-dify — MEDAI/OSCE Reproducible Environment

This repository is a customized fork of [langgenius/dify](https://github.com/langgenius/dify) built specifically for the **MEDAI / OSCE project**.

It integrates:

- A **custom video-extractor microservice** (for video frame extraction + audio extraction)
- A **modified Dify Docker environment** that automatically builds and runs the microservice
- An exported **MEDAI/OSCE Dify workflow** (`workflows/MVP-complete.yml`)
- A **Makefile** that simplifies startup and teardown
- A fully reproducible layout so teammates can clone + run the system with no manual edits

This README provides **end-to-end setup instructions**, from fresh clone → launch → workflow import → running OSCE videos.

---

## 🚀 1. Overview

This fork allows you to:

- Run the complete Dify stack locally (API, UI, workers, Postgres, Redis)
- Automatically launch the `video-extractor` HTTP microservice used by the ingestion node
- Import the OSCE workflow and run long-form OSCE video grading pipelines
- Fully reproduce the environment on any teammate’s machine

Everything required lives inside this repository.

---

## 📁 2. Repository Structure (Important)

Key paths in this fork:

```text
socra-dify/
├── docker/
│   ├── docker-compose.yaml        # main Docker stack (includes video-extractor)
│   ├── .env.example               # template for local configuration
│   └── video-extractor/           # custom HTTP microservice for OSCE videos
│       ├── Dockerfile
│       ├── main.py                # service entrypoint (HTTP API)
│       └── ...                    # any additional code / assets
├── workflows/
│   └── MVP-complete.yml           # exported MEDAI/OSCE workflow for Dify
├── Makefile                       # helper targets for docker compose
└── ...                            # standard Dify source tree (api, web, worker, etc.)
```

---

## 🧩 3. Prerequisites

Make sure you have:

### Required

- **Docker Desktop** (macOS/Windows)  
  OR  
- **Docker Engine + docker-compose plugin** (Linux)

### Optional (but helpful)

- VSCode or similar editor
- A stable internet connection for model downloads

### You must have at least one model provider key

- Example: `OPENAI_API_KEY`

---

## ✅ Step 0 — Clone the Repository

```bash
git clone https://github.com/vittoriacicalese/socra-dify.git
cd socra-dify
```

---

## ✅ Step 1 — Configure Environment Variables

Navigate into the `docker` folder:

```bash
cd docker
```

Copy the template environment file:

```bash
cp .env.example .env
```

Open `.env` and fill in real values:

```env
INIT_EMAIL=admin@example.com
INIT_PASSWORD=ReplaceMe123!
INIT_USERNAME=admin

OPENAI_API_KEY=your-real-key-here
```

### 🔒 Important Notes

- Never commit `.env` (it contains secrets).
- `.env.example` contains placeholders only and is safe to commit.
- Real provider keys must live only in:
  - The local `.env` file
  - The provider configuration inside the Dify UI

Then return to the repo root:

```bash
cd ..
```

---

## ✅ Step 2 — Start the Full Dify + Video Extractor Stack

From the repository root:

```bash
make up
```

What this does:

- Builds Dify (API, Web, Worker)
- Builds and starts Postgres + Redis
- Builds and starts the custom `video-extractor` microservice
- Launches everything in Docker using `docker/docker-compose.yaml`

Check container status:

```bash
make ps
```

View logs:

```bash
make logs
```

(Press `Ctrl+C` to stop log output.)

---

## ✅ Step 3 — Open the Dify UI

Open your browser and go to:

- http://localhost:3000

Log in using credentials from `.env`:

- Email: `INIT_EMAIL`
- Password: `INIT_PASSWORD`

Dify will automatically initialize the admin user using these values.

---

## ✅ Step 4 — Import the OSCE Workflow

Inside the Dify UI:

1. Go to **Workflow** (or **Apps**).
2. Click **Import**.
3. Select the file:

   ```text
   workflows/MVP-complete.yml
   ```

You should now see the full MEDAI/OSCE pipeline:

- Video ingestion node
- HTTP node calling `video-extractor`
- ASR node
- Rubric evaluation nodes
- Final grading flow

This completes the OSCE workflow setup.

---

## ✅ Step 5 — Test the Video Extractor Service

From your terminal:

```bash
curl http://localhost:8000/health
```

Or in a browser:

- http://localhost:8000/health

Expected output:

```json
{ "status": "ok" }
```

### 🧠 How it works inside the workflow

Dify’s ingestion node `POST`s video bytes to:

```text
http://video-extractor:8000/extract
```

Docker’s internal DNS automatically resolves `video-extractor`.

---

## 🔵 Stopping & Resetting the System

Stop Dify + `video-extractor` + all backing services:

```bash
make down
```

Completely reset your Docker environment (optional):

```bash
docker system prune -a
docker volume prune
```

Running `make up` afterward will rebuild everything cleanly.

---

## 🎥 How the Video Extractor Works (High-Level)

The microservice performs:

### ▶ Video → Frames

Extracts frames at a configurable FPS or interval.

### ▶ Video → WAV Audio

Converts video audio into `.wav` suitable for ASR.

### ▶ JSON Response Back to Dify

Example:

```json
{
  "frames_dir": "/shared/frames/video123/",
  "audio_path": "/shared/audio/video123.wav",
  "num_frames": 3421
}
```

Downstream nodes use these paths for:

- ASR
- Captioning
- Rubric scoring
- Final grading

All integration is defined in `workflows/MVP-complete.yml`.

---

## 📦 Makefile Commands (Summary)

```bash
make up                        # Start the full stack (Dify + microservice)
make down                      # Stop everything + remove volumes
make logs                      # Stream logs from all services
make ps                        # Show container status
make rebuild-video-extractor   # Rebuild only the microservice
make rebuild-api               # Rebuild only the Dify API (optional)
```

---

## 🛡️ Security Notes

- Do **NOT** commit API keys or secrets.
- `.env` is strictly ignored by Git.
- Workflow YAML files should contain only placeholders, never real keys.
- GitHub push protection is enabled on this repository.

If a push is rejected:

1. Open the file and remove the secret.
2. Amend your commit:

   ```bash
   git commit --amend --no-edit
   ```

3. Push again:

   ```bash
   git push --force
   ```

4. Rotate the exposed key in your provider dashboard.

---

## 🧪 Troubleshooting

### ❌ “Cannot connect to video-extractor”

Check logs:

```bash
docker compose -f docker/docker-compose.yaml logs video-extractor
```

Common issues:

- Missing dependencies in the microservice
- Exceptions in `main.py`
- Rare port conflicts

---

### ❌ UI loads blank

Usually caused by stale containers:

```bash
make down
make up
```

Then reload: http://localhost:3000

---

### ❌ Workflow import fails

Confirm:

- You used the file: `workflows/MVP-complete.yml`
- There are no secrets in the YAML
- The Dify version matches (this fork is aligned)

---

## 🤝 Contributing (Internal Team)

1. Create a feature branch:

   ```bash
   git checkout -b feature/my-change
   ```

2. Implement & test your changes:

   ```bash
   make up
   make logs
   ```

3. Ensure no secrets are committed.
4. Push your branch & open a PR into `main`.

All MEDAI/OSCE development should stay inside this repository.
