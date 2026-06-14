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
