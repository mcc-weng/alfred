# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Alfred's brain: wraps headless `claude -p` (Max subscription, no API key).

Prompt is piped via STDIN — `--allowedTools` is variadic and would swallow a
trailing prompt argument (spiked 2026-06-07).
"""
import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
_CLAUDE_DEFAULT = "/Users/mikeweng/.local/bin/claude"


def _claude_bin() -> str:
    return os.environ.get("CLAUDE_BIN", _CLAUDE_DEFAULT)

CHAT_TOOLS = "Read,Glob,Grep"
RITUAL_TOOLS = (
    "Read,Glob,Grep,Write,Edit,"
    "Bash(uv run scripts/discord_io.py:*),Bash(git:*),Bash(curl:*)"
)
TIMEOUT = {"chat": 180, "ritual": 900, "nudge": 180}


def _config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def _render(lines: list[dict]) -> str:
    return "\n".join(f"{m['author']}: {m['content']}" for m in lines) or "(none)"


def build_prompt(mode: str, history: list[dict], messages: list[dict]) -> str:
    template = (ROOT / "prompts" / f"{mode}.md").read_text()
    return template.replace("{history}", _render(history)).replace(
        "{messages}", _render(messages)
    )


def mode_args(mode: str) -> list[str]:
    cfg = _config()
    if mode == "ritual":
        return ["--model", cfg.get("ritual_model", "sonnet"),
                "--allowedTools", RITUAL_TOOLS]
    return ["--model", cfg.get("chat_model", "sonnet"),
            "--allowedTools", CHAT_TOOLS]


def run_brain(mode: str, history: list[dict], messages: list[dict],
              prompt_override: str | None = None) -> str:
    prompt = prompt_override or build_prompt(mode, history, messages)
    result = subprocess.run(
        [_claude_bin(), "-p", *mode_args(mode)],
        input=prompt.encode(),
        capture_output=True,
        cwd=ROOT,
        timeout=TIMEOUT.get(mode, 180),
    )
    if result.returncode != 0:
        raise RuntimeError(f"brain exited {result.returncode}: "
                           f"{result.stderr.decode()[:500]}")
    return result.stdout.decode().strip()
