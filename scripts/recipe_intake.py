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
import re
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRAME_DIR = ROOT / ".runtime" / "recipe_frames"
MAX_FRAMES = 10
MAX_FILESIZE = "150M"
# Keep the download well under chat mode's 180s ceiling (brain.py TIMEOUT["chat"]),
# leaving room for the brain to Read the frames (vision) and compose a reply.
DOWNLOAD_TIMEOUT = 90
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")
GEMINI_HTTP_TIMEOUT_MS = 70_000
GEMINI_FILE_WAIT = 45  # max seconds to wait for an uploaded video to become ACTIVE
SCENE_THRESHOLD = 0.3
MIN_SCENE_FRAMES = 3  # below this, the clip is low-motion → fall back to even sampling


def scene_filter(threshold: float) -> str:
    return f"select='gt(scene,{threshold})'"


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


def _download_video(url: str, dest: pathlib.Path) -> bool:
    """Download a clip to dest via yt-dlp. Returns True on success. Shared by frames + gemini."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dl = subprocess.run(
            [_bin("yt-dlp", "YT_DLP_BIN"), "-f", "mp4/best", "--no-warnings",
             "--no-playlist", "--max-filesize", MAX_FILESIZE, "-o", str(dest), url],
            capture_output=True, timeout=DOWNLOAD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False
    return dl.returncode == 0 and dest.exists()


def cmd_frames(url: str) -> dict:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    vid = "".join(c for c in url if c.isalnum())[-16:] or "clip"
    workdir = FRAME_DIR / vid
    workdir.mkdir(exist_ok=True)
    mp4 = workdir / "clip.mp4"
    if not _download_video(url, mp4):
        return {"error": "download failed or file too large", "frames": []}
    # Scene-detection: one frame per significant cut, capped at MAX_FRAMES.
    try:
        subprocess.run(
            [_bin("ffmpeg", "FFMPEG_BIN"), "-hide_banner", "-loglevel", "error",
             "-i", str(mp4), "-vf", scene_filter(SCENE_THRESHOLD), "-vsync", "vfr",
             "-frames:v", str(MAX_FRAMES), "-q:v", "3", "-y", str(workdir / "scene_%02d.jpg")],
            capture_output=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        pass
    frames = [str(p) for p in sorted(workdir.glob("scene_*.jpg"))]
    if len(frames) >= MIN_SCENE_FRAMES:
        return {"frames": frames}
    # Low-motion clip → even sampling guarantees coverage.
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


def is_youtube(url: str) -> bool:
    return bool(re.search(r"youtube\.com|youtu\.be", url, re.IGNORECASE))


def _gemini_prompt(caption: str) -> str:
    base = (
        "看這支料理影片,給我關於它的『完整理解』(不只是食譜):\n"
        "1) 菜名\n2) 食材(盡量含份量)\n3) 步驟\n"
        "4) 值得注意的細節:技巧、火候、時間、感官線索(看到/聽到/聞到什麼才算對)、"
        "視覺觀察、主廚會注意的 nuance。\n"
        "最後,把來源(影片字幕/貼文)原本寫的食材與步驟『原文照抄』另列一段,"
        "標題寫「原文食譜」,讓我能保留原始食譜。\n全部用繁體中文。"
    )
    if caption.strip():
        base += f"\n\n【貼文文字(請一併參考並原文保留)】\n{caption.strip()}"
    return base


def _file_state(f) -> str:
    return str(getattr(f.state, "name", f.state)).upper()


def cmd_gemini(url: str) -> dict:
    """Gemini watches the video (+caption) → comprehensive understanding. Never raises."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"error": "no GEMINI_API_KEY"}
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"error": "google-genai not installed"}
    caption = cmd_caption(url).get("description", "")  # yt-dlp metadata only (no download)
    prompt = _gemini_prompt(caption)
    try:
        client = genai.Client(api_key=key,
                              http_options=types.HttpOptions(timeout=GEMINI_HTTP_TIMEOUT_MS))
        if is_youtube(url):
            contents = [types.Part(file_data=types.FileData(file_uri=url)), prompt]
        else:
            mp4 = FRAME_DIR / ("g_" + ("".join(c for c in url if c.isalnum())[-16:] or "clip")) / "clip.mp4"
            if not _download_video(url, mp4):
                return {"error": "download failed or file too large"}
            gfile = client.files.upload(file=str(mp4))
            waited = 0
            while _file_state(gfile) == "PROCESSING" and waited < GEMINI_FILE_WAIT:
                time.sleep(3)
                waited += 3
                gfile = client.files.get(name=gfile.name)
            if _file_state(gfile) != "ACTIVE":
                return {"error": f"gemini file state {_file_state(gfile)}"}
            contents = [gfile, prompt]
        text = ""
        for m in GEMINI_MODELS:
            try:
                text = client.models.generate_content(model=m, contents=contents).text
                break
            except Exception:  # noqa: BLE001 — try next model
                continue
        return {"source": "gemini", "understanding": text} if text else {"error": "empty gemini response"}
    except Exception as e:  # noqa: BLE001 — degrade to caption upstream
        return {"error": str(e)[:200]}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("caption").add_argument("url")
    sub.add_parser("frames").add_argument("url")
    sub.add_parser("gemini").add_argument("url")
    args = p.parse_args()
    if args.cmd == "caption":
        result = cmd_caption(args.url)
    elif args.cmd == "frames":
        result = cmd_frames(args.url)
    else:
        result = cmd_gemini(args.url)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
