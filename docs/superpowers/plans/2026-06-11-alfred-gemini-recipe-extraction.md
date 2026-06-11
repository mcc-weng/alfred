# Alfred Gemini Video Recipe Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the caption→frames→Whisper fallback with Gemini watching the reel: the listener pre-fetches a comprehensive video understanding (IG → download+upload, YouTube → URL-direct) and injects it for 小當家 to enrich; caption + scene-detected frames remain as keyless fallbacks.

**Architecture:** Gemini is the extractor, 小當家 (Claude) the enricher. `recipe_intake.cmd_gemini(url)` returns a comprehensive understanding or `{error}` (never raises). The listener's deterministic pre-fetch becomes Gemini-first with caption fallback — same seam that already fixed history-anchoring. `cmd_frames` upgrades from even-sampling to scene-detection (keyless deep fallback). `google-genai` is lazy-imported so the keyless paths still work.

**Tech Stack:** Python 3.11 stdlib + `google-genai` (lazy-imported), `yt-dlp` + `ffmpeg`, run via `uv run`. `gemini-2.5-flash` (free tier). `pytest`. Headless `claude -p` (chat mode) as the enricher.

**Reference spec:** `docs/superpowers/specs/2026-06-11-alfred-gemini-recipe-extraction-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `scripts/recipe_intake.py` | Add `is_youtube`, `_gemini_prompt`, `cmd_gemini` (+ `_download_video` extraction, scene-detection in `cmd_frames`) | Modify |
| `tests/test_recipe_intake.py` | Unit-test `is_youtube`, `_gemini_prompt`, `_file_state`, `scene_filter` | Modify |
| `scripts/listener.py` | `_inject_recipe_context` becomes Gemini-first w/ caption fallback; add `format_understanding_injection`; `google-genai` dep | Modify |
| `tests/test_listener.py` | Unit-test `format_understanding_injection` | Modify |
| `prompts/chat.md` | Door #1: handle the injected Gemini understanding | Modify |

**Takes effect:** `listener.py` change needs a daemon restart (`install_daemon.sh`); `chat.md` is read fresh per turn.

---

## Task 1: `cmd_gemini` extractor + `_download_video` refactor

**Files:** Modify `scripts/recipe_intake.py`, `tests/test_recipe_intake.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_recipe_intake.py`:

```python
def test_is_youtube():
    assert ri.is_youtube("https://youtu.be/abc")
    assert ri.is_youtube("https://www.youtube.com/watch?v=abc")
    assert ri.is_youtube("https://www.youtube.com/shorts/abc")
    assert not ri.is_youtube("https://www.instagram.com/reel/abc")


def test_gemini_prompt_includes_caption_and_verbatim_ask():
    p = ri._gemini_prompt("黑糖 30g、水 300g")
    assert "黑糖 30g" in p          # caption fused in
    assert "原文食譜" in p          # asks Gemini to quote source verbatim (for 📌)
    assert "完整理解" in p          # asks for comprehensive understanding, not flat recipe


def test_gemini_prompt_no_caption_omits_caption_block():
    assert "貼文文字" not in ri._gemini_prompt("")


def test_file_state_reads_enum_or_str():
    class S: name = "ACTIVE"
    class F: state = S()
    assert ri._file_state(F()) == "ACTIVE"
    class F2: state = "processing"
    assert ri._file_state(F2()) == "PROCESSING"
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_recipe_intake.py -k "youtube or gemini_prompt or file_state" -v` → FAIL (`AttributeError`, no such functions).

- [ ] **Step 3: Add `import time`** to `scripts/recipe_intake.py` imports (after `import subprocess`):

```python
import subprocess
import sys
import time
```

- [ ] **Step 4: Add the constants** after `DOWNLOAD_TIMEOUT = 90`:

```python
GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")
GEMINI_HTTP_TIMEOUT_MS = 70_000
GEMINI_FILE_WAIT = 45  # max seconds to wait for an uploaded video to become ACTIVE
```

- [ ] **Step 5: Extract `_download_video`** — replace the download block inside `cmd_frames`. First add this helper (place it just above `cmd_frames`):

```python
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
```

Then change the top of `cmd_frames` from its current download try/except to use it:

```python
def cmd_frames(url: str) -> dict:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    vid = "".join(c for c in url if c.isalnum())[-16:] or "clip"
    workdir = FRAME_DIR / vid
    workdir.mkdir(exist_ok=True)
    mp4 = workdir / "clip.mp4"
    if not _download_video(url, mp4):
        return {"error": "download failed or file too large", "frames": []}
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
```

(Scene-detection is added in Task 2; this step only swaps in `_download_video` so `cmd_gemini` can share it.)

- [ ] **Step 6: Add the Gemini functions** — place after `cmd_frames`:

```python
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
                time.sleep(3); waited += 3
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
```

- [ ] **Step 7: Add a `gemini` subcommand to `main()`** (for standalone testing) — in the argparse block add alongside `caption`/`frames`:

```python
    sub.add_parser("gemini").add_argument("url")
```

and extend the dispatch line:

```python
    if args.cmd == "caption":
        result = cmd_caption(args.url)
    elif args.cmd == "frames":
        result = cmd_frames(args.url)
    else:
        result = cmd_gemini(args.url)
```

- [ ] **Step 8: Run the tests** — `uv run pytest tests/test_recipe_intake.py -v` → all PASS. Then full suite `uv run pytest -q` → green.

- [ ] **Step 9: Smoke-test live** (network + key; `GEMINI_API_KEY` in `.env`):

```bash
uv run --with google-genai python -c "import sys; sys.path.insert(0,'scripts'); from discord_io import load_env; load_env(); import recipe_intake as ri; r=ri.cmd_gemini('https://www.instagram.com/reel/DYXDnWfPROW/'); print('source:', r.get('source'), '| err:', r.get('error')); print(r.get('understanding','')[:400])"
```
Expected: `source: gemini`, no error, and a 繁中 understanding of 家常鹽水雞 with technique detail + an 「原文食譜」 section.

- [ ] **Step 10: Commit**

```bash
git add scripts/recipe_intake.py tests/test_recipe_intake.py
git commit -m "feat(intake): cmd_gemini — comprehensive video understanding (YT url-direct, IG download+upload); share _download_video"
```

---

## Task 2: scene-detection for the `frames` fallback

**Files:** Modify `scripts/recipe_intake.py`, `tests/test_recipe_intake.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_recipe_intake.py`:

```python
def test_scene_filter_builds_threshold_expr():
    assert ri.scene_filter(0.3) == "select='gt(scene,0.3)'"
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_recipe_intake.py -k scene_filter -v` → FAIL.

- [ ] **Step 3: Add constants + helper** — after the `GEMINI_FILE_WAIT` constant:

```python
SCENE_THRESHOLD = 0.3
MIN_SCENE_FRAMES = 3  # below this, the clip is low-motion → fall back to even sampling


def scene_filter(threshold: float) -> str:
    return f"select='gt(scene,{threshold})'"
```

- [ ] **Step 4: Upgrade `cmd_frames`** — replace the per-timestamp even-sampling loop (the body after the `_download_video` guard) with scene-detection first, even-sampling as underflow fallback:

```python
    if not _download_video(url, mp4):
        return {"error": "download failed or file too large", "frames": []}
    # Scene-detection: one frame per significant cut, capped at MAX_FRAMES.
    scene_glob = workdir / "scene_%02d.jpg"
    try:
        subprocess.run(
            [_bin("ffmpeg", "FFMPEG_BIN"), "-hide_banner", "-loglevel", "error",
             "-i", str(mp4), "-vf", scene_filter(SCENE_THRESHOLD), "-vsync", "vfr",
             "-frames:v", str(MAX_FRAMES), "-q:v", "3", "-y", str(scene_glob)],
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
```

- [ ] **Step 5: Run tests** — `uv run pytest tests/test_recipe_intake.py -v` → PASS. Full suite green.

- [ ] **Step 6: Commit**

```bash
git add scripts/recipe_intake.py tests/test_recipe_intake.py
git commit -m "feat(intake): scene-detection frame sampling (cap + even-sampling underflow fallback)"
```

---

## Task 3: Wire Gemini-first into the listener

**Files:** Modify `scripts/listener.py`, `tests/test_listener.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_listener.py`:

```python
def test_format_understanding_injection_carries_text_and_guard():
    out = listener.format_understanding_injection(
        "https://insta/reel/x", {"source": "gemini", "understanding": "家常鹽水雞:雞腿1支..."})
    assert "家常鹽水雞" in out          # the Gemini understanding
    assert "聊天記錄" in out            # anti-history-anchoring guard
    assert "原始食譜" in out            # tells 小當家 to preserve the verbatim original


def test_format_understanding_injection_none_on_error():
    assert listener.format_understanding_injection("u", {"error": "quota"}) is None
```

- [ ] **Step 2: Run to verify they fail** — `uv run pytest tests/test_listener.py -k understanding -v` → FAIL.

- [ ] **Step 3: Add `google-genai` to listener deps** — edit the `# /// script` header:

```python
# dependencies = ["discord.py", "google-genai"]
```

- [ ] **Step 4: Add `format_understanding_injection`** — in `scripts/listener.py`, right after `format_caption_injection`:

```python
def format_understanding_injection(url: str, result: dict) -> str | None:
    """Inject Gemini's comprehensive video understanding for the brain. Returns None on
    error so the caller can fall back to the caption."""
    if result.get("error") or not result.get("understanding"):
        return None
    return (
        f"\n[系統已用 Gemini 看完「這則訊息裡的影片」{url},完整理解如下 — "
        f"**請只用這一份來做食譜卡,絕對不要從聊天記錄挪用別道菜**;"
        f"把其中「原文食譜」那段的食材/步驟原文放進 📌 原始食譜區塊:\n"
        f"{result['understanding']}\n]"
    )
```

- [ ] **Step 5: Rename + rewrite the injector** — replace the whole `_inject_recipe_captions` method with `_inject_recipe_context` (Gemini-first, caption fallback):

```python
    async def _inject_recipe_context(self, lines: list[dict]) -> None:
        """For any IG/YT link, pre-fetch the recipe BEFORE the brain — Gemini watches the
        video (richest); fall back to caption if Gemini errors/times-out/has no key. Either
        way the brain enriches the EXACT dropped recipe, never one from chat history."""
        for line in lines:
            url = extract_recipe_url(line["content"])
            if not url:
                continue
            try:
                g = await asyncio.to_thread(recipe_intake.cmd_gemini, url)
            except Exception as e:  # noqa: BLE001
                g = {"error": str(e)[:120]}
            inj = format_understanding_injection(url, g)
            if inj is None:  # Gemini unavailable → deterministic caption fallback
                try:
                    cap = await asyncio.to_thread(recipe_intake.cmd_caption, url)
                except Exception as e:  # noqa: BLE001 — never let intake prep crash the turn
                    print(f"recipe pre-fetch failed for {url}: {e}", flush=True)
                    continue
                inj = format_caption_injection(url, cap)
            line["content"] += inj
```

- [ ] **Step 6: Update the call site** in `_chat_reply` — change `await self._inject_recipe_captions(lines)` to:

```python
        await self._inject_recipe_context(lines)  # deterministic: Gemini/caption pre-fetch before the brain
```

- [ ] **Step 7: Run tests** — `uv run pytest tests/test_listener.py -v` → PASS. Full suite `uv run pytest -q` → green.

- [ ] **Step 8: Commit**

```bash
git add scripts/listener.py tests/test_listener.py
git commit -m "feat(intake): listener pre-fetches Gemini video understanding (caption fallback); google-genai dep"
```

---

## Task 4: Teach chat mode about the Gemini understanding

**Files:** Modify `prompts/chat.md`. No unit test (prompt) — verified in Task 5.

- [ ] **Step 1: Update door #1** — replace the door #1 line (currently begins `1. **影片連結** → 訊息裡通常已附「[系統已自動抓取…]」`):

```markdown
1. **影片連結** → 訊息裡通常已附系統先做好的食譜資料:可能是「Gemini 完整理解」(系統已看完影片+貼文),也可能是「[系統已自動抓取…]」的 caption。**有就直接用那一份做食譜卡**,不要再自己跑 caption。Gemini 那份比較完整 — 用它的細節做卡片,並把其中「原文食譜」段落的食材/步驟原文放進 📌 原始食譜。caption 那份若 `is_thin` 為 false 也夠用。若附的是 `error`(影片私密/打不開)→ 跳第 2 點試 frames;frames 也 error 就走第 6 點。
```

- [ ] **Step 2: Sanity-check the render**

```bash
uv run python -c "import sys; sys.path.insert(0,'scripts'); import brain; p=brain.build_prompt('chat',[],[]); print('Gemini 完整理解' in p and '原始食譜' in p)"
```
Expected: `True`.

- [ ] **Step 3: Commit**

```bash
git add prompts/chat.md
git commit -m "feat(intake): chat mode uses the injected Gemini understanding (falls back to caption)"
```

---

## Task 5: Live verification via real Discord use

**Files:** none. Reinstall the daemon (listener changed), then drop real sources.

- [ ] **Step 1: Reinstall the daemon** — `bash scripts/install_daemon.sh`; confirm `.runtime/listener.log` shows `READY`.

- [ ] **Step 2: Gemini path (captioned IG reel)** — drop a NEW recipe reel in #小當家的廚房. Expect a richer card than caption-alone (technique/timing cues Gemini saw), the 📌 verbatim original, saved + queued, no "Hit a snag". Confirm `state/cookbook/<slug>.md` written.

- [ ] **Step 3: YouTube path (URL-direct, no download)** — drop a YouTube recipe link. Expect a card; confirm in `.runtime/recipe_frames/` that **no `g_*` download dir** was created for it (YT goes URL-direct).

- [ ] **Step 4: Caption fallback** — temporarily break the key (rename it in `.env` to `GEMINI_API_KEY_OFF`), reinstall daemon, drop a reel → still saves via caption (no crash). Restore the key + reinstall after.

- [ ] **Step 5: Webpage routing (no Gemini)** — drop a recipe-blog URL → 小當家 uses WebFetch, saves a card; confirm no Gemini call / download happened for it.

- [ ] **Step 6: Commit real-use cookbook entries**

```bash
git add state/cookbook/
git commit -m "ritual: Gemini extraction live verification — richer cards from real reels"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Gemini extractor, comprehensive understanding, verbatim original → Task 1 (`cmd_gemini` + `_gemini_prompt` asks for 原文食譜). ✅
- IG download+upload / YT URL-direct branch → Task 1 (`is_youtube`). ✅
- Lazy `google-genai`, never-raises, key-missing handling → Task 1. ✅
- Frames scene-detection + cap + underflow fallback → Task 2. ✅
- Listener Gemini-first with caption fallback → Task 3. ✅
- Source routing (Gemini only for IG/YT; webpage→WebFetch) → unchanged `extract_recipe_url`; verified Task 5 step 5. ✅
- chat.md uses the understanding, preserves 📌 → Task 4. ✅
- Fallback ladder (Gemini→caption→frames→screenshot) → Task 3 + Task 2 + existing doors. ✅
- No Whisper → nothing added. ✅

**Placeholder scan:** No TBD/TODO; every code step is complete; commands have expected output. ✅

**Type/name consistency:** `cmd_gemini`/`is_youtube`/`_gemini_prompt`/`_file_state`/`scene_filter`/`_download_video` (recipe_intake) and `format_understanding_injection`/`_inject_recipe_context` (listener) are referenced consistently across their tests, definitions, and call sites. `_inject_recipe_context` replaces `_inject_recipe_captions` everywhere (definition + `_chat_reply` call site). ✅
