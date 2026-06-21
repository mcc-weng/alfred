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


def _plan_hash(plans_dir: pathlib.Path | None = None) -> str:
    """SHA1 of the latest plan file; empty string if none exists."""
    d = plans_dir if plans_dir is not None else ROOT / "state" / "plans"
    dated = sorted(d.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"))
    if not dated:
        return ""
    return hashlib.sha1(dated[-1].read_bytes()).hexdigest()


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
    sched["plan_hash"] = _plan_hash()
    SCHED.parent.mkdir(parents=True, exist_ok=True)
    SCHED.write_text(json.dumps(sched, ensure_ascii=False, indent=2))
    print(f"prep: planned {len(items)} item(s) for {today}")


def _replan(now: datetime.datetime) -> dict | None:
    """Rebuild today's schedule after a mid-day plan change.

    Past-due items are auto-marked sent so they can never re-fire.
    Returns the new schedule, or None if the brain call fails (skip this tick).
    """
    today = now.strftime("%Y-%m-%d")
    cook_time = _config().get("cook_time", "18:30")
    weekday = now.strftime("%A")
    prompt = (ROOT / "prompts" / "prep.md").read_text() \
        .replace("{today}", today).replace("{weekday}", weekday) \
        .replace("{cook_time}", cook_time)
    try:
        out = brain.run_brain("nudge", [], [], prompt_override=prompt)
    except Exception:
        return None
    items = parse_plan_output(out)
    sched = build_schedule(today, cook_time, items)
    sched["plan_hash"] = _plan_hash()
    for item in sched["items"]:
        if now >= datetime.datetime.fromisoformat(item["due"]):
            item["sent"] = True
    SCHED.write_text(json.dumps(sched, ensure_ascii=False, indent=2))
    future = sum(1 for it in sched["items"] if not it["sent"])
    print(f"prep: replanned after plan change ({future} future item(s))")
    return sched


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
    if sched.get("plan_hash", "") != _plan_hash():
        sched = _replan(datetime.datetime.now())
        if sched is None:
            return
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
