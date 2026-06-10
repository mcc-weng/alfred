# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Extract a recipe source for chat mode: caption text or sampled video frames.

Read-only on state; writes only throwaway frames under .runtime/recipe_frames/.
Shells out to yt-dlp (metadata/download) and ffmpeg/ffprobe (frame sampling); each is
resolved via PATH or the YT_DLP_BIN / FFMPEG_BIN / FFPROBE_BIN env override.

Usage:
  uv run scripts/recipe_intake.py caption <url>   # JSON: title/uploader/duration/
                                                  # description/is_thin (no download)
  uv run scripts/recipe_intake.py frames <url>    # JSON: {"frames": [paths]}
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRAME_DIR = ROOT / ".runtime" / "recipe_frames"
MAX_FRAMES = 10
MAX_FILESIZE = "150M"


def _bin(name: str, env: str) -> str:
    return os.environ.get(env) or shutil.which(name) or name


def extract_fields(info: dict) -> dict:
    return {
        "title": info.get("title") or "",
        "uploader": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration") or 0,
        "description": info.get("description") or "",
    }


def is_thin(description: str) -> bool:
    d = description.strip()
    if len(d) < 60:
        return True
    return not any(ch.isdigit() for ch in d)  # recipes carry quantities


def frame_timestamps(duration: float, max_frames: int = MAX_FRAMES) -> list[float]:
    if duration <= 0:
        return [0.0]
    n = max(1, min(max_frames, int(duration // 3) or 1))
    step = duration / (n + 1)
    return [round(step * (i + 1), 2) for i in range(n)]


def _probe_duration(mp4: pathlib.Path) -> float:
    try:
        out = subprocess.run(
            [_bin("ffprobe", "FFPROBE_BIN"), "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", str(mp4)],
            capture_output=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return 0.0
    try:
        return float(out.stdout.decode().strip())
    except ValueError:
        return 0.0


def cmd_caption(url: str) -> dict:
    try:
        out = subprocess.run(
            [_bin("yt-dlp", "YT_DLP_BIN"), "-j", "--skip-download",
             "--no-warnings", "--no-playlist", url],
            capture_output=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}
    if out.returncode != 0:
        return {"error": out.stderr.decode()[:300]}
    try:
        info = json.loads(out.stdout.decode())
    except json.JSONDecodeError:
        return {"error": "bad json from yt-dlp"}
    fields = extract_fields(info)
    fields["is_thin"] = is_thin(fields["description"])
    return fields


def cmd_frames(url: str) -> dict:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    vid = "".join(c for c in url if c.isalnum())[-16:] or "clip"
    workdir = FRAME_DIR / vid
    workdir.mkdir(exist_ok=True)
    mp4 = workdir / "clip.mp4"
    try:
        dl = subprocess.run(
            [_bin("yt-dlp", "YT_DLP_BIN"), "-f", "mp4/best", "--no-warnings",
             "--no-playlist", "--max-filesize", MAX_FILESIZE, "-o", str(mp4), url],
            capture_output=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "frames": []}
    if dl.returncode != 0 or not mp4.exists():
        return {"error": dl.stderr.decode()[:200] or "download failed", "frames": []}
    frames = []
    for i, ts in enumerate(frame_timestamps(_probe_duration(mp4))):
        fp = workdir / f"frame_{i:02d}.jpg"
        try:
            subprocess.run(
                [_bin("ffmpeg", "FFMPEG_BIN"), "-hide_banner", "-loglevel", "error",
                 "-ss", str(ts), "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
                 "-y", str(fp)],
                capture_output=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            continue
        if fp.exists():
            frames.append(str(fp))
    return {"frames": frames}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("caption").add_argument("url")
    sub.add_parser("frames").add_argument("url")
    args = p.parse_args()
    result = cmd_caption(args.url) if args.cmd == "caption" else cmd_frames(args.url)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
