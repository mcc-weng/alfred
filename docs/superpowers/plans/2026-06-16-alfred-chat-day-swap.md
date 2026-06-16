# Chat-Driven Day Swap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let 小當家 swap two days' meals in the current week's plan from chat, persisting the change so the morning nudge follows the new order.

**Architecture:** A new growable plan-operations CLI `scripts/plan.py` ships one subcommand, `swap`. The chat LLM does natural-language understanding (which two days); `plan.py` owns integrity (deterministic edit + validation + self-commit). Chat gets one allowlist line — no new mode, no routing change. Full rationale: `docs/superpowers/specs/2026-06-16-alfred-chat-day-swap-design.md`.

**Tech Stack:** Python 3.11 (uv inline-script header, no external deps), pytest, git via subprocess.

---

## File Structure

- **Create** `scripts/plan.py` — plan-operations CLI. Pure helpers (`swap_text`, `_resolve`, `_cells`, `latest_plan_path`, `plan_date`) + orchestration (`swap`) + `main()`.
- **Create** `tests/test_plan.py` — unit tests for the pure helpers and orchestration.
- **Modify** `scripts/brain.py:23-28` — add one line to `CHAT_TOOLS`.
- **Modify** `prompts/chat.md` — add the day-swap behavior section.
- **Modify** `CLAUDE.md` — document the swap capability under Commands.

The plan file format being edited (unchanged by this work):

```
| 天 | 料理 | 模式 | 時間 | 每份營養* |
|---|---|---|---|---|
| 週二 Tue | 三杯雞 + 白飯 | play | 35分 | ~50P / 810kcal |
| 週三 Wed | 牛排 | play | 30分 | ~46P / 540kcal |
...
## Reasoning
- 週二: play — 三杯雞，本週絕學：收汁與醬感判斷
- 週三: play — 牛排，上週 banger 技巧重現
```

`swap` keeps each day label (`週二 Tue`) fixed and exchanges the content cells (dish/模式/時間/營養) plus the matching `- 週X:` reasoning bullets.

All test commands run from the repo root: `cd /Users/mikeweng/Projects/alfred`.

---

### Task 1: `swap_text` — table-row swap (pure core)

**Files:**
- Create: `scripts/plan.py`
- Test: `tests/test_plan.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_plan.py`:

```python
import datetime
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import plan

PLAN = """# 週菜單 Jun 15–21, 2026

| 天 | 料理 | 模式 | 時間 | 每份營養* |
|---|---|---|---|---|
| 週一 Mon | 蔥香雞腿 + 番茄炒蛋 | fast | 35分 | ~42P / 640kcal |
| 週二 Tue | 三杯雞 + 白飯 | play | 35分 | ~50P / 810kcal |
| 週三 Wed | 牛排 | play | 30分 | ~46P / 540kcal |
| 週日 Sun | 外食 | — | — | — |

## Reasoning
- 週一: fast 開週，清爽暖場
- 週二: play — 三杯雞，本週絕學：收汁與醬感判斷
- 週三: play — 牛排，上週 banger 技巧重現
"""


def test_swap_table_rows_exchanges_content_keeps_labels():
    out = plan.swap_text(PLAN, "週二", "週三")
    lines = out.split("\n")
    tue = next(l for l in lines if l.startswith("| 週二 Tue"))
    wed = next(l for l in lines if l.startswith("| 週三 Wed"))
    # day labels stay put; content swapped
    assert "牛排" in tue and "30分" in tue and "~46P / 540kcal" in tue
    assert "三杯雞" in wed and "35分" in wed and "~50P / 810kcal" in wed


def test_swap_leaves_other_days_untouched():
    out = plan.swap_text(PLAN, "週二", "週三")
    lines = out.split("\n")
    assert "| 週一 Mon | 蔥香雞腿 + 番茄炒蛋 | fast | 35分 | ~42P / 640kcal |" in lines
    assert "| 週日 Sun | 外食 | — | — | — |" in lines
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plan'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/plan.py`:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Alfred plan operations. Usage: uv run scripts/plan.py swap <dayA> <dayB>

The chat LLM resolves natural language to two day selectors; this script owns
plan-file integrity (deterministic edit + validation + self-commit). See
docs/superpowers/specs/2026-06-16-alfred-chat-day-swap-design.md.
"""
import datetime
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLANS = ROOT / "state" / "plans"

_DAY_ALIASES = {
    "monday": "週一", "mon": "週一", "tuesday": "週二", "tue": "週二",
    "wednesday": "週三", "wed": "週三", "thursday": "週四", "thu": "週四",
    "friday": "週五", "fri": "週五", "saturday": "週六", "sat": "週六",
    "sunday": "週日", "sun": "週日",
}


def _cells(line: str) -> list[str]:
    """Stripped cells of a markdown table row (drops the empty edges)."""
    return [c.strip() for c in line.split("|")[1:-1]]


def _haystack(day_label: str, dish: str) -> str:
    """Lowercased searchable text for a row: day label + dish + EN aliases."""
    hay = f"{day_label} {dish}".lower()
    for alias, cn in _DAY_ALIASES.items():
        if cn in day_label:
            hay += " " + alias
    return hay


def _resolve(rows: list[tuple[str, list[str]]], selector: str) -> int:
    """Index of the single row matching selector (weekday or dish substring)."""
    s = selector.strip().lower()
    hits = [i for i, (label, cells) in enumerate(rows)
            if s and s in _haystack(label, cells[0])]
    if not hits:
        raise ValueError(f"找不到符合「{selector}」的那一天")
    if len(hits) > 1:
        raise ValueError(f"「{selector}」對到不只一天，請說清楚是哪一天")
    return hits[0]


def swap_text(text: str, sel_a: str, sel_b: str) -> str:
    """Return plan text with the two selected days' content swapped."""
    lines = text.split("\n")
    day_line_idx = [i for i, ln in enumerate(lines) if re.match(r"^\|\s*週", ln)]
    rows = [(_cells(lines[i])[0], _cells(lines[i])[1:]) for i in day_line_idx]

    ia, ib = _resolve(rows, sel_a), _resolve(rows, sel_b)
    if ia == ib:
        raise ValueError("兩個都指到同一天，沒得換")

    label_a, content_a = rows[ia]
    label_b, content_b = rows[ib]
    lines[day_line_idx[ia]] = "| " + " | ".join([label_a] + content_b) + " |"
    lines[day_line_idx[ib]] = "| " + " | ".join([label_b] + content_a) + " |"
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mikeweng/Projects/alfred
git add scripts/plan.py tests/test_plan.py
git commit -m "feat(plan): plan.py swap_text — table-row content swap (pure)"
```

---

### Task 2: `swap_text` — reasoning bullets + round-trip

**Files:**
- Modify: `scripts/plan.py` (extend `swap_text`)
- Test: `tests/test_plan.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan.py`:

```python
def test_swap_exchanges_reasoning_bullets():
    out = plan.swap_text(PLAN, "週二", "週三")
    lines = out.split("\n")
    r_tue = next(l for l in lines if l.startswith("- 週二:"))
    r_wed = next(l for l in lines if l.startswith("- 週三:"))
    assert "牛排" in r_tue and "banger" in r_tue
    assert "三杯雞" in r_wed and "收汁" in r_wed


def test_swap_then_swap_back_is_identity():
    once = plan.swap_text(PLAN, "週二", "週三")
    twice = plan.swap_text(once, "週二", "週三")
    assert twice == PLAN
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: FAIL — `test_swap_exchanges_reasoning_bullets` (reasoning unchanged); `test_swap_then_swap_back_is_identity` may pass already but will pass after this task too.

- [ ] **Step 3: Write minimal implementation**

Add two helpers to `scripts/plan.py` (above `swap_text`):

```python
def _reasoning_idx(lines: list[str], weekday: str) -> int | None:
    """Index of the `- 週X:` reasoning bullet for weekday, or None."""
    for i, ln in enumerate(lines):
        if re.match(rf"^- {weekday}\s*[:：]", ln):
            return i
    return None


def _reasoning_text(line: str) -> str:
    return re.split(r"[:：]", line, 1)[1].strip()
```

Then extend `swap_text`, inserting before `return "\n".join(lines)`:

```python
    wd_a = re.search(r"週.", label_a).group()
    wd_b = re.search(r"週.", label_b).group()
    ra, rb = _reasoning_idx(lines, wd_a), _reasoning_idx(lines, wd_b)
    if ra is not None and rb is not None:
        text_a, text_b = _reasoning_text(lines[ra]), _reasoning_text(lines[rb])
        lines[ra] = f"- {wd_a}: {text_b}"
        lines[rb] = f"- {wd_b}: {text_a}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mikeweng/Projects/alfred
git add scripts/plan.py tests/test_plan.py
git commit -m "feat(plan): swap reasoning bullets; round-trip is identity"
```

---

### Task 3: Selector resolution edge cases

**Files:**
- Test: `tests/test_plan.py` (no implementation change expected — proves `_resolve` contract)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan.py`:

```python
def test_selector_by_dish_substring():
    out = plan.swap_text(PLAN, "牛排", "三杯雞")
    tue = next(l for l in out.split("\n") if l.startswith("| 週二 Tue"))
    assert "牛排" in tue


def test_selector_english_full_name():
    out = plan.swap_text(PLAN, "Tuesday", "Wednesday")
    wed = next(l for l in out.split("\n") if l.startswith("| 週三 Wed"))
    assert "三杯雞" in wed


def test_selector_unknown_raises():
    with pytest.raises(ValueError, match="找不到"):
        plan.swap_text(PLAN, "週六", "週二")


def test_selector_ambiguous_raises():
    # "play" appears in multiple rows' content
    with pytest.raises(ValueError, match="不只一天"):
        plan.swap_text(PLAN, "play", "週二")


def test_selector_same_row_raises():
    with pytest.raises(ValueError, match="同一天"):
        plan.swap_text(PLAN, "週二", "三杯雞")
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: PASS for most; if `test_selector_ambiguous_raises` fails because "play" is matched in the day-label haystack only, note that `_haystack` includes the dish cell so "play" (the 模式 cell) is **not** in the haystack — adjust the test's ambiguous token to one that genuinely appears in 2+ rows' day-label-or-dish, e.g. use `"雞"` (appears in 週一 蔥香雞腿 and 週二 三杯雞). Replace `"play"` with `"雞"` and re-run.

- [ ] **Step 3: Implementation**

No code change expected — `_resolve` already raises on unknown/ambiguous and `swap_text` raises on same-row. If a test reveals a gap, fix `_resolve`/`swap_text` minimally.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mikeweng/Projects/alfred
git add tests/test_plan.py
git commit -m "test(plan): selector resolution — dish/EN/unknown/ambiguous/same-row"
```

---

### Task 4: File location, freshness guard, `swap()` orchestration

**Files:**
- Modify: `scripts/plan.py` (add `latest_plan_path`, `plan_date`, `swap`)
- Test: `tests/test_plan.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan.py`:

```python
def _write_plan(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return p


def test_latest_plan_path_picks_newest(tmp_path):
    _write_plan(tmp_path, "2026-06-07.md", "old")
    _write_plan(tmp_path, "2026-06-15.md", "new")
    assert plan.latest_plan_path(tmp_path).name == "2026-06-15.md"


def test_plan_date_parses_filename(tmp_path):
    p = _write_plan(tmp_path, "2026-06-15.md", "x")
    assert plan.plan_date(p) == datetime.date(2026, 6, 15)


def test_swap_writes_swapped_content_no_commit(tmp_path):
    _write_plan(tmp_path, "2026-06-15.md", PLAN)
    plan.swap("週二", "週三", plans_dir=tmp_path,
              today=datetime.date(2026, 6, 16), do_commit=False)
    out = (tmp_path / "2026-06-15.md").read_text()
    tue = next(l for l in out.split("\n") if l.startswith("| 週二 Tue"))
    assert "牛排" in tue


def test_swap_refuses_stale_plan(tmp_path):
    _write_plan(tmp_path, "2026-06-01.md", PLAN)
    with pytest.raises(SystemExit):
        plan.swap("週二", "週三", plans_dir=tmp_path,
                  today=datetime.date(2026, 6, 30), do_commit=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: FAIL — `AttributeError: module 'plan' has no attribute 'latest_plan_path'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/plan.py`:

```python
_PLAN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def latest_plan_path(plans_dir: pathlib.Path = PLANS) -> pathlib.Path | None:
    dated = [p for p in plans_dir.glob("*.md") if _PLAN_NAME.match(p.name)]
    return max(dated, default=None, key=lambda p: p.name)


def plan_date(path: pathlib.Path) -> datetime.date:
    return datetime.date.fromisoformat(path.stem)


def _die(msg: str) -> None:
    print(msg)
    raise SystemExit(1)


def swap(sel_a: str, sel_b: str, *, plans_dir: pathlib.Path = PLANS,
         today: datetime.date | None = None, do_commit: bool = True) -> None:
    today = today or datetime.date.today()
    path = latest_plan_path(plans_dir)
    if path is None:
        _die("state/plans/ 裡沒有任何計畫檔")
    pdate = plan_date(path)
    if (today - pdate).days > 8:
        _die(f"最新計畫({pdate})距今超過 8 天，不動舊計畫")
    text = path.read_text()
    try:
        new = swap_text(text, sel_a, sel_b)
    except ValueError as e:
        _die(str(e))
    if new == text:
        _die("換完跟原本一樣，沒有變動")
    path.write_text(new)
    if do_commit:
        _commit(path, sel_a, sel_b, pdate)
    print(f"已對調：{sel_a} ↔ {sel_b}（week of {pdate}）")
```

(Note: `_commit` is defined in Task 5; for this task's `do_commit=False` tests it is never called.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/mikeweng/Projects/alfred
git add scripts/plan.py tests/test_plan.py
git commit -m "feat(plan): latest-plan lookup, freshness guard, swap() orchestration"
```

---

### Task 5: `_commit` + `main()` CLI, end-to-end

**Files:**
- Modify: `scripts/plan.py` (add `_commit`, `main`, `__main__` guard)
- Test: `tests/test_plan.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_plan.py`:

```python
def test_main_requires_three_args(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["plan.py", "swap", "週二"])
    with pytest.raises(SystemExit):
        plan.main()


def test_main_unknown_command(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["plan.py", "frobnicate"])
    with pytest.raises(SystemExit):
        plan.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: FAIL — `AttributeError: module 'plan' has no attribute 'main'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/plan.py`:

```python
def _commit(path: pathlib.Path, sel_a: str, sel_b: str,
            pdate: datetime.date) -> None:
    msg = f"plan: swap {sel_a}↔{sel_b} (week of {pdate})"
    subprocess.run(["git", "-C", str(ROOT), "add", str(path)], check=True)
    subprocess.run(["git", "-C", str(ROOT), "commit", "-m", msg], check=True)


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 1 and args[0] == "swap":
        if len(args) != 3:
            _die("用法：plan.py swap <dayA> <dayB>")
        swap(args[1], args[2])
        return
    _die(f"未知指令：{args[0] if args else '(空)'}；目前只支援 swap")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes, then a real end-to-end swap**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_plan.py -v`
Expected: PASS (15 tests).

Real end-to-end against the live plan (this commits — verify then it's a real swap):
```bash
cd /Users/mikeweng/Projects/alfred
uv run scripts/plan.py swap 週二 週三
git log --oneline -1   # expect: plan: swap 週二↔週三 (week of 2026-06-15)
uv run scripts/plan.py swap 週二 週三   # swap back to restore order
```
Expected: first command prints `已對調：週二 ↔ 週三 …` and creates a commit; the swap-back returns the plan to its original order with a second commit.

- [ ] **Step 5: Commit**

```bash
cd /Users/mikeweng/Projects/alfred
git add scripts/plan.py tests/test_plan.py
git commit -m "feat(plan): _commit + main() CLI dispatch for swap"
```

---

### Task 6: Wire chat — allowlist, prompt, docs

**Files:**
- Modify: `scripts/brain.py:23-28`
- Modify: `prompts/chat.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the allowlist line**

In `scripts/brain.py`, change `CHAT_TOOLS` to include `plan.py`:

```python
CHAT_TOOLS = (
    "Read,Glob,WebFetch,"
    "Bash(uv run scripts/capture.py:*),"
    "Bash(uv run scripts/recipe_intake.py:*),"
    "Bash(uv run scripts/save_recipe.py:*),"
    "Bash(uv run scripts/plan.py:*)"
)
```

- [ ] **Step 2: Verify the allowlist test still passes**

Run: `cd /Users/mikeweng/Projects/alfred && python3 -m pytest tests/test_brain.py -v`
Expected: PASS (if a test asserts CHAT_TOOLS contents, update it to expect the new entry).

- [ ] **Step 3: Add the chat.md behavior section**

Append to `prompts/chat.md` a section (繁中) instructing 小當家:

```markdown
## 換菜單那天的菜（只換,不重排）

當 Mike 明確要把「現有的兩天對調」(換/對調/對換/互換/「X 跟 Y 換」/「今晚改吃 X」):
1. 讀 `state/plans/` 最新的計畫,搞清楚是哪兩天。
2. 用 heredoc 形式呼叫(不要用 `… |` pipe,allowlist 只認 `uv run` 開頭):
   `uv run scripts/plan.py swap <A> <B>`
   — <A>/<B> 可以是星期(週二/Tue)或菜名(牛排)。
3. 換好後用小當家的口吻確認,並補上相關提醒(回溫/退冰時機)。

⚠️ 規則:
- 只做「對調既有兩天」。**絕不**重新生成或鎖定整週菜單(那是儀式模式的事)。
- plan.py 回錯誤就照實轉達,別自己硬改檔案。
- 其他改動(換掉某天的菜、加菜、減菜、改時間)→ 用 `capture.py` 寫進 inbox,讓週日儀式處理,別假裝改了。
```

- [ ] **Step 4: Document under CLAUDE.md Commands**

Add a bullet under the Commands section of `CLAUDE.md`:

```markdown
- **Day swap (chat):** say 「把週二跟週三對調」/「今晚改吃牛排」in #小當家的廚房 →
  chat calls the vetted seam `scripts/plan.py swap <A> <B>` (weekday or dish name),
  which swaps the two days' content + reasoning in the latest `state/plans/` file and
  self-commits (`plan: swap …`). Swap-only; replace/add/remove still route to the
  Sunday ritual via inbox. Design: `docs/superpowers/specs/2026-06-16-alfred-chat-day-swap-design.md`.
```

- [ ] **Step 5: Commit**

```bash
cd /Users/mikeweng/Projects/alfred
git add scripts/brain.py prompts/chat.md CLAUDE.md
git commit -m "feat(swap): chat can call plan.py swap to reorder days (allowlist + prompt + docs)"
```

---

## Self-Review

**Spec coverage:**
- Seam `plan.py swap` — Tasks 1–5. ✓
- LLM/script division of labor — chat resolves NL (Task 6 prompt), script does deterministic edit (Tasks 1–2). ✓
- Freshness guard (>8 days) — Task 4. ✓
- Selector by weekday OR dish, exactly-one-row, ambiguous/unknown/same-row errors — Tasks 1 & 3. ✓
- Swap table cells + reasoning bullets, keep day labels — Tasks 1–2. ✓
- Self-commit, message `plan: swap …` — Task 5. ✓
- Allowlist `Bash(uv run scripts/plan.py:*)` — Task 6. ✓
- chat.md: explicit-swap-only, never lock a menu, fall back to capture.py — Task 6. ✓
- CLAUDE.md doc — Task 6. ✓
- Prep-schedule limitation — documented in spec; no code (accepted). ✓
- Tests: table+reasoning swap, others untouched, round-trip identity, selector cases, stale refused — Tasks 1–4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `swap_text(text, sel_a, sel_b)`, `_resolve(rows, selector)`, `rows` = `list[(label, content_cells)]`, `latest_plan_path(plans_dir)`, `plan_date(path)`, `swap(sel_a, sel_b, *, plans_dir, today, do_commit)`, `_commit(path, sel_a, sel_b, pdate)`, `main()` — names consistent across Tasks 1–6. ✓
