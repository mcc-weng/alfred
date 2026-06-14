# Timed Prep Reminders + Reproduce-with-Swaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver recipe-derived timed prep reminders to #小當家的廚房, and let chat regenerate a meal's lesson with swapped ingredients (then offer to save it).

**Architecture:** Feature 1 = "plan once, deliver cheaply": a launchd morning job (`prep.py plan`) has 小當家 reason out the day's prep timings into `.runtime/prep_schedule.json`; a launchd 15-min tick (`prep.py tick`, no LLM) posts due items idempotently. Reuses brain `nudge` mode + the `nudge.py` wrapper pattern. Feature 2 = a chat-mode prompt capability over the existing `save_recipe.py` seam (+ a `--variant` flag).

**Tech Stack:** Python (PEP 723 inline-deps scripts, stdlib only), pytest, launchd. Spec: `docs/superpowers/specs/2026-06-14-alfred-prep-reminders-and-swap-design.md`.

---

### Task 1: Config — add cook_time anchor

**Files:**
- Modify: `config.json:13`

- [ ] **Step 1: Add the cook_time key**

Find:
```
  "thresholds": {"woolies": 75, "asianpantry": 130},
  "woolies_fulfillment": "delivery-trial"
```
Replace with:
```
  "thresholds": {"woolies": 75, "asianpantry": 130},
  "woolies_fulfillment": "delivery-trial",
  "cook_time": "18:30"
```

- [ ] **Step 2: Verify** — `python -c "import json;print(json.load(open('config.json'))['cook_time'])"` → expected `18:30`

- [ ] **Step 3: Commit**
```bash
git add config.json
git commit -m "feat(prep): add cook_time anchor (18:30) to config"
```

---

### Task 2: prep.py pure helpers (TDD)

**Files:**
- Create: `scripts/prep.py`
- Test: `tests/test_prep.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_prep.py
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import prep


def test_item_id_stable_and_distinct():
    assert prep.item_id("醃雞") == prep.item_id("醃雞")
    assert prep.item_id("醃雞") != prep.item_id("回溫")


def test_clock_to_due():
    assert prep.clock_to_due("2026-06-15", "17:50") == "2026-06-15T17:50:00"


def test_build_schedule():
    sched = prep.build_schedule(
        "2026-06-15", "18:30",
        [{"time": "09:00", "msg": "醃雞"}, {"time": "17:50", "msg": "回溫"}])
    assert sched["date"] == "2026-06-15"
    assert sched["cook_time"] == "18:30"
    assert len(sched["items"]) == 2
    assert sched["items"][0]["due"] == "2026-06-15T09:00:00"
    assert sched["items"][0]["sent"] is False
    assert sched["items"][0]["id"] == prep.item_id("醃雞")


def test_parse_plan_output_nothing():
    assert prep.parse_plan_output("NOTHING") == []
    assert prep.parse_plan_output("  nothing.\n") == []
    assert prep.parse_plan_output("") == []


def test_parse_plan_output_json():
    assert prep.parse_plan_output('[{"time":"09:00","msg":"醃雞"}]') == \
        [{"time": "09:00", "msg": "醃雞"}]


def test_parse_plan_output_fenced():
    out = '```json\n[{"time":"09:00","msg":"醃雞"}]\n```'
    assert prep.parse_plan_output(out) == [{"time": "09:00", "msg": "醃雞"}]


def test_due_items_grace_window():
    sched = prep.build_schedule("2026-06-15", "18:30",
                                [{"time": "17:50", "msg": "回溫"}])
    early = datetime.datetime(2026, 6, 15, 17, 30)   # 20m before → outside 15m grace
    within = datetime.datetime(2026, 6, 15, 17, 40)  # 10m before → inside grace
    assert prep.due_items(sched, early, 15) == []
    assert len(prep.due_items(sched, within, 15)) == 1


def test_due_items_skips_sent():
    sched = prep.build_schedule("2026-06-15", "18:30",
                                [{"time": "09:00", "msg": "醃雞"}])
    sched["items"][0]["sent"] = True
    now = datetime.datetime(2026, 6, 15, 9, 0)
    assert prep.due_items(sched, now, 15) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_prep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'prep'`

- [ ] **Step 3: Write the minimal implementation**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Recipe-derived timed prep reminders.

Usage:
  uv run scripts/prep.py plan   # LLM: write today's prep schedule (idempotent/day)
  uv run scripts/prep.py tick   # no LLM: post any reminder now due (idempotent)
"""
import datetime
import hashlib
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain  # noqa: E402

UV = "/opt/homebrew/bin/uv"
GRACE_MIN = 15
SCHED = ROOT / ".runtime" / "prep_schedule.json"


def _config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def item_id(msg: str) -> str:
    return hashlib.sha1(msg.encode("utf-8")).hexdigest()[:8]


def clock_to_due(date: str, hhmm: str) -> str:
    return f"{date}T{hhmm}:00"


def build_schedule(date: str, cook_time: str, items: list[dict]) -> dict:
    return {
        "date": date,
        "cook_time": cook_time,
        "items": [
            {"id": item_id(it["msg"]), "due": clock_to_due(date, it["time"]),
             "msg": it["msg"], "sent": False}
            for it in items
        ],
    }


def parse_plan_output(text: str) -> list[dict]:
    t = text.strip()
    if not t or t.upper().rstrip(".") == "NOTHING":
        return []
    m = re.search(r"\[.*\]", t, re.DOTALL)
    return json.loads(m.group(0)) if m else []


def due_items(schedule: dict, now: datetime.datetime, grace_min: int) -> list[dict]:
    grace = datetime.timedelta(minutes=grace_min)
    out = []
    for it in schedule["items"]:
        due = datetime.datetime.fromisoformat(it["due"])
        if not it["sent"] and now >= due - grace:
            out.append(it)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_prep.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**
```bash
git add scripts/prep.py tests/test_prep.py
git commit -m "feat(prep): pure schedule helpers (id/due/build/parse/due_items) + tests"
```

---

### Task 3: prep.py `plan` orchestration + planner prompt

**Files:**
- Modify: `scripts/prep.py` (append `plan()` + `main()`)
- Create: `prompts/prep.md`

- [ ] **Step 1: Create the planner prompt**

```markdown
你是「小當家」🔥。今天是 {today}({weekday}),晚餐預設開火時間 {cook_time}。

**你的任務:規劃「今天到今晚」的備料提醒時間表。** 你的輸出會被系統解析成定時提醒,
逐則在對的時間點傳到 #小當家的廚房。不要發訊息、不要解釋、不要寒暄。

步驟:
1. 用 Glob/Read 看 `state/plans/` 最新的計畫,找出**今天**({weekday})和**明天**排的晚餐。
   最新計畫檔距今超過 8 天 → 直接只輸出一個英文字:NOTHING。
2. 用 Read 打開對應的 `state/cookbook/` 食譜,推敲需要**提前**做的備料,只挑真正需要
   抓時間的(沒有就略過):
   - 早上要先做的(例:今晚要炸的肉早上先醃更入味)→ 時間用 09:00。
   - 開火前一段時間要做的(例:牛排下鍋前回溫40分)→ 時間 = {cook_time} 減去該分鐘數。
   - **明天**的菜若需要前一晚處理(冷凍肉退冰、長時間醃漬)→ 今晚的時間(例 21:00);
     冰箱狀態未知,用條件語氣(「明天的肉若還冰著,今晚移到冷藏退冰」)。
3. 簡單、免提前備料的菜(拌飯、煮麵)→ 不要硬湊提醒。整天都沒有 → 只輸出:NOTHING。

輸出格式:**只輸出**一個 JSON 陣列(或單字 NOTHING),不要任何其他文字:
[{"time":"HH:MM","msg":"一句小當家口吻的繁中提醒,可加 ⏰ 開頭"}, ...]
時間用 24 小時制 HH:MM。msg 簡短、有畫面、講為什麼。
```

- [ ] **Step 2: Append `plan()` and `main()` to `scripts/prep.py`**

```python
def plan(force: bool = False) -> None:
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if not force and SCHED.exists():
        try:
            if json.loads(SCHED.read_text()).get("date") == today:
                print("prep: schedule already exists for today")
                return
        except (json.JSONDecodeError, OSError):
            pass  # corrupt/unreadable → regenerate
    cook_time = _config().get("cook_time", "18:30")
    weekday = datetime.datetime.now().strftime("%A")
    prompt = (ROOT / "prompts" / "prep.md").read_text() \
        .replace("{today}", today).replace("{weekday}", weekday) \
        .replace("{cook_time}", cook_time)
    out = brain.run_brain("nudge", [], [], prompt_override=prompt)
    items = parse_plan_output(out)
    sched = build_schedule(today, cook_time, items)
    SCHED.parent.mkdir(parents=True, exist_ok=True)
    SCHED.write_text(json.dumps(sched, ensure_ascii=False, indent=2))
    print(f"prep: planned {len(items)} item(s) for {today}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "plan":
        plan(force="--force" in sys.argv)
    elif cmd == "tick":
        tick()
    else:
        sys.exit("usage: prep.py plan|tick")


if __name__ == "__main__":
    main()
```
(Note: `tick` is added in Task 4; `main()` references it — Task 4 lands before any real run.)

- [ ] **Step 3: Verify idempotency unit-style** — add to `tests/test_prep.py`:
```python
def test_plan_idempotent_by_date(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sched_file.write_text(json.dumps({"date": today, "cook_time": "18:30", "items": []}))
    monkeypatch.setattr(prep, "SCHED", sched_file)
    called = []
    monkeypatch.setattr(prep.brain, "run_brain", lambda *a, **k: called.append(1) or "NOTHING")
    prep.plan()
    assert called == []  # existing today schedule → brain NOT called
```
Run: `uv run pytest tests/test_prep.py -v` → Expected: PASS (9 tests)

- [ ] **Step 4: Real smoke test** — `uv run scripts/prep.py plan --force` then inspect `.runtime/prep_schedule.json`. Against the current plan, expect a steak-day `回溫` item near 17:50 and/or a morning 醃 item; a no-prep day → `{"items": []}`. (This calls the live brain; takes ~30–60s.)

- [ ] **Step 5: Commit**
```bash
git add scripts/prep.py tests/test_prep.py prompts/prep.md
git commit -m "feat(prep): plan subcommand (idempotent-by-date) + planner prompt"
```

---

### Task 4: prep.py `tick` delivery

**Files:**
- Modify: `scripts/prep.py` (add `tick()` before `main()`)

- [ ] **Step 1: Write the failing test** — add to `tests/test_prep.py`:
```python
def test_tick_posts_due_then_marks_sent(monkeypatch, tmp_path):
    sched_file = tmp_path / "prep_schedule.json"
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    sched = {"date": today, "cook_time": "18:30",
             "items": [{"id": "a1", "due": f"{today}T00:00:00", "msg": "醃雞", "sent": False}]}
    sched_file.write_text(json.dumps(sched))
    monkeypatch.setattr(prep, "SCHED", sched_file)
    posts = []
    monkeypatch.setattr(prep.subprocess, "run", lambda *a, **k: posts.append(a))
    prep.tick()
    assert len(posts) == 1                       # posted once
    after = json.loads(sched_file.read_text())
    assert after["items"][0]["sent"] is True     # marked sent
    posts.clear()
    prep.tick()
    assert posts == []                           # second run: no double-post
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_prep.py::test_tick_posts_due_then_marks_sent -v`
Expected: FAIL — `AttributeError: module 'prep' has no attribute 'tick'`

- [ ] **Step 3: Implement `tick()`** (insert above `main()`):
```python
def tick() -> None:
    if not SCHED.exists():
        return
    try:
        sched = json.loads(SCHED.read_text())
    except (json.JSONDecodeError, OSError):
        return
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    if sched.get("date") != today:
        return  # stale (pre-plan window / post-midnight) → silent
    due = due_items(sched, datetime.datetime.now(), GRACE_MIN)
    if not due:
        return
    msg = "\n".join(it["msg"] for it in due)
    subprocess.run(
        [UV, "run", str(ROOT / "scripts" / "discord_io.py"),
         "post", "--channel", "alfred", "--content", msg],
        cwd=ROOT, check=True)
    ids = {it["id"] for it in due}
    for it in sched["items"]:
        if it["id"] in ids:
            it["sent"] = True
    SCHED.write_text(json.dumps(sched, ensure_ascii=False, indent=2))
    print(f"prep: posted {len(due)} reminder(s)")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_prep.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**
```bash
git add scripts/prep.py tests/test_prep.py
git commit -m "feat(prep): tick delivery — posts due reminders once, marks sent"
```

---

### Task 5: launchd jobs

**Files:**
- Create: `launchd/com.alfred.prep-plan.plist`
- Create: `launchd/com.alfred.prep-tick.plist`

(No `install_daemon.sh` edit needed — it globs `launchd/*.plist`.)

- [ ] **Step 1: Create the plan job** (`launchd/com.alfred.prep-plan.plist`):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alfred.prep-plan</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>/Users/mikeweng/Projects/alfred/scripts/prep.py</string>
    <string>plan</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/mikeweng/Projects/alfred</string>
  <key>StandardOutPath</key><string>/Users/mikeweng/Projects/alfred/.runtime/prep-plan.log</string>
  <key>StandardErrorPath</key><string>/Users/mikeweng/Projects/alfred/.runtime/prep-plan.err</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>
</dict>
</plist>
```

- [ ] **Step 2: Create the tick job** (`launchd/com.alfred.prep-tick.plist`):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alfred.prep-tick</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>/Users/mikeweng/Projects/alfred/scripts/prep.py</string>
    <string>tick</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/mikeweng/Projects/alfred</string>
  <key>StandardOutPath</key><string>/Users/mikeweng/Projects/alfred/.runtime/prep-tick.log</string>
  <key>StandardErrorPath</key><string>/Users/mikeweng/Projects/alfred/.runtime/prep-tick.err</string>
  <key>StartInterval</key><integer>900</integer>
</dict>
</plist>
```

- [ ] **Step 3: Install & verify**
```bash
bash scripts/install_daemon.sh
launchctl list | grep prep
```
Expected: both `com.alfred.prep-plan` and `com.alfred.prep-tick` listed.

- [ ] **Step 4: Commit**
```bash
git add launchd/com.alfred.prep-plan.plist launchd/com.alfred.prep-tick.plist
git commit -m "feat(prep): launchd jobs — daily plan (08:00) + 15-min tick"
```

---

### Task 6: De-overlap the morning lesson nudge

**Files:**
- Modify: `prompts/nudge-morning.md:13-14`

- [ ] **Step 1: Trim the prep preamble** (the timed prep system now owns prep)

Find:
```
   - 第一行熱血預告:「今天的對決是——{菜名}!」+ 任何**現在就要做**的準備
     (退冰今晚的蛋白質、為明天先醃肉等)。
```
Replace with:
```
   - 第一行熱血預告:「今天的對決是——{菜名}!」(備料的定時提醒由系統另外發,
     這裡不必再列提前準備)。
```

- [ ] **Step 2: Verify** — Read `prompts/nudge-morning.md`; confirm the prep clause is gone and the lesson body instructions remain intact.

- [ ] **Step 3: Commit**
```bash
git add prompts/nudge-morning.md
git commit -m "feat(prep): morning nudge drops prep preamble (timed system owns it)"
```

---

### Task 7: save_recipe.py `--variant` flag (TDD)

**Files:**
- Modify: `scripts/save_recipe.py`
- Test: `tests/test_save_recipe.py` (append)

- [ ] **Step 1: Write failing tests** — append to `tests/test_save_recipe.py`:
```python
import io


def test_variant_skips_craving(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(save_recipe.capture, "append_note", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(save_recipe, "COOKBOOK", tmp_path)
    monkeypatch.setattr(sys, "argv",
        ["save_recipe.py", "--title", "T", "--slug", "t-variant",
         "--source", "s", "--variant"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("body"))
    save_recipe.main()
    assert calls == []                       # variant → NO craving queued
    assert (tmp_path / "t-variant.md").exists()


def test_nonvariant_queues_craving(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(save_recipe.capture, "append_note", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(save_recipe, "COOKBOOK", tmp_path)
    monkeypatch.setattr(sys, "argv",
        ["save_recipe.py", "--title", "T", "--slug", "t-normal", "--source", "s"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("body"))
    save_recipe.main()
    assert len(calls) == 1                    # normal → craving queued
```
(If `tests/test_save_recipe.py` lacks the `import save_recipe` / `sys` path-insert preamble the other tests use, mirror it from the top of the file.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_save_recipe.py -k variant -v`
Expected: FAIL — `--variant` is an unrecognized argument (SystemExit).

- [ ] **Step 3: Implement the flag** in `scripts/save_recipe.py` `main()`:

Find:
```python
    p.add_argument("--kind", default="link")
    args = p.parse_args()
```
Replace with:
```python
    p.add_argument("--kind", default="link")
    p.add_argument("--variant", action="store_true",
                   help="swapped-ingredient variant — skip queuing a craving")
    args = p.parse_args()
```

Find:
```python
    capture.append_note(INBOX, date, "craving",
                        craving_note(args.title, slug, args.by, args.kind))
    print(f"saved cookbook/{slug}.md + queued craving")
```
Replace with:
```python
    if not args.variant:
        capture.append_note(INBOX, date, "craving",
                            craving_note(args.title, slug, args.by, args.kind))
        print(f"saved cookbook/{slug}.md + queued craving")
    else:
        print(f"saved cookbook/{slug}.md (variant — no craving)")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_save_recipe.py -v`
Expected: PASS (existing tests + 2 new)

- [ ] **Step 5: Commit**
```bash
git add scripts/save_recipe.py tests/test_save_recipe.py
git commit -m "feat(swap): save_recipe --variant flag skips craving queue"
```

---

### Task 8: chat.md — reproduce-with-swaps flow

**Files:**
- Modify: `prompts/chat.md` (add a capability bullet under "你現在能做的")

- [ ] **Step 1: Add the reproduce-with-swaps bullet** — after the 料理求救 bullet (the `state/lessons.md` line ~21), insert:
```
- **換食材重做食譜**:對方說某道菜的食材沒了/要換(例:「青醬雞腿麵的雞腿沒了,改用雞胸,重新給我食譜」)→ 找出那道菜(沒指定就用**今天**的晚餐:讀 `state/plans/` 最新檔+對應 `state/cookbook/` 食譜),把整份食譜**重新生成**:依替代食材調整時間/火候/份量,**標出改了什麼、為什麼**,維持 2 人份,並更新 `🔢 每份` 估算。貼出來後**問一句**「要把這個版本存成食譜嗎?」。
  - 要存 → 用 write-seam 存成**變化版**(heredoc、`uv run` 開頭、`--variant`):slug **必須是英文**(中文後綴會被 slugify 砍掉而撞回原檔名、存不進去),例 `--slug pesto-chicken-pasta-chicken-breast`、`--source "variant of pesto-chicken-pasta"`、`--kind 變化版`。`--variant` 會跳過 craving 佇列。
  - 不要存 → 就這樣,不寫任何東西(ephemeral)。本週鎖定的菜單不要動。
```

- [ ] **Step 2: Verify** — Read `prompts/chat.md`; confirm the bullet references the ASCII-slug requirement, `--variant`, and heredoc form, consistent with the existing recipe-intake save instructions.

- [ ] **Step 3: Commit**
```bash
git add prompts/chat.md
git commit -m "feat(swap): chat reproduce-with-swaps → regenerate, ask, save as variant"
```

---

### Task 9: Test checklist + integration verification

**Files:**
- Modify: `TEST-CHECKLIST.md`

- [ ] **Step 1: Append scenarios**
```
## Prep reminders + reproduce-with-swaps
- [ ] PR1 plan: `prep.py plan --force` on a steak day → schedule has a ~17:50 回溫 item
- [ ] PR2 plan: 醃-in-morning dish → 09:00 item; no-prep day → empty items
- [ ] PR3 plan idempotent: second `plan` (no --force) same day → "already exists", brain not called
- [ ] PR4 tick: a due item posts to #小當家的廚房 once; second tick → no double-post
- [ ] PR5 tick stale: schedule date != today → silent no-op
- [ ] PR6 launchd: prep-plan + prep-tick loaded; reminders arrive on a real cook day
- [ ] SW1 swap: chat regenerates a named dish with a swap, flags changes, updates 每份
- [ ] SW2 swap save=yes → ASCII-slug variant written, no craving queued
- [ ] SW3 swap save=no → nothing written; locked week untouched
```

- [ ] **Step 2: Commit**
```bash
git add TEST-CHECKLIST.md
git commit -m "docs: prep + swap test scenarios (PR1-6, SW1-3)"
```

- [ ] **Step 3: Integration verification (real use)** — kick the daemon after prompt edits (`launchctl kickstart -k gui/$(id -u)/com.alfred.listener` is not needed for prompts — `build_prompt` re-reads — but restart isn't harmful). Confirm PR1–PR6 over a real cook day and SW1–SW3 in real chat. Tick items as they pass.

---

## Notes for the executor
- `prep.py` reuses brain `nudge` mode (read-only Read/Glob) via `prompt_override` — no `brain.py` change.
- `.runtime/prep_schedule.json` is already gitignored — never commit it.
- The tick's 15-min `StartInterval` + 15-min grace means a reminder fires at most ~15 min early, never late.
- Tasks 7–8 (swaps) are independent of 1–6 (reminders); either half can ship alone.
