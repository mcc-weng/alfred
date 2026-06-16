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
    # Chat must never have a general Write/Edit tool; it writes ONLY through vetted scripts.
    assert "Write" not in tools and "Edit" not in tools
    # The only Bash scopes permitted are the vetted recipe-intake / capture / plan seams.
    vetted = [
        "Bash(uv run scripts/capture.py:*)",
        "Bash(uv run scripts/recipe_intake.py:*)",
        "Bash(uv run scripts/save_recipe.py:*)",
        "Bash(uv run scripts/plan.py:*)",
    ]
    for scope in vetted:
        assert scope in tools
    remaining = tools
    for scope in vetted:
        remaining = remaining.replace(scope, "")
    # No arbitrary / unscoped Bash beyond the vetted scripts.
    assert "Bash" not in remaining


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


def test_chat_tools_include_recipe_intake_seams():
    # chat mode must be able to fetch sources and save recipes (recipe intake)
    assert "WebFetch" in brain.CHAT_TOOLS
    assert "scripts/recipe_intake.py" in brain.CHAT_TOOLS
    assert "scripts/save_recipe.py" in brain.CHAT_TOOLS
    # and must keep its existing capture seam
    assert "scripts/capture.py" in brain.CHAT_TOOLS


def test_chat_prompt_has_recipe_enrichment():
    # The recipe-intake card must instruct: keep the verbatim source (📌 原始食譜),
    # scale servings, and offer 小當家's teaching sections. Guard against a future
    # chat.md edit silently dropping the enrichment + faithfulness block.
    p = brain.build_prompt("chat", history=[], messages=[])
    assert "原始食譜" in p          # the verbatim provenance block
    assert "2 人份" in p            # scale-to-household instruction
    assert "主廚秘訣" in p          # on-demand teaching section
