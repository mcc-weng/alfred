# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Alfred's voice: proactive nudges. Usage: uv run scripts/nudge.py morning|sunday"""
import datetime
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import brain  # noqa: E402


def main() -> None:
    kind = sys.argv[1]  # morning | sunday
    now = datetime.datetime.now()
    template = (ROOT / "prompts" / f"nudge-{kind}.md").read_text()
    prompt = template.replace("{today}", now.strftime("%Y-%m-%d")).replace(
        "{weekday}", now.strftime("%A")
    )
    text = brain.run_brain("nudge", [], [], prompt_override=prompt)
    if text.strip().upper().rstrip(".") == "NOTHING" or not text.strip():
        print("nudge: nothing to say")
        return
    subprocess.run(
        ["/opt/homebrew/bin/uv", "run", str(ROOT / "scripts" / "discord_io.py"),
         "post", "--channel", "alfred", "--content", text],
        cwd=ROOT, check=True,
    )
    print(f"nudge: posted ({kind})")


if __name__ == "__main__":
    main()
