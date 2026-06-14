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
