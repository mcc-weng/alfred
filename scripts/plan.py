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


def _reasoning_idx(lines: list[str], weekday: str) -> int | None:
    """Index of the `- 週X:` reasoning bullet for weekday, or None."""
    for i, ln in enumerate(lines):
        if re.match(rf"^- {weekday}\s*[:：]", ln):
            return i
    return None


def _reasoning_text(line: str) -> str:
    return re.split(r"[:：]", line, maxsplit=1)[1].strip()


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

    wd_a = re.search(r"週.", label_a).group()
    wd_b = re.search(r"週.", label_b).group()
    ra, rb = _reasoning_idx(lines, wd_a), _reasoning_idx(lines, wd_b)
    if ra is not None and rb is not None:
        text_a, text_b = _reasoning_text(lines[ra]), _reasoning_text(lines[rb])
        lines[ra] = f"- {wd_a}: {text_b}"
        lines[rb] = f"- {wd_b}: {text_a}"

    return "\n".join(lines)


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
