# Alfred — Chat-Driven Day Swap

**Date:** 2026-06-16
**Status:** Design approved, pending implementation plan
**Scope:** Let 小當家 swap two days' meals in the current week's plan, in chat, so the change persists and the morning nudge follows the new order.

## Problem

On 2026-06-16 Mike asked 小當家 (in #小當家的廚房) to swap Tuesday and Wednesday — eat steak tonight instead of 三杯雞. Chat mode is read-only, so 小當家 replied 「菜單只是參考,自由調換」 and delivered the steak recipe, but **never changed the plan file**. The morning nudge reads `state/plans/<latest>.md` by weekday and dumps that day's recipe (`prompts/nudge-morning.md`), so the next morning would have re-served the *steak* recipe (週三=牛排, unchanged) and skipped 三杯雞 — a silent desync between what's cooked and what's planned.

The desync was patched by hand this once. We want 小當家 to be able to swap days himself.

## Guiding principle

The chat/ritual split is often described as "chat is read-only," but that's the symptom. The real lesson from the 2026-06-14 lock-word bug is:

> **The mode you route to must have the tools for the intent you detected.**

That bug happened because chat *detected* a lock intent but *lacked* lock capability → 240s thrash. Read-only is just the **default** for open conversation, not a sacred rule. Specific write-intents already get the capability they need: 裝車 → `cart` mode, 排菜單/lock → `ritual` mode. And chat already performs *scoped* writes through vetted scripts (`capture.py`, `recipe_intake.py`, `save_recipe.py`).

A day-swap is one more scoped write. We give it capability the same way: a vetted scalpel.

## Why a scalpel, not a "write chat"

Mechanically, a "mode" is just a headless `claude -p` subprocess with a different `--allowedTools` string, `--model`, prompt file, and timeout (`scripts/brain.py:75-88`). "Read-only chat" = the chat subprocess whose allowlist is read tools + three named write *scripts* (`brain.py:23-28`). A "write chat" would be that same subprocess with `Write,Edit,Bash(git:*)` added (what ritual gets, `brain.py:29-32`).

We deliberately do **not** flip chat to general `Write`:

1. **Blast radius.** Chat runs on every channel message, on ambiguous input, on a faster model. General `Write` means any misread message could overwrite the locked plan or corrupt state. Least privilege: don't carry that risk every turn.
2. **Integrity isn't solved by `Write`.** An LLM hand-editing a markdown table can drop a row, misalign a column, lose the nutrition cell. A deterministic `swap` function cannot.
3. **Testability.** `swap(a, b)` is a pure function with unit tests. Freehand editing is untestable.
4. **Auditability.** `Bash(uv run scripts/plan.py:*)` declares exactly what chat can do to the plan. `Write` declares "anything."

The model already supplies the natural-language *understanding*; what it lacks is a *safe, correct* way to mutate. The scalpel is that — write capability, scoped and correct-by-construction.

## Architecture

Add **one growable plan-operations CLI**: `scripts/plan.py`. v1 ships exactly one subcommand, `swap`. Future plan edits (replace, retime) become new subcommands in the same file — one stable allowlist entry, not a proliferation of one-off scripts.

```
uv run scripts/plan.py swap <selectorA> <selectorB>
```

- **No new mode, no routing change.** The swap stays in chat mode. 「對換」/「對調」/「換」 already fall through to chat (no existing trigger catches them), and we avoid a fragile routing regex on 換 (which also appears in 「換個口味」 = a craving, not a plan edit).
- **One allowlist line** in `brain.py`: add `Bash(uv run scripts/plan.py:*)` to `CHAT_TOOLS`.

### Division of labor

- **Chat LLM** — natural-language understanding. Reads the plan, maps「今晚想吃牛排,跟三杯雞對調」or「把週二週三對換」to the two target days, calls `plan.py swap`.
- **`plan.py`** — integrity. Deterministic edit that cannot malform the file; validation; self-commit.

## `plan.py swap` behavior

1. **Locate the plan.** Latest file in `state/plans/` by filename (filenames are `YYYY-MM-DD.md`, lexical max = newest).
2. **Freshness guard.** If the latest plan's date is more than 8 days before today, refuse with a clear message (same rule the nudge uses, `nudge-morning.md:10`). Never edit a stale plan.
3. **Resolve selectors.** Each selector matches a plan row by **weekday** (`週二`, `Tue`, `Tuesday`) *or* **dish substring** (`牛排`). Each selector must resolve to exactly one distinct row; otherwise exit non-zero with a message naming the problem (unknown / ambiguous / both resolve to same row) so the LLM can relay it.
4. **Swap.** Exchange the two rows' **content cells** (dish / 模式 / 時間 / 每份營養), keeping the day labels (`週二 Tue`, `週三 Wed`) fixed in their rows. Also swap the matching `- 週X:` bullets in the `## Reasoning` section (keep each `- 週X:` prefix, exchange the descriptive text). This mirrors the manual fix applied 2026-06-16.
5. **Write + self-commit.** Re-render and write the file, then commit internally: `plan: swap <dishA>↔<dishB> (week of <plan-date>)`. The script runs git itself — chat never gets general `git` or `Write`.
6. **Output.** On success, print a short structured confirmation (the two days and their new dishes) for the LLM to voice. On any failure, exit non-zero with the reason.

### Plan file format (current, unchanged)

```
| 天 | 料理 | 模式 | 時間 | 每份營養* |
|---|---|---|---|---|
| 週二 Tue | 三杯雞 + 白飯 | play | 35分 | ~50P / 810kcal |
| 週三 Wed | 牛排 | play | 30分 | ~46P / 540kcal |
...
## Reasoning
- 週二: play — 三杯雞，本週絕學：收汁與醬感判斷
- 週三: play — 牛排，上週 banger 技巧熟練，自信重現
```

`swap` is purely textual row/line surgery on this format — no conversion to structured data (the markdown plan remains the single source of truth that the nudge and prep schedule both read by weekday).

## Chat integration (`prompts/chat.md`)

Add a section instructing 小當家:

- On an **explicit request to rearrange existing days** (swap / 對調 / 對換 / 互換 / 「X 跟 Y 換」 / 「今晚改吃 X」): resolve the two days from the current plan and call `uv run scripts/plan.py swap <A> <B>` (via the `uv run`-prefixed form the allowlist matches — never a `… |` pipe). Then confirm in 小當家's voice plus the relevant logistics note (回溫/退冰 timing).
- **Never** regenerate or lock a whole menu — that remains ritual-only. If `plan.py` returns an error, relay it naturally and do not attempt a freehand edit.
- For any **other** plan change (replace a day's dish, add/remove a dish, retime): this is out of scope for v1. Capture it to `state/inbox.md` via `capture.py` so the Sunday ritual reconciles it — do not silently refuse, and do not pretend to apply it.

## Known limitation (documented, accepted for v1)

The prep-reminder schedule is built once per day at 08:00, idempotent-by-date (`prep.py plan`, `scripts/prep.py`). A swap made *after* 08:00 will **not** retroactively change *today's* already-built prep reminders. This is acceptable because:

- The **morning recipe nudge reads the plan live each morning**, so tomorrow's recipe always follows the swap — this is the actual problem being solved.
- Future days' prep schedules regenerate correctly from the swapped plan on their own 08:00 run.

v1 does not auto-poke prep regeneration (keeps the seam decoupled). Revisit only if same-day prep desync proves to matter in real use.

## Out of scope (v1)

- Replacing / adding / removing dishes (→ `capture.py` → ritual).
- Editing nutrition, modes, or shopping list.
- Cross-week moves (single current plan only).
- Auto-resyncing the prep schedule on swap.
- Structured-data plan model + shared render layer (heavier; not needed while the markdown plan is the working source of truth).

## Testing

`swap` is pure logic over a plan string — unit-testable without Discord or `claude`:

- Swaps both the table rows and the matching Reasoning bullets.
- Leaves all other days, the header, nutrition footnote, and shopping list untouched.
- Swap-then-swap-back returns the original file byte-for-byte.
- Selector resolution: weekday token, English day, and dish substring all resolve; unknown / ambiguous / same-row selectors error cleanly (non-zero exit, clear message).
- Stale plan (>8 days old) is refused.

Follows the existing pure-helper + test pattern from the prep work (`scripts/prep.py` helpers + tests, commit `4b0bfb8`).

## Footprint summary

- **New:** `scripts/plan.py` (one subcommand, `swap`) + tests.
- **Changed:** `brain.py` `CHAT_TOOLS` (+1 allowlist line); `prompts/chat.md` (+1 section); `CLAUDE.md` (document the swap capability under Commands).
- **Unchanged:** modes, routing, plan file format, nudge, cart, ritual.
