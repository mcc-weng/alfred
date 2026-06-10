# Alfred Recipe Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let someone drop a recipe source (IG/YT link, webpage, image, file, or pasted text) into #小當家的廚房 and have 小當家 extract the recipe, save it to the cookbook, and queue it as a craving for the next weekly ritual.

**Architecture:** Expand the existing `chat` brain mode rather than add a new mode. Two new narrow helper scripts give the brain controlled capabilities: `recipe_intake.py` (extract caption or sampled video frames via `yt-dlp`/`ffmpeg`) and `save_recipe.py` (write `state/cookbook/<slug>.md` + append a craving to `state/inbox.md`, reusing `capture.append_note`). The brain never gets raw `Write`/`yt-dlp`/`ffmpeg` — only the two allowlisted scripts plus `WebFetch`. Caption-first; frames only when the caption is thin. Saved cravings ride the existing `inbox.md` → Sunday ritual loop, so the current locked plan is never mutated.

**Tech Stack:** Python 3.11 stdlib only (`subprocess`, `argparse`, `json`, `re`, `shutil`, `pathlib`), run via `uv run`. `yt-dlp` + `ffmpeg`/`ffprobe` as external binaries (already installed). `pytest` for unit tests. Headless `claude -p` (chat mode) as the brain.

**Reference spec:** `docs/superpowers/specs/2026-06-10-alfred-recipe-intake-design.md`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `scripts/save_recipe.py` | Controlled write-seam: cookbook file + inbox craving. Dedupes by slug. | Create |
| `tests/test_save_recipe.py` | Unit tests for `slugify`, `cookbook_markdown`, `craving_note`. | Create |
| `scripts/recipe_intake.py` | Extractor: `caption` (metadata/description + thin hint) and `frames` (download + sample). | Create |
| `tests/test_recipe_intake.py` | Unit tests for `extract_fields`, `is_thin`, `frame_timestamps`. | Create |
| `scripts/brain.py` | Add the three new tools to `CHAT_TOOLS`. | Modify (line 23) |
| `tests/test_brain.py` | Assert `CHAT_TOOLS` carries the new tools. | Modify (add one test) |
| `prompts/chat.md` | Add the "料理擷取" intake section. | Modify |

**Task order rationale:** Task 1 builds the back-end write-seam (testable standalone). Task 2 builds the extractor (testable standalone). Task 3 wires the tools into chat mode. Task 4 teaches the brain how to use them. Task 5 verifies end-to-end through real Discord use (per the project's verify-via-real-use rule — prompts and network paths are not unit-tested).

---

## Task 1: `save_recipe.py` — cookbook + craving write-seam

**Files:**
- Create: `scripts/save_recipe.py`
- Test: `tests/test_save_recipe.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_save_recipe.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import save_recipe as sr


def test_slugify_basic():
    assert sr.slugify("Milk-Mochi Dessert Soup") == "milk-mochi-dessert-soup"


def test_slugify_strips_punct_and_case():
    assert sr.slugify("  Beef Chow Mein!! ") == "beef-chow-mein"


def test_slugify_cjk_returns_empty():
    # Non-Latin titles slug to empty; main() then requires an explicit --slug.
    assert sr.slugify("鮮奶麻糬甜湯") == ""


def test_cookbook_markdown_structure():
    body = "dessert · ~15 min · serves 2\n\n**Ingredients:** 黑糖 30g\n\n**Steps:** 1. 煮。"
    md = sr.cookbook_markdown(
        "鮮奶麻糬甜湯", body,
        "https://www.instagram.com/reel/DUNy6_ADXyp/",
        "ball", "IG reel", "2026-06-10",
    )
    assert md.startswith("# 鮮奶麻糬甜湯\n")
    assert "**Ingredients:** 黑糖 30g" in md
    assert "**Source:** https://www.instagram.com/reel/DUNy6_ADXyp/ (IG reel, shared by ball) · saved 2026-06-10" in md
    assert md.rstrip().endswith("## Verdicts")


def test_craving_note_points_at_cookbook():
    note = sr.craving_note("鮮奶麻糬甜湯", "milk-mochi-dessert-soup", "ball", "IG reel")
    assert note == "想做鮮奶麻糬甜湯 — 已存 cookbook/milk-mochi-dessert-soup.md (ball, IG reel)"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_save_recipe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'save_recipe'`

- [ ] **Step 3: Write `scripts/save_recipe.py`**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Save an extracted recipe to the cookbook + queue it as a craving for the ritual.

Chat mode's recipe-intake write-seam — the ONLY recipe writer. Narrow blast radius:
writes one state/cookbook/<slug>.md and appends one craving line to state/inbox.md
(via capture.append_note, DRY). Dedupes by slug: if the cookbook file already exists it
is left untouched (preserving any verdicts) and no craving is re-queued.

Usage:
  echo "<recipe body markdown>" | uv run scripts/save_recipe.py \\
      --title "鮮奶麻糬甜湯" --slug "milk-mochi-dessert-soup" \\
      --source "https://www.instagram.com/reel/DUNy6_ADXyp/" \\
      --by "ball" --kind "IG reel"

Body (stdin) = the 繁中 card minus the H1 title: a meta line, **Ingredients:** …,
**Steps:** … . The script wraps it with the title, a **Source:** line, and ## Verdicts.
"""
import argparse
import datetime
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import capture  # reuse append_note for inbox writes (DRY)

ROOT = pathlib.Path(__file__).resolve().parent.parent
COOKBOOK = ROOT / "state" / "cookbook"
INBOX = ROOT / "state" / "inbox.md"


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def cookbook_markdown(title: str, body: str, source: str, by: str,
                      kind: str, date: str) -> str:
    src = f"**Source:** {source} ({kind}, shared by {by}) · saved {date}"
    return f"# {title}\n\n{body.strip()}\n\n{src}\n\n## Verdicts\n"


def craving_note(title: str, slug: str, by: str, kind: str) -> str:
    return f"想做{title} — 已存 cookbook/{slug}.md ({by}, {kind})"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--slug", default="")
    p.add_argument("--source", required=True)
    p.add_argument("--by", default="someone")
    p.add_argument("--kind", default="link")
    args = p.parse_args()

    slug = slugify(args.slug or args.title)
    if not slug:
        sys.exit("empty slug — pass an ASCII --slug (the title may be non-Latin)")
    body = sys.stdin.read().strip()
    if not body:
        sys.exit("empty recipe body on stdin")

    path = COOKBOOK / f"{slug}.md"
    if path.exists():
        print(f"already in cookbook: {slug}")
        return
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        cookbook_markdown(args.title, body, args.source, args.by, args.kind, date),
        encoding="utf-8",
    )
    capture.append_note(INBOX, date, "craving",
                        craving_note(args.title, slug, args.by, args.kind))
    print(f"saved cookbook/{slug}.md + queued craving")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_save_recipe.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Smoke-test the CLI end-to-end (then clean up)**

Run:
```bash
printf 'dessert · ~15 min · serves 2\n\n**Ingredients:** 黑糖 30g · 牛奶 300g\n\n**Steps:** 1. 煮。' \
  | uv run scripts/save_recipe.py --title "測試甜湯" --slug "zz-test-soup" \
      --source "https://example.com/x" --by "tester" --kind "test"
cat state/cookbook/zz-test-soup.md
tail -2 state/inbox.md
```
Expected: prints `saved cookbook/zz-test-soup.md + queued craving`; the cookbook file shows the `# 測試甜湯` header, body, `**Source:**` line, and `## Verdicts`; inbox has a new `[craving]` line.

Then remove the test artifacts (do NOT commit them):
```bash
rm state/cookbook/zz-test-soup.md
git checkout state/inbox.md 2>/dev/null || true
```

- [ ] **Step 6: Commit**

```bash
git add scripts/save_recipe.py tests/test_save_recipe.py
git commit -m "feat(intake): save_recipe.py — write cookbook + queue craving (write-seam)"
```

---

## Task 2: `recipe_intake.py` — caption + frame extractor

**Files:**
- Create: `scripts/recipe_intake.py`
- Test: `tests/test_recipe_intake.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_recipe_intake.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import recipe_intake as ri

MILK_MOCHI_DESC = (
    "【年菜挑戰EP4 — 鮮奶麻糬甜湯】\n"
    "甜湯（減糖版）\n- 黑糖 30g\n- 水300g\n- 薑3-4片\n"
    "麻糬（減糖版）\n- 牛奶300g\n- 地瓜粉30g\n- 糖20g\n"
)


def test_extract_fields_full():
    info = {"title": "Milk Mochi", "uploader": "Selina",
            "duration": 32.8, "description": MILK_MOCHI_DESC}
    out = ri.extract_fields(info)
    assert out == {"title": "Milk Mochi", "uploader": "Selina",
                   "duration": 32.8, "description": MILK_MOCHI_DESC}


def test_extract_fields_falls_back_to_channel():
    info = {"title": "X", "channel": "Chef Bob", "duration": 0, "description": ""}
    assert ri.extract_fields(info)["uploader"] == "Chef Bob"


def test_is_thin_true_for_short_or_no_digits():
    assert ri.is_thin("") is True
    assert ri.is_thin("好吃！推薦給大家 yummy delicious enjoy") is True  # no digits


def test_is_thin_false_for_real_recipe():
    assert ri.is_thin(MILK_MOCHI_DESC) is False


def test_frame_timestamps_bounded_and_increasing():
    ts = ri.frame_timestamps(32.8, max_frames=8)
    assert len(ts) == 8
    assert ts == sorted(ts)
    assert all(0 < t < 32.8 for t in ts)


def test_frame_timestamps_short_clip():
    ts = ri.frame_timestamps(2.0, max_frames=10)
    assert len(ts) >= 1
    assert all(0 < t < 2.0 for t in ts)


def test_frame_timestamps_zero_duration():
    assert ri.frame_timestamps(0) == [0.0]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_recipe_intake.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'recipe_intake'`

- [ ] **Step 3: Write `scripts/recipe_intake.py`**

```python
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
    out = subprocess.run(
        [_bin("ffprobe", "FFPROBE_BIN"), "-v", "error", "-show_entries",
         "format=duration", "-of", "csv=p=0", str(mp4)],
        capture_output=True, timeout=30,
    )
    try:
        return float(out.stdout.decode().strip())
    except ValueError:
        return 0.0


def cmd_caption(url: str) -> dict:
    out = subprocess.run(
        [_bin("yt-dlp", "YT_DLP_BIN"), "-j", "--skip-download",
         "--no-warnings", "--no-playlist", url],
        capture_output=True, timeout=60,
    )
    if out.returncode != 0:
        return {"error": out.stderr.decode()[:300]}
    info = json.loads(out.stdout.decode())
    fields = extract_fields(info)
    fields["is_thin"] = is_thin(fields["description"])
    return fields


def cmd_frames(url: str) -> dict:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    vid = "".join(c for c in url if c.isalnum())[-16:] or "clip"
    workdir = FRAME_DIR / vid
    workdir.mkdir(exist_ok=True)
    mp4 = workdir / "clip.mp4"
    dl = subprocess.run(
        [_bin("yt-dlp", "YT_DLP_BIN"), "-f", "mp4/best", "--no-warnings",
         "--no-playlist", "--max-filesize", MAX_FILESIZE, "-o", str(mp4), url],
        capture_output=True, timeout=120,
    )
    if dl.returncode != 0 or not mp4.exists():
        return {"error": "download failed or file too large", "frames": []}
    frames = []
    for i, ts in enumerate(frame_timestamps(_probe_duration(mp4))):
        fp = workdir / f"frame_{i:02d}.jpg"
        subprocess.run(
            [_bin("ffmpeg", "FFMPEG_BIN"), "-hide_banner", "-loglevel", "error",
             "-ss", str(ts), "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
             "-y", str(fp)],
            capture_output=True, timeout=30,
        )
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_recipe_intake.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Smoke-test against the real reel (network — optional but recommended)**

Run:
```bash
uv run scripts/recipe_intake.py caption "https://www.instagram.com/reel/DUNy6_ADXyp/"
```
Expected: JSON with `"title"`, `"uploader": "Selina的簡單料理日常"` (or similar), the full `"description"` containing the ingredient list, and `"is_thin": false`.

(Skip if running offline; the path was already verified live during the spike on 2026-06-10.)

- [ ] **Step 6: Commit**

```bash
git add scripts/recipe_intake.py tests/test_recipe_intake.py
git commit -m "feat(intake): recipe_intake.py — yt-dlp caption + ffmpeg frame sampling"
```

---

## Task 3: Wire the new tools into chat mode

**Files:**
- Modify: `scripts/brain.py` (line 23, `CHAT_TOOLS`)
- Test: `tests/test_brain.py` (add one test)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_brain.py`:

```python
def test_chat_tools_include_recipe_intake_seams():
    # chat mode must be able to fetch sources and save recipes (recipe intake)
    assert "WebFetch" in brain.CHAT_TOOLS
    assert "scripts/recipe_intake.py" in brain.CHAT_TOOLS
    assert "scripts/save_recipe.py" in brain.CHAT_TOOLS
    # and must keep its existing capture seam
    assert "scripts/capture.py" in brain.CHAT_TOOLS
```

> If `tests/test_brain.py` does not already `import brain` with the `sys.path.insert(...scripts...)` shim, add the same three-line shim used by `tests/test_asianpantry.py` at the top of the file first.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_brain.py::test_chat_tools_include_recipe_intake_seams -v`
Expected: FAIL — assertion error (`WebFetch` not in `CHAT_TOOLS`)

- [ ] **Step 3: Update `CHAT_TOOLS` in `scripts/brain.py`**

Replace line 23:

```python
CHAT_TOOLS = "Read,Glob,Bash(uv run scripts/capture.py:*)"
```

with:

```python
CHAT_TOOLS = (
    "Read,Glob,WebFetch,"
    "Bash(uv run scripts/capture.py:*),"
    "Bash(uv run scripts/recipe_intake.py:*),"
    "Bash(uv run scripts/save_recipe.py:*)"
)
```

- [ ] **Step 4: Run the full brain test file to verify it passes**

Run: `uv run pytest tests/test_brain.py -v`
Expected: PASS (all existing tests + the new one)

- [ ] **Step 5: Commit**

```bash
git add scripts/brain.py tests/test_brain.py
git commit -m "feat(intake): grant chat mode WebFetch + recipe_intake/save_recipe tools"
```

---

## Task 4: Teach chat mode the recipe-intake behavior

**Files:**
- Modify: `prompts/chat.md`

This task has no unit test — it changes the brain's prompt. It is verified end-to-end in Task 5 (per the project's verify-via-real-use rule).

- [ ] **Step 1: Add the intake section to `prompts/chat.md`**

Insert the following block immediately **after** the bullet block ending with the
成品照/冰箱照 line (the `- 訊息含檔案路徑…` bullet, currently line 22) and **before** the
`## 規則` heading:

```markdown

## 料理擷取(收到影片連結 / 網頁 / 圖片 / 食譜文字 → 存進食譜)
當訊息帶來一份「可以做的料理」— 影片連結(Instagram / YouTube)、食譜網頁、食譜截圖/圖片/PDF、或貼上的食譜文字 — 就擷取下來、存進食譜、排進下週候選。判斷要靠常識:純閒聊的連結、隨手拍的生活照**不是**料理擷取,照平常聊天處理。

擷取的門路(由快到慢,夠了就停):
1. **影片連結** → 先 `uv run scripts/recipe_intake.py caption <url>`。回傳的 `description` 通常就是完整食譜(食材+步驟)。`is_thin` 為 false 代表夠用 → 直接用,不要下載。
2. **字幕太少時(is_thin 為 true 或沒有食材/步驟)** → 跑 `uv run scripts/recipe_intake.py frames <url>`,它會回傳幾張影格路徑;用 **Read** 一張張看 — 食譜常以畫面上的文字(食材表、步驟字卡)呈現,你自己「看」這支影片把食譜抓出來。
3. **食譜網頁** → 用 **WebFetch** 讀整頁內容。
4. **圖片 / 檔案**(訊息含「[attached file saved at: …]」)→ 用 **Read** 看。
5. **貼上的食譜文字** → 直接讀訊息內容。
6. 上面都抓不到 → 老實說這支沒抓到文字食譜,請他截一張步驟圖或跟你說菜名。

擷取到之後:
- 整理成**忠於原作**的繁體中文食譜卡:標題、份量、食材(含份量)、步驟、時間。非中文來源就翻成繁中。
- 先讀 `state/preferences.md`;若食譜牴觸偏好(例如有豬肉但他們不吃),**點出來問他要不要換**,不要自己偷偷改掉。
- 用 write-seam 存檔(這是你唯一能寫食譜的方式):把食譜卡「標題以下」的內容(份量那行、**Ingredients:**、**Steps:**)從 stdin 餵進去:
  `... | uv run scripts/save_recipe.py --title "<繁中標題>" --slug "<英文-kebab-slug>" --source "<原始連結或來源>" --by "<是誰丟的>" --kind "<IG reel|YouTube|webpage|image|text>"`
  `--slug` 一定要給一個英文小寫連字號的代稱(例如 milk-mochi-dessert-soup),因為中文標題無法當檔名。
- 存完後熱情回覆:貼出食譜卡,並加一句像「存好了,排進下週候選 ✅ 不要就跟我說一聲」。若腳本回「already in cookbook」,就說這道之前存過了。
- 這條鏈不要動本週已鎖定的菜單 — 一律走「下週候選」(儀式會處理)。
```

- [ ] **Step 2: Sanity-check the prompt renders**

Run:
```bash
uv run python -c "import sys; sys.path.insert(0,'scripts'); import brain; print('料理擷取' in brain.build_prompt('chat', [], []))"
```
Expected: prints `True` (the new section is present in the rendered chat prompt).

- [ ] **Step 3: Commit**

```bash
git add prompts/chat.md
git commit -m "feat(intake): teach chat mode the recipe-intake flow (caption→frames→save)"
```

---

## Task 5: End-to-end verification via real Discord use

**Files:** none (manual verification, mirrors the project's `selftest.py` + verify-via-real-use approach)

This task confirms the live daemon path works. Reinstall the daemon so it picks up the new `chat.md` and `brain.py`, then exercise each front-door in #小當家的廚房.

- [ ] **Step 1: Reinstall the daemon to load the new prompt + tools**

Run: `bash scripts/install_daemon.sh`
Expected: launchd job reloaded; `.runtime/` listener log shows `READY as …`.

- [ ] **Step 2: Verify the caption path (the original reel)**

In #小當家的廚房, post: `https://www.instagram.com/reel/DUNy6_ADXyp/`
Expected: 小當家 replies with a 繁中 recipe card (鮮奶麻糬甜湯, ingredients + steps) and a "存好了,排進下週候選 ✅" line. Confirm a new file under `state/cookbook/` and a new `[craving]` line in `state/inbox.md`.

- [ ] **Step 3: Verify the frames path (caption-less clip)**

Post a recipe Reel/Short whose recipe is shown as on-screen text but has a sparse caption.
Expected: 小當家 downloads + reads frames and still produces a recipe card. Confirm the cookbook file was written.

- [ ] **Step 4: Verify the webpage and image paths**

Post a recipe blog URL, then (separately) a recipe screenshot image.
Expected: both produce recipe cards via `WebFetch` and `Read` respectively, each saved to the cookbook.

- [ ] **Step 5: Verify the negative case**

Post a non-recipe link (e.g. a news article).
Expected: normal chat reply; **nothing** written to `state/cookbook/` or `state/inbox.md`.

- [ ] **Step 6: Verify the ritual picks up a queued craving**

Trigger the ritual (say 「排菜單」) and confirm the harvested inbox includes the intake craving as a candidate. (Or inspect that Step 1 of `plan-week` reads the craving line.)

- [ ] **Step 7: Commit any cookbook/state changes from real use**

```bash
git add state/
git commit -m "ritual: recipe-intake real-use verification — cookbook entries from reels"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Expand chat mode (not new mode) → Task 3. ✅
- `recipe_intake.py` caption + frames → Task 2. ✅
- `save_recipe.py` cookbook + inbox craving, dedupe by slug → Task 1. ✅
- Four front-doors (link/webpage/image/text) + fallback ladder → Task 4 prompt. ✅
- Caption-first, frames only if thin → `is_thin` (Task 2) + prompt step 1–2 (Task 4). ✅
- Preference-conflict flag, not auto-fix → Task 4 prompt. ✅
- Rides inbox→ritual, no live-plan mutation → Task 1 craving + Task 4 prompt rule + Task 5 step 6. ✅
- Scope boundaries (no auto-cart / Whisper / login) → none implemented; nothing in the plan adds them. ✅
- Edge cases (non-recipe, duplicate, long video size guard, walled reel) → Task 4 negative case + `MAX_FILESIZE`/dedupe in Tasks 1–2 + Task 5 step 5. ✅

**Placeholder scan:** No TBD/TODO; every code step contains complete code; every command has expected output. ✅

**Type/name consistency:** `slugify`, `cookbook_markdown`, `craving_note` (Task 1) and `extract_fields`, `is_thin`, `frame_timestamps`, `cmd_caption`, `cmd_frames` (Task 2) are referenced consistently in their tests and `main()`. `CHAT_TOOLS` substrings asserted in Task 3 match the strings written. ✅
