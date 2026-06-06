# Alfred v1 — Weekly Cooking Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Alfred v1 engine — a Claude Code skill + Discord bot I/O + markdown state — so the first Sunday planning ritual (fridge photo → week plan → recipes + Woolies list posted to Discord) runs this week.

**Architecture:** Claude Code (Max subscription) is the brain; a single Python script does Discord bot REST I/O (read channel history, post messages); all durable state is markdown in `state/`, git-versioned. No daemon, no hosting — those are v1.5 (separate plan). Fridge inventory is ephemeral by design and never written to state.

**Tech Stack:** Claude Code project skill (`.claude/skills/`), Python 3.11+ single-file script via `uv run` (stdlib only), Discord bot REST API v10, pytest (via `uv run --with pytest`).

**Spec:** `docs/superpowers/specs/2026-06-06-alfred-cooking-loop-design.md`

---

## File structure

```
alfred/
├── CLAUDE.md                          # repo orientation: Alfred persona, commands, state map
├── .gitignore                         # .env, caches
├── .env                               # DISCORD_BOT_TOKEN — NEVER committed
├── config.json                        # server + channel IDs (not secret, committed)
├── scripts/
│   └── discord_io.py                  # bot REST I/O: `read` / `post` subcommands
├── tests/
│   └── test_discord_io.py             # unit tests for message splitting (the only real logic)
├── .claude/skills/plan-week/
│   └── SKILL.md                       # the Sunday ritual orchestration (the engine's heart)
└── state/
    ├── staples.md                     # assumed pantry — never on shopping lists
    ├── preferences.md                 # tastes, allergies, nutrition defaults
    ├── woolworths.md                  # ingredient → preferred Woolies product map (learned)
    ├── cookbook/                      # one file per recipe, verdict log appended
    └── plans/                         # locked weekly plans, YYYY-MM-DD.md
```

---

### Task 1: Repo scaffolding + state templates

**Files:**
- Create: `.gitignore`, `CLAUDE.md`, `config.json`, `state/staples.md`, `state/preferences.md`, `state/woolworths.md`, `state/cookbook/.gitkeep`, `state/plans/.gitkeep`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
.env
__pycache__/
.pytest_cache/
*.pyc
```

- [ ] **Step 2: Create `config.json`** (IDs filled in Task 3)

```json
{
  "server_id": "",
  "channels": {
    "alfred": "",
    "meal-plan": ""
  }
}
```

- [ ] **Step 3: Create `CLAUDE.md`**

```markdown
# Alfred — Household Chef Agent

Lively chef agent for Mike + his girlfriend. Full design:
`docs/superpowers/specs/2026-06-06-alfred-cooking-loop-design.md`

## You are Alfred
When operating in this repo you are **Alfred**: a warm, brief, slightly butler-ish
chef. Discord posts are signed "— Alfred 🤵". Two-touchpoint rule during rituals:
ask at most two questions (inventory correction, plan tweaks). Never twenty-questions.

## Commands
- **Weekly ritual:** use the `plan-week` skill (triggers: "plan the week", "alfred plan")
- **Discord I/O** (run from repo root):
  - `uv run scripts/discord_io.py read --channel alfred --limit 100`
  - `uv run scripts/discord_io.py post --channel meal-plan --content "..."`
  - long content via stdin: `cat msg.md | uv run scripts/discord_io.py post --channel meal-plan`

## State (all markdown, git-versioned)
- `state/staples.md` — assumed pantry; excluded from shopping lists unless flagged low
- `state/preferences.md` — tastes, dislikes, allergies, nutrition defaults
- `state/cookbook/` — one file per recipe ever planned; verdict log appended
- `state/plans/` — locked weekly plans (`YYYY-MM-DD.md`)
- `state/woolworths.md` — ingredient → preferred Woolies product map; update on every correction
- **Fridge inventory is EPHEMERAL** — never write fridge contents to state

## Rules
- `.env` holds `DISCORD_BOT_TOKEN` — never commit it, never print it
- `config.json` holds channel IDs (not secret)
- After a ritual: commit state changes with message `ritual: week of YYYY-MM-DD`
```

- [ ] **Step 4: Create `state/staples.md`** (starter list — Mike edits at onboarding, Task 5)

```markdown
# Pantry staples — assumed always present
<!-- Never added to shopping lists unless someone flags "out of X" in #alfred -->

- olive oil, neutral oil (canola), sesame oil
- soy sauce, oyster sauce, fish sauce, rice vinegar
- salt, black pepper, sugar, honey
- rice (jasmine), pasta, flour, cornflour
- garlic, brown onions, ginger
- chicken stock cubes, canned tomatoes
- common spices: paprika, cumin, chilli flakes, curry powder
- butter, eggs
```

- [ ] **Step 5: Create `state/preferences.md`** (structure now; content filled at onboarding, Task 5)

```markdown
# Household preferences

## People
- Mike
- Gf

## Allergies / hard nos
<!-- filled at onboarding (Task 5) -->

## Dislikes (soft — avoid unless asked)
<!-- filled at onboarding (Task 5) -->

## Nutrition defaults
- Every dinner anchored on a protein source, ~30–40 g/serve
- Whole-food bias; no macro tracking in v1

## Week shape defaults
- Dinners only; default 6 dinners/week (confirm count each ritual)
- Mode mix default: 3 fast + 1 batch + 2 play
- fast ≈ ≤30 min · batch = cook once eat twice · play = learning session, no time cap
```

- [ ] **Step 6: Create `state/woolworths.md`**

```markdown
# Woolworths product map
<!-- Learned from Mike's corrections. Format: one line per ingredient. -->
<!-- ingredient → exact product name as sold | pack size | notes -->

| Ingredient | Woolies product | Pack | Notes |
|---|---|---|---|
```

- [ ] **Step 7: Create empty dirs and commit**

```bash
mkdir -p state/cookbook state/plans && touch state/cookbook/.gitkeep state/plans/.gitkeep
git add -A
git commit -m "feat: scaffold repo — CLAUDE.md, config, state templates"
```

---

### Task 2: Discord I/O script (TDD on the splitter)

**Files:**
- Create: `scripts/discord_io.py`
- Test: `tests/test_discord_io.py`

The only real *logic* is message splitting (Discord caps messages at 2000 chars; recipes can exceed that). TDD that. The REST calls are thin wrappers verified live in Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discord_io.py`:

```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
from discord_io import split_message


def test_short_message_is_single_chunk():
    assert split_message("hello") == ["hello"]


def test_splits_at_newline_before_limit():
    text = "a" * 1500 + "\n" + "b" * 1000
    chunks = split_message(text)
    assert chunks == ["a" * 1500, "b" * 1000]


def test_all_chunks_within_limit():
    text = ("line of recipe text\n" * 400).strip()
    assert all(len(c) <= 2000 for c in split_message(text))


def test_hard_split_when_no_newline():
    chunks = split_message("x" * 4500)
    assert [len(c) for c in chunks] == [2000, 2000, 500]


def test_empty_text_returns_no_chunks():
    assert split_message("") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discord_io'`

- [ ] **Step 3: Write the script**

Create `scripts/discord_io.py`:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Alfred's Discord bot I/O (REST API v10, stdlib only). Run from repo root.

Usage:
  uv run scripts/discord_io.py read --channel alfred --limit 100
  uv run scripts/discord_io.py post --channel meal-plan --content "text"
  cat long.md | uv run scripts/discord_io.py post --channel meal-plan
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.request

API = "https://discord.com/api/v10"
MAX_LEN = 2000
ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def request(method: str, path: str, payload: dict | None = None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode() if payload else None,
        headers={
            "Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}",
            "Content-Type": "application/json",
            "User-Agent": "Alfred (private household agent, 1.0)",
        },
        method=method,
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split text into <=limit chunks, preferring newline boundaries."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def channel_id(name: str) -> str:
    config = json.loads((ROOT / "config.json").read_text())
    cid = config["channels"].get(name, "")
    if not cid:
        sys.exit(f"config.json has no id for channel '{name}' — run Task 3 setup")
    return cid


def cmd_read(args) -> None:
    msgs = request(
        "GET", f"/channels/{channel_id(args.channel)}/messages?limit={args.limit}"
    )
    out = [
        {
            "author": m["author"].get("global_name") or m["author"]["username"],
            "bot": m["author"].get("bot", False),
            "timestamp": m["timestamp"],
            "content": m["content"],
            "attachments": [a["url"] for a in m.get("attachments", [])],
        }
        for m in reversed(msgs)  # API returns newest first; emit oldest first
    ]
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_post(args) -> None:
    content = args.content if args.content is not None else sys.stdin.read()
    chunks = split_message(content.strip())
    for chunk in chunks:
        request(
            "POST",
            f"/channels/{channel_id(args.channel)}/messages",
            {"content": chunk},
        )
    print(f"posted {len(chunks)} message(s) to #{args.channel}")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="read recent messages, oldest first, as JSON")
    r.add_argument("--channel", required=True)
    r.add_argument("--limit", type=int, default=50)
    r.set_defaults(fn=cmd_read)
    p = sub.add_parser("post", help="post content (auto-splits at 2000 chars)")
    p.add_argument("--channel", required=True)
    p.add_argument("--content", help="message text; omit to read from stdin")
    p.set_defaults(fn=cmd_post)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/ -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/discord_io.py tests/test_discord_io.py
git commit -m "feat: discord bot I/O script with tested message splitting"
```

---

### Task 3: Discord setup (REQUIRES MIKE) + live verification

**Files:**
- Create: `.env` (never committed)
- Modify: `config.json` (fill IDs, commit)

> ⚠️ **Human steps** — Mike at the keyboard (~15 min, one-time). The agent waits, then verifies.

- [ ] **Step 1 (Mike): Create the server and channels**

In Discord: create private server "Alfred's Kitchen" (any name) → create text channels `#alfred` and `#meal-plan` → invite gf.

- [ ] **Step 2 (Mike): Create the bot**

https://discord.com/developers/applications → New Application → name **Alfred** →
Bot tab → Reset Token → copy token → enable **MESSAGE CONTENT INTENT** →
OAuth2 → URL Generator → scope `bot`, permissions: *View Channels, Send Messages,
Read Message History, Manage Messages* → open generated URL → add to the server.

- [ ] **Step 3 (Mike): Provide secrets and IDs**

Create `.env` in repo root (Discord: Settings → Advanced → Developer Mode ON, then right-click server/channels → Copy ID):

```bash
DISCORD_BOT_TOKEN=<paste token>
```

Fill `config.json` with the server ID and both channel IDs.

- [ ] **Step 4: Verify post (live)**

Run: `uv run scripts/discord_io.py post --channel meal-plan --content "Alfred online. 🤵"`
Expected: `posted 1 message(s) to #meal-plan` — and the message visible in Discord, authored by **Alfred**.

- [ ] **Step 5: Verify read + attachments (live)**

Mike posts a test message and any photo in `#alfred`, then:

Run: `uv run scripts/discord_io.py read --channel alfred --limit 5`
Expected: JSON including the test message content and a non-empty `attachments` URL for the photo. Download check: `curl -s -o /tmp/test.jpg "<url>" && file /tmp/test.jpg` → image file.

- [ ] **Step 6: Verify `.env` is ignored, commit config**

Run: `git status --short` — `.env` must NOT appear.

```bash
git add config.json
git commit -m "chore: discord server + channel IDs configured"
```

---

### Task 4: The `plan-week` skill (the engine's heart)

**Files:**
- Create: `.claude/skills/plan-week/SKILL.md`

- [ ] **Step 1: Create the skill**

Create `.claude/skills/plan-week/SKILL.md`:

````markdown
---
name: plan-week
description: Run Alfred's Sunday planning ritual — harvest the Discord channel, read the fridge photo, propose the week, post recipes + Woolies list + summary to #meal-plan, save state. Use when Mike says "plan the week", "alfred plan", or starts the Sunday ritual.
---

# Alfred — Weekly Planning Ritual

You are Alfred 🤵, the household chef. Mike and his gf are on the couch — this is
a couple ritual. Be warm and brief. **Two-touchpoint rule:** you may ask at most
TWO questions in the whole ritual (steps 3 and 5). Bundle everything else.

## Step 1 — Harvest the channel
Run: `uv run scripts/discord_io.py read --channel alfred --limit 100`
From messages since the last plan (newest file in `state/plans/`), extract:
- **Verdicts** on last week's meals ("banger", "meh, too salty", 👎 sentiments)
- **Cravings/requests** ("want pad thai", "something spicy")
- **Flags** ("out of olive oil" → add to shopping list even if a staple)
- **Fridge photo** — the most recent image attachment

## Step 2 — Process verdicts FIRST
For each verdict, append to the matching `state/cookbook/<slug>.md` under
`## Verdicts`: `- YYYY-MM-DD: <verbatim feedback> (<who>)`. Bangers become
rotation candidates; "no repeat" verdicts are excluded from future plans.

## Step 3 — Inventory (Touchpoint 1)
Download the fridge photo: `curl -s -o /tmp/fridge.jpg "<attachment url>"`, then
Read it. No photo in the channel? Ask Mike to paste one into the session.
List every perishable you can identify, grouped (veg / protein / dairy / other).
Then ask ONE question: *"Anything hidden — crisper, leftovers, freezer plans?"*
The corrected snapshot is **ephemeral**: use it for this plan, never save it.

## Step 4 — Read state before proposing
- `state/preferences.md` — allergies are HARD constraints; week shape defaults
- `state/staples.md` — assume present; exclude from the shopping list
- last 2 files in `state/plans/` — nothing repeats from these unless it was a
  🔥 banger that someone asked for
- `state/cookbook/` — bangers not cooked in ~4 weeks are rotation candidates
- `state/woolworths.md` — preferred products for the list

## Step 5 — Propose the week (Touchpoint 2)
Confirm dinner count (default 6), then propose the COMPLETE week in one message.
Per dinner: **name · mode (fast/batch/play) · ~minutes · one-line reasoning**
(what it uses up / whose craving / protein anchor / what technique it teaches).
Default mix 3 fast + 1 batch + 2 play. Every dinner: protein ~30–40 g/serve.
`play` meals should teach something — name the technique. Apply tweaks; lock on
approval.

## Step 6 — Post to #meal-plan, in EXACTLY this order
(newest message must end up being the summary)
1. One post per dinner — full recipe, format below
2. The Woolworths shopping list, format below
3. "The Week" summary, format below

Post each via stdin to handle length:
`cat /tmp/msg.md | uv run scripts/discord_io.py post --channel meal-plan`

### Recipe format (aim ≤1900 chars; phone-at-the-stove scannable)
```
🍳 **{Day} — {Dish name}**  ({mode} · ~{min} min · serves 2)

**Ingredients**
- {qty} {item}   (one per line, grouped: protein, veg, sauce)

**Steps**
1. Short imperative steps. Numbered. No prose walls.

💡 {one technique tip if play mode}
— Alfred 🤵
```

### Shopping list format
```
🛒 **Woolies — week of {date}**

**Produce**
- {Woolworths product name} · {pack size} · x{qty}
**Meat & seafood**
...
**Dairy & fridge**
...
**Pantry**
...

(staples assumed: see anything missing, shout)
— Alfred 🤵
```
Use `state/woolworths.md` products where known; otherwise best guess + "(or
equivalent)". Pack-size reasoning: recipes say "1 onion", Woolies sells units —
pick the sensible purchasable size. Consolidate across recipes.

### Summary format
```
📅 **The Week — {date range}**
Mon · {dish} ({mode}, {min}m)
Tue · {dish} ({mode}, {min}m)
...
🛒 list above · 📖 recipes above · drop cravings + verdicts here anytime
— Alfred 🤵
```

## Step 7 — Save state
- `state/plans/YYYY-MM-DD.md`: the locked week (dishes, modes, reasoning) + the
  shopping list
- For each NEW dish: create `state/cookbook/<slug>.md` with the full recipe and
  an empty `## Verdicts` section. Existing dishes: add `- planned YYYY-MM-DD`.
- Any product corrections from Mike → update `state/woolworths.md`

## Step 8 — Close the ritual
Remind Mike: *"Order's ready to tap into the Woolies app — aim for a Monday
slot."* Then: `git add state/ && git commit -m "ritual: week of YYYY-MM-DD"`

## Hard rules
- Allergies are absolute. Dislikes need an explicit request to override.
- Fridge inventory NEVER persists anywhere.
- Don't exceed two questions. Don't post to #alfred (that's the humans' channel —
  v1 Alfred only posts to #meal-plan).
- If `discord_io.py` fails, finish the ritual in-session and give Mike the posts
  as copy-paste blocks. Degraded beats broken.
````

- [ ] **Step 2: Verify skill discovery**

Run: `ls .claude/skills/plan-week/SKILL.md` and start a fresh Claude Code session; confirm `plan-week` appears in available skills (or `/plan-week` resolves).
Expected: skill listed/invocable.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/plan-week/SKILL.md
git commit -m "feat: plan-week ritual skill — the v1 engine"
```

---

### Task 5: Onboarding + dry-run ritual (acceptance test)

No new files — this exercises everything end-to-end with Mike present.

- [ ] **Step 1 (with Mike): Fill preferences**

Ask Mike (and gf if present) in one batch: allergies/hard-nos, dislikes, usual dinner count. Write answers into `state/preferences.md` sections. Ask Mike to skim `state/staples.md` and add/remove items.

- [ ] **Step 2 (Mike): Seed the channel like a real week**

Mike posts into `#alfred`: a real fridge photo + 2–3 fake-but-realistic messages ("want something spicy", "out of soy sauce").

- [ ] **Step 3: Run the full ritual**

Invoke the `plan-week` skill. Verify each stage as it happens:
- harvest picks up the photo URL + cravings → ✓
- inventory list shown, one correction question only → ✓
- complete week proposed in one message, modes + reasoning present → ✓
- after approval: recipes posted, then list, then summary (summary is newest in `#meal-plan`) → ✓
- `state/plans/<today>.md` + cookbook entries created → ✓

- [ ] **Step 4: Check against spec success criteria**

- Ritual wall-clock ≤ 10 min (criterion 2)
- Shopping list usable in the Woolies app without rewriting (criterion 4 precondition)
- Both phones can read the recipes comfortably in `#meal-plan`

Any failure → fix the SKILL.md prompt (most issues are prompt issues), re-run, don't proceed until clean.

- [ ] **Step 5: Commit the ritual output**

```bash
git add state/
git commit -m "ritual: dry-run week — v1 acceptance"
```

---

## Self-review (spec coverage)

| Spec section | Covered by |
|---|---|
| Weekly ritual, two-touchpoint rule | Task 4 SKILL.md steps 1–8 |
| Ephemeral inventory / durable preferences split | Task 1 templates + SKILL.md hard rules |
| Recipe / list / summary formats + posting order | Task 4 formats section |
| Verdict harvesting → cookbook | SKILL.md step 2 |
| Woolies product map learning | Task 1 `woolworths.md` + SKILL.md step 7 |
| Bot account, channels, token hygiene | Task 3 |
| 2000-char limit handling | Task 2 (TDD'd splitter) |
| Degraded mode (Discord down) | SKILL.md hard rules |
| Success criteria | Task 5 step 4 |
| v1.5 daemon, v2 cart automation | **Deliberately separate plans** |
