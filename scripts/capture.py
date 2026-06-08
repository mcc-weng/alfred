# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Append-only capture of mid-week feedback to state/inbox.md.

Chat mode may call this (and ONLY this) to durably capture a verdict/craving/
preference/correction the instant it's said. The Sunday ritual reads + clears it.
Append-only and narrow: the only file it writes is state/inbox.md (path hardcoded);
it cannot read or modify any other state. Blast radius is bounded to inbox.md.

Usage: uv run scripts/capture.py <kind> "<note>"
  kind ∈ verdict|craving|preference|correction|note|lesson
"""
import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
INBOX = ROOT / "state" / "inbox.md"
KINDS = {"verdict", "craving", "preference", "correction", "note", "lesson"}
HEADER = ("# Capture inbox — mid-week feedback awaiting the next ritual\n"
          "<!-- Appended by chat via capture.py. The ritual reads + clears this. -->\n\n")


def format_line(date: str, kind: str, note: str) -> str:
    return f"- {date} [{kind}] {note}"


def append_note(path: pathlib.Path, date: str, kind: str, note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEADER)
    with path.open("a") as f:
        f.write(format_line(date, kind, note) + "\n")


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit("usage: capture.py <kind> \"<note>\"")
    kind = sys.argv[1] if sys.argv[1] in KINDS else "note"
    note = " ".join(sys.argv[2:]).strip()
    if not note:
        sys.exit("empty note")
    append_note(INBOX, datetime.datetime.now().strftime("%Y-%m-%d"), kind, note)
    print(f"captured [{kind}]: {note[:60]}")


if __name__ == "__main__":
    main()
