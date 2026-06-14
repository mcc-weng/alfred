# Alfred — Timed Prep Reminders + Reproduce-with-Swaps

**Date:** 2026-06-14
**Status:** Design approved, pending implementation plan
**Author:** 小當家 (with Mike)

## Overview

Two cooking-loop enhancements:

1. **Timed prep reminders** — proactive pings whose *timing is derived from each
   dish's own recipe*, anchored to a default cook-start time. e.g. 鹹酥雞 → a
   morning 「醃」 ping; 牛排 → a ping ~40 min before cooking to temper; a frozen
   protein → an evening "move it to the fridge" ping the night before.
2. **Reproduce-with-swaps** — in chat, Mike can ask 小當家 to regenerate a meal's
   full lesson with an ingredient swapped or corrected; 小當家 adapts the recipe,
   posts it, then *asks* whether to save it.

Both ride the existing seams. Feature 1 reuses the `nudge` brain mode + launchd
pattern; Feature 2 is a chat-mode capability over the existing `save_recipe.py`
write-seam.

## Goals / Non-goals

**Goals**
- Reminders fire at recipe-correct moments, in #小當家的廚房, in 小當家's voice.
- Silent when there's nothing to prep (most quick-dinner nights).
- No duplicate reminders, ever.
- Swapped recipes regenerate intelligently (adjust time/technique/quantity), not
  find-and-replace, and optionally persist.

**Non-goals (v1)**
- Tracking fridge/freezer contents (stays ephemeral — see thaw caveat).
- Auto-rescheduling pings when Mike changes tonight's cook time mid-day
  (conversational recompute only; see Future enhancements).

---

## Feature 1 — Timed prep reminders

### Architecture: "plan once, deliver cheaply"

Two launchd jobs, one new script `scripts/prep.py` with two subcommands:

| Subcommand | Role | Trigger | LLM? |
|---|---|---|---|
| `prep.py plan` | 小當家 reads today's + tomorrow's dinner recipes, reasons out a timed prep list, returns JSON. Wrapper writes `.runtime/prep_schedule.json`. | launchd, daily ~08:00 | yes — 1 call/day |
| `prep.py tick` | No LLM. Reads the schedule, posts any item now due, marks it sent. | launchd, every 15 min (`StartInterval` 900) | no |

Rejected alternatives: firing reminders from the live daemon's asyncio timers
(lost if the daemon is down — these are time-critical), and a single morning
text "timeline" digest (Mike explicitly wants a ping *at* each moment).

### Cook-time anchor

- `config.json` gains `"cook_time": "18:30"` — the default time Mike *starts*
  cooking dinner. All "X minutes before cooking" leads are measured from this.
- Per-day override is **conversational** in v1: if Mike says 「今晚八點才煮」,
  chat mode recomputes and tells him the adjusted times in the reply. The
  scheduled pings still use the default. (Auto-reschedule → Future enhancements.)

### `prep.py plan` contract

- Loads `prompts/prep.md`, substitutes `{today}`, `{weekday}`, `{cook_time}`.
- Calls `brain.run_brain("nudge", [], [], prompt_override=prompt)` — `nudge` mode
  is read-only (`Read,Glob`), exactly what the planner needs. **No `brain.py`
  change.** The wrapper (not the LLM) writes the file, mirroring `nudge.py`.
- The LLM returns **either** the literal `NOTHING` **or** a JSON array:
  ```json
  [{"time": "09:00", "msg": "⏰ 該醃雞腿了!今晚的鹹酥雞,早上先醃晚上炸才入味 🔥"},
   {"time": "17:50", "msg": "⏰ 牛排離冰箱回溫(下鍋前40分,冰肉下鍋外焦內冷)"}]
  ```
  - `time` is a 24h `HH:MM` clock string. The LLM computes it: before-cook leads =
    `cook_time − N`; morning prep is anchored to a **fixed 09:00 slot** (predictable,
    not LLM-whim); night-before thaw/long-marinate for *tomorrow's* dish → an
    evening time (e.g. `21:00`, still today's date).
  - `msg` is a short 繁中 ping in 小當家's voice (no heavy signature).
- The planner considers **today's** dinner (all same-day prep) AND **tomorrow's**
  dinner (only night-before items: thaw, long marinate).
- Wrapper writes `.runtime/prep_schedule.json`:
  ```json
  {"date": "2026-06-14", "cook_time": "18:30",
   "items": [{"id": "<hash(msg)>", "due": "2026-06-14T17:50:00",
              "msg": "...", "sent": false}]}
  ```
  `id` = short stable hash of `msg` (dedup key). `due` = today's date + `time`.

**Idempotency (fix):** `plan` is idempotent-by-date — if `prep_schedule.json`
already has today's date, it **no-ops** (does not clobber `sent` flags → no
re-posts on a second run / pmset re-fire). A future `--force` supports the
conversational override.

### `prep.py tick` contract

- Reads `.runtime/prep_schedule.json`. If `date != today` → stale → silent no-op
  (covers the pre-08:00 window and post-midnight rollover).
- For each item where `now >= due − grace` (grace = 15 min ≈ tick interval) **and**
  `sent == false` → collect it.
  - Putting the margin in the *tick* (not the planner) keeps planner times
    semantically clean (ideal action times) while guaranteeing a ping never fires
    *late* — at worst ~15 min early, never eating into the lead.
- Posts collected items (batched into one message if several) to channel `alfred`
  via `discord_io.py`, sets their `sent = true`, rewrites the JSON. Idempotent.
- Logs to `.runtime/prep-tick.log` / `.err` (matches nudge logging).

### Thaw caveat (honest limitation)

Fridge/freezer state is intentionally untracked. Thaw reminders are therefore
**best-effort, conditional** — the planner infers "bought Sun, cooked Sat →
probably frozen" and phrases softly: 「明天的肉若還冰著,今晚移到冷藏退冰」. The
marinate and temper reminders need no fridge knowledge and are exact.

### De-overlap

`prompts/nudge-morning.md` currently embeds a "現在就要做的準備" preamble. Trim it
— the timed prep system now owns prep; the 09:00 nudge keeps posting the full
lesson for tonight's cook.

### Most days are silent

Quick 拌飯/麵 nights need ~no advance prep → empty schedule → no pings. Reminders
concentrate on play-mode cooks (steak, 鹹酥雞). Not noisy by design.

---

## Feature 2 — Reproduce a meal with swapped ingredients

A **chat-mode** capability — chat already has `Read,Glob` and the `save_recipe.py`
seam in `CHAT_TOOLS`. No new daemon job, no new mode.

### Flow

1. Mike says e.g. 「青醬雞腿麵的雞腿沒了,改用雞胸,重新給我食譜」.
2. 小當家 identifies the dish: default = **today's dinner** (read latest
   `state/plans/` file → today's row → match title to a `state/cookbook/*.md`,
   same lookup the morning nudge already does); or the dish Mike names.
3. Reads that recipe and **regenerates the full lesson** (🔪備料 / 👨‍🍳步驟 /
   ⚠️翻車點 / 🔥秘訣 / ✅完成判準) with the swap intelligently applied — adjusts
   cook time, technique, and quantities; **explicitly flags what changed & why**;
   stays 2人份.
4. Posts the adapted lesson to #小當家的廚房.
5. **Asks** 「要把這個版本存成食譜嗎?」 (one question — respects the two-touchpoint rule).
6. **Yes** → save via `save_recipe.py`; **No** → ephemeral, nothing saved.

### Save behavior

- Saved as its **own new cookbook card** (default; the alternative — appending a
  「## 變化版」 section to the original — needs an Edit/append path chat lacks, so
  deferred).
- **Slug must be ASCII.** `save_recipe.py` slugifies by stripping non-Latin chars,
  so a 「雞胸」 suffix would collapse to the original slug and the dedup guard would
  silently refuse the write. Chat must pass an explicit ASCII suffix, e.g.
  `--slug pesto-chicken-pasta-chicken-breast`.
- `save_recipe.py` gains a `--variant` flag that **skips queuing a craving** (a
  variant is not a new craving). `--source` = `variant of <original-slug>`.
- Invoked via the `uv run`-prefixed **heredoc** form (never a `… |` pipe — the
  Bash allowlist only matches commands starting with the allowed prefix).

---

## Files

**New**
- `scripts/prep.py` — `plan` + `tick` subcommands.
- `prompts/prep.md` — planner prompt + strict JSON/NOTHING output contract.
- `launchd/com.alfred.prep-plan.plist` — daily ~08:00 → `prep.py plan`.
- `launchd/com.alfred.prep-tick.plist` — `StartInterval` 900 → `prep.py tick`.

**Edited**
- `config.json` — add `"cook_time": "18:30"`.
- `scripts/install_daemon.sh` — install the two new launchd jobs.
- `prompts/nudge-morning.md` — drop the prep preamble (de-overlap).
- `prompts/chat.md` — recognize reproduce-with-swaps; regenerate → post → ask → save.
- `scripts/save_recipe.py` — add `--variant` (skip craving) flag.

**Runtime (gitignored)**
- `.runtime/prep_schedule.json`, `.runtime/prep-{plan,tick}.log/.err`.

---

## Verification

- `prep.py plan` against the live plan → inspect `prep_schedule.json`: steak day
  emits a ~17:50 回溫 item; 鹹酥雞 day emits a 09:00 醃 item; a late-week protein
  emits a soft evening thaw item; 外食 day → `NOTHING`/empty.
- `prep.py tick` with a hand-crafted past-due item → posts once; second run →
  no double-post (sent flag honored). Stale-date file → silent.
- A few **pure unit tests** for the deterministic bits (cook_time − lead math,
  09:00 morning anchoring, `due − grace` due-check, hash-id dedup) — keep pytest
  green (currently 74).
- Feature 2 via **real chat use** (per "verify by real use" preference): swap a
  dish → adapted lesson posts → save prompt appears → "yes" writes an ASCII-slug
  variant with no spurious craving → "no" saves nothing.
- Update `TEST-CHECKLIST.md` with the new scenarios.

## Future enhancements

- Auto-reschedule pings when cook time is overridden mid-day (needs a chat-writable
  override file + `plan --force`).
- Append-variation save path (`## 變化版` on the original) once chat has a safe
  append seam.
