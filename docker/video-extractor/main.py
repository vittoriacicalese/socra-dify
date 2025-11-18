# main.py
"""
Video Frame + Audio Extractor Service

Features
- Accepts MP4 via:
  1) multipart/form-data `videos` as files (UploadFile),
  2) multipart/form-data `videos_bytes` as raw bytes (no filename),
  3) `video_url` query param (the service downloads it).
- Extracts every Nth frame with optional color conversion and resizing.
- Optionally extracts audio to mono 16 kHz WAV.
- Serves artifacts under /static and returns a JSON manifest link:
    {
      "video": "<original filename or generated>",
      "frames_saved": <int>,
      "frames_json_url": "http://<host>/static/<stem>_frames.json",
      "wav": "http://<host>/static/<stem>.wav" | "<path>" | null
    }

Environment
- OUTPUT_DIR: absolute path where frames and WAVs are written (default: /app/outputs)
- PUBLIC_BASE_URL: optional external base URL for returned links (default: request.base_url)
"""

from __future__ import annotations

import json
import os
import subprocess
import time  # <-- ADDED: timing
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple
from uuid import uuid4
from urllib.request import urlopen, Request as URLRequest
from urllib.error import URLError, HTTPError

import cv2
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, Request
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

# -----------------------------------------------------------------------------
# Paths and constants
# -----------------------------------------------------------------------------
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/app/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

SERVICE_TITLE = "Video Frame + Audio Extractor"
SERVICE_VERSION = "3.2.0"
SERVICE_DESC = "Extract every Nth frame from MP4 videos and export WAV audio."
PRINT_PREFIX = "[video-extractor]"

print(f"{PRINT_PREFIX} starting")
print(f"{PRINT_PREFIX} OUTPUT_DIR={OUTPUT_DIR}")
print(f"{PRINT_PREFIX} PUBLIC_BASE_URL={PUBLIC_BASE_URL or '(auto from request)'}")

# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(title=SERVICE_TITLE, version=SERVICE_VERSION, description=SERVICE_DESC)

# Serve generated files
app.mount("/static", StaticFiles(directory=str(OUTPUT_DIR)), name="static")


@app.get("/health", response_class=ORJSONResponse)
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _safe_stem(filename: Optional[str]) -> str:
    stem = (Path(filename).stem if filename else "").strip() or f"video-{uuid4().hex[:8]}"
    clean = "".join(ch for ch in stem if ch.isalnum() or ch in ("-", "_"))
    return clean[:128] or f"video-{uuid4().hex[:8]}"


def _extract_audio_to_wav(src_mp4: str, out_dir: Path, base_stem: str) -> Path:
    """
    Extract mono 16 kHz AAC (M4A) using ffmpeg.

    NOTE: name kept for backwards-compatibility with callers;
    it now produces <base_stem>.m4a instead of raw PCM WAV.
    """
    wav_path = out_dir / f"{base_stem}.m4a"
    cmd = [
        "ffmpeg", "-y", "-i", src_mp4,
        "-vn",
        "-acodec", "aac",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", os.getenv("AUDIO_BITRATE", "64k"),
        str(wav_path),
    ]
    print(PRINT_PREFIX, "ffmpeg:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    return wav_path


def _write_frames_json(frames: List[str], base_stem: str) -> Path:
    """Write frame URLs to JSON file and return the path."""
    manifest = OUTPUT_DIR / f"{base_stem}_frames.json"
    manifest.write_text(json.dumps(frames, indent=2), encoding="utf-8")
    return manifest


def _save_uploadfile_to_tmp(f: UploadFile) -> Tuple[str, str]:
    """Persist UploadFile to OUTPUT_DIR. Returns (tmp_path, inferred_name)."""
    tmp_path = OUTPUT_DIR / f"{uuid4().hex}.mp4"
    inferred_name = f.filename or "upload.mp4"
    return str(tmp_path), inferred_name


def _save_bytes_to_tmp(data: bytes, name_hint: Optional[str] = None) -> Tuple[str, str]:
    """Persist raw bytes to OUTPUT_DIR. Returns (tmp_path, inferred_name)."""
    inferred = name_hint or f"video-{uuid4().hex[:8]}.mp4"
    tmp_path = OUTPUT_DIR / f"{uuid4().hex}.mp4"
    with open(tmp_path, "wb") as out:
        out.write(data)
    return str(tmp_path), inferred


def _download_url_to_tmp(url: str) -> Tuple[str, str]:
    """Download a URL to OUTPUT_DIR using stdlib. Returns (tmp_path, inferred_name)."""
    stem = _safe_stem(url.split("/")[-1] or "video")
    inferred_name = f"{stem}.mp4" if not stem.endswith(".mp4") else stem
    tmp_path = OUTPUT_DIR / f"{uuid4().hex}.mp4"
    req = URLRequest(url, headers={"User-Agent": "video-extractor/1.0"})
    with urlopen(req, timeout=60) as r, open(tmp_path, "wb") as out:
        # Stream to file in chunks to support large OSCE videos
        while True:
            chunk = r.read(1024 * 1024)  # 1 MiB
            if not chunk:
                break
            out.write(chunk)
    return str(tmp_path), inferred_name


# -----------------------------------------------------------------------------
# Route
# -----------------------------------------------------------------------------
@app.post("/extract", response_class=ORJSONResponse)
async def extract(
    request: Request,
    # Accept well-formed file parts
    videos: Optional[List[UploadFile]] = File(
        None, description="One or more MP4 files (proper file parts)."
    ),
    # Accept malformed parts where `videos` arrives without filename as raw bytes
    videos_bytes: Optional[List[bytes]] = File(
        None, description="One or more MP4 payloads when the form part lacks filename."
    ),
    # Allow server-side fetching to avoid large multipart bodies
    video_url: Optional[str] = Query(
        None, description="Optional URL to an MP4 the service should fetch."
    ),
    every_nth: int = Query(30, description="Take every Nth frame."),
    resize_w: Optional[int] = Query(None, description="Resize width."),
    resize_h: Optional[int] = Query(None, description="Resize height."),
    convert: Optional[str] = Query(None, regex="^(rgb|gray)?$", description="Optional color conversion."),
    max_frames: int = Query(200, description="Maximum frames to extract."),
    return_wav: Optional[str] = Query(None, regex="^(link|path)?$", description="'link' for URL, 'path' for FS path."),
) -> Dict[str, Any]:
    """
    Returns:
      {
        "results": [
          {
            "video": "<name>",
            "frames_saved": <int>,
            "frames_json_url": "http://.../static/<stem>_frames.json",
            "wav": "http://.../static/<stem>.wav" | "<path>" | null
          }
        ]
      }
    """
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    results: List[Dict[str, Any]] = []

    # Build list of (tmp_path, inferred_name, base_stem)
    tasks: List[Tuple[str, str, str]] = []

    try:
        # Proper files
        if videos:
            for f in videos:
                tmp_path_str, inferred = _save_uploadfile_to_tmp(f)
                # Stream upload to disk in chunks to avoid loading full MP4 into memory
                with open(tmp_path_str, "wb") as out_file:
                    while True:
                        chunk = await f.read(1024 * 1024)  # 1 MiB
                        if not chunk:
                            break
                        out_file.write(chunk)
                tasks.append((tmp_path_str, inferred, _safe_stem(inferred)))

        # Raw bytes fallback when no filename/content-type provided
        if videos_bytes:
            for idx, data in enumerate(videos_bytes, start=1):
                tmp_path_str, inferred = _save_bytes_to_tmp(data, f"video-{idx}.mp4")
                tasks.append((tmp_path_str, inferred, _safe_stem(inferred)))

        # URL fallback
        if video_url and not tasks:
            try:
                tmp_path_str, inferred = _download_url_to_tmp(video_url)
                tasks.append((tmp_path_str, inferred, _safe_stem(inferred)))
            except (URLError, HTTPError) as e:
                print(PRINT_PREFIX, "download failed:", repr(e))
                raise HTTPException(status_code=400, detail="Failed to download video_url")

        if not tasks:
            raise HTTPException(status_code=400, detail="No video provided")

        # Process each video
        for tmp_path_str, inferred_name, base_stem in tasks:
            cap = cv2.VideoCapture(tmp_path_str)
            if not cap.isOpened():
                print(PRINT_PREFIX, "cv2 failed to open:", tmp_path_str)
                raise HTTPException(status_code=400, detail=f"Failed to open video: {inferred_name}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            print(f"{PRINT_PREFIX} video={inferred_name} fps={fps} frames={total} nth={every_nth} max={max_frames}")

            frame_urls: List[str] = []
            frame_idx = 0
            saved = 0

            # --- ADDED: start timing frames stage ---
            video_start = time.perf_counter()

            try:
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break

                    if frame_idx % every_nth == 0:
                        if convert == "rgb":
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        elif convert == "gray":
                            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                        if resize_w and resize_h:
                            frame = cv2.resize(frame, (int(resize_w), int(resize_h)))

                        out_path = OUTPUT_DIR / f"{base_stem}_{frame_idx}.jpg"
                        ok = cv2.imwrite(str(out_path), frame)
                        if ok:
                            frame_urls.append(f"{base_url}/static/{out_path.name}")
                            saved += 1
                            if saved % 50 == 0:
                                print(f"{PRINT_PREFIX} saved {saved} frames")

                            if saved >= max_frames:
                                print(f"{PRINT_PREFIX} hit max_frames={max_frames}, stopping")
                                break

                    frame_idx += 1
            finally:
                cap.release()

            # --- ADDED: end timing frames stage ---
            frames_elapsed = time.perf_counter() - video_start

            # Write manifest file
            manifest = _write_frames_json(frame_urls, base_stem)
            manifest_url = f"{base_url}/static/{manifest.name}"

            # Optional audio
            wav_value: Optional[str] = None
            audio_elapsed = 0.0  # <-- ADDED: default audio time
            if return_wav:
                try:
                    audio_start = time.perf_counter()  # <-- ADDED: start timing audio
                    wav_path = _extract_audio_to_wav(tmp_path_str, OUTPUT_DIR, base_stem)
                    audio_elapsed = time.perf_counter() - audio_start  # <-- ADDED: end timing audio

                    if return_wav == "path":
                        wav_value = str(wav_path)
                    else:
                        wav_value = f"{base_url}/static/{wav_path.name}"
                except Exception as e:
                    print(f"{PRINT_PREFIX} audio extraction failed: {e!r}")

            # --- ADDED: log total timings ---
            total_elapsed = frames_elapsed + audio_elapsed
            print(
                f"{PRINT_PREFIX} timing video={inferred_name} "
                f"frames_s={frames_elapsed:.3f} audio_s={audio_elapsed:.3f} total_s={total_elapsed:.3f}"
            )

            results.append({
                "video": inferred_name,
                "frames_saved": saved,
                "frames_json_url": manifest_url,
                "wav": wav_value
            })

    finally:
        # If you want to delete tmp MP4s after processing, add safe cleanup here.
        pass

    return {"results": results}
