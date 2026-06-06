import json
import os
import pathlib
import stat
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import brain


def test_build_prompt_renders_history_and_messages():
    p = brain.build_prompt(
        "chat",
        history=[{"author": "Mike", "content": "hi"}],
        messages=[{"author": "Gf", "content": "want pad thai"}],
    )
    assert "Mike: hi" in p and "Gf: want pad thai" in p
    assert "小當家" in p  # persona from template


def test_mode_args_chat_is_readonly():
    args = brain.mode_args("chat")
    assert "--allowedTools" in args
    tools = args[args.index("--allowedTools") + 1]
    assert "Write" not in tools and "Bash" not in tools


def test_mode_args_ritual_has_scoped_bash():
    tools = brain.mode_args("ritual")[brain.mode_args("ritual").index("--allowedTools") + 1]
    assert "Bash(uv run scripts/discord_io.py:*)" in tools
    assert "Bash(git:*)" in tools and "Write" in tools


def test_run_brain_pipes_prompt_via_stdin(tmp_path):
    fake = tmp_path / "fake_claude"
    fake.write_text("#!/bin/sh\ncat > /dev/null\necho FAKE-REPLY\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    os.environ["CLAUDE_BIN"] = str(fake)
    try:
        out = brain.run_brain("chat", history=[], messages=[{"author": "Mike", "content": "yo"}])
        assert out.strip() == "FAKE-REPLY"
    finally:
        del os.environ["CLAUDE_BIN"]


def test_build_prompt_substitutes_date():
    p = brain.build_prompt("chat", history=[], messages=[])
    assert "{today}" not in p and "{weekday}" not in p


def test_run_brain_raises_on_nonzero_exit(tmp_path):
    fake = tmp_path / "fake_claude_fail"
    fake.write_text("#!/bin/sh\ncat > /dev/null\necho boom >&2\nexit 3\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    os.environ["CLAUDE_BIN"] = str(fake)
    try:
        with pytest.raises(RuntimeError, match="exited 3"):
            brain.run_brain("chat", history=[], messages=[{"author": "M", "content": "x"}])
    finally:
        del os.environ["CLAUDE_BIN"]
