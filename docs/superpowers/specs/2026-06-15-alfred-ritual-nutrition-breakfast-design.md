# Alfred — Craving Deck + Nutrition + Breakfast (Ritual v2)

**Date:** 2026-06-15
**Status:** Design approved, pending implementation plan
**Author:** 小當家 (with Mike)

## Overview

Three enhancements to the weekly planning loop, all landing in the ritual
(`plan-week` skill), the recipe-card format, and `state/`:

1. **Nutrition (display-only)** — per-serve **protein + calories** shown on every
   recipe, the weekly summary, and each craving-deck card. Mike is cutting fat;
   numbers steer choices but nothing is "optimized to a target" in v1.
2. **Breakfast (rotating go-to set)** — a small curated set of quick high-protein
   breakfasts in `state/breakfasts.md`, provisioned onto the weekly shopping list.
   Not planned day-by-day.
3. **Craving deck** — Touchpoint 1 of the ritual becomes a numbered deck of 8
   candidate dishes (proven + craved + new + challenge) that Mike & gf react to,
   killing the blank-page problem while injecting novelty and skill progression.

These interlock (the deck shows macros; breakfast is provisioned during the
ritual), so they ship as one ritual upgrade but are independently buildable.

## Goals / Non-goals

**Goals**
- Make "what do we eat?" a *reaction*, not a blank page — with built-in surprise.
- Surface protein + calories everywhere a dish is named, to support the cut.
- Cover breakfast without adding daily decision load.

**Non-goals (v1)**
- Macro *targets* / optimization (protein floor, calorie cap) — display only.
- Full macros (carbs/fat) — protein + calories only.
- Per-day breakfast planning — it's a stable rotation, not a weekly plan.
- Reaction via Discord emoji reactions — interaction is plain text (rides the
  existing listener message flow; no `reaction_add` plumbing).

---

## Feature A — Nutrition (protein + calories, display-only)

### Estimate once, store, reuse
- When a recipe is **created** (ritual Step 7, or chat recipe-intake), 小當家
  estimates **per-serve protein (g) + calories** from the ingredients and portion
  (recipes are 2人份 → per serve = per person) and writes a macro line into the
  cookbook card, near the top:
  ```
  🔢 每份 ~38g 蛋白 · ~520 kcal
  ```
- Stored in the card → **stable, not re-guessed** each read. The morning nudge and
  weekly summary just relay the stored value.
- Estimates are directional home-cook rough numbers, always marked `~`.

### Where it surfaces
1. **Recipe card** (cookbook + morning nudge, which relays the card verbatim).
2. **Weekly summary line:** `週一 · 蔥香雞腿 (fast, 35分 · 38P/520kcal)`.
3. **Each craving-deck candidate** (see Feature C) — so diet-friendly picks are obvious.

### Backfill
One-time pass adds a macro line to existing `state/cookbook/*.md`. New recipes get
it via the updated card template, so no ongoing special-casing.

### State / prompt edits
- `state/preferences.md` → flip "no macro tracking in v1" to: "show per-serve
  protein + calories (LLM-estimated, directional, `~`); Mike cutting fat → favor
  high-protein, lean dinners."
- `plan-week` SKILL recipe-format + summary-format templates gain the macro line.

### Cross-ref
The reproduce-with-swaps flow (separate spec, 2026-06-14) regenerates the full
card, so it must re-estimate the macro line for the swapped version.

---

## Feature B — Breakfast (rotating go-to set)

### `state/breakfasts.md`
A curated set of ~5 quick, high-protein breakfasts. Per entry:
```
### 希臘優格高蛋白碗
~30g 蛋白 · ~350 kcal · 5分
- 食材:無糖希臘優格、莓果、燕麥、蜂蜜、堅果
- 做法:優格鋪底,撒燕麥莓果堅果,淋一點蜂蜜。
```
High-protein bias for the cut. These are assembly/minimal-cook, lighter than the
dinner lessons.

### Seeding
On first build, 小當家 proposes ~5; Mike approves/tweaks; the set is written once.
Thereafter it's stable.

### Editing (v1: via the ritual, not live chat)
Chat mode is read-only (no Write), so breakfast-set edits flow through the inbox:
「早餐加 X / 換掉 Y」 → chat appends to `state/inbox.md` via `capture.py` → the
**ritual reconciles** breakfast edits into `breakfasts.md` (Step 2/7). Slowly-
changing rotation, so ritual-cadence updates are fine.

### Shopping provisioning
The weekly Woolies list (ritual Step 6) gains a **Breakfast** group that provisions
the active set's weekly-consumed ingredients (eggs, Greek yogurt, oats, fruit,
bread…), tagged `[woolies]`/`[asianpantry]` as usual, deduped against
`state/staples.md` (don't list true always-stocked pantry items).

### Daily surface
**Not** in the morning nudge (it's a known rotation). Ask 「今天早餐吃啥」 in chat →
chat reads `breakfasts.md` and suggests one (factoring variety/macros).

### State / prompt edits
- New `state/breakfasts.md`.
- `state/preferences.md` "Week shape defaults" → note breakfast is a separate
  rotating set provisioned weekly (no longer strictly "dinners only").
- `prompts/chat.md` → handle 「今天早餐吃啥」 (read set) + capture breakfast-set edits.

---

## Feature C — Craving deck (ritual Touchpoint 1)

### What changes
Touchpoint 1 stops leading with "what's in your fridge?" and instead presents a
**numbered deck of 8 candidate dishes**. Fridge inventory is still welcome — just
an *optional mention* in the reply, not the lead question. Two-touchpoint rule
preserved: **TP1 = deck**, **TP2 = full proposal** (unchanged from today).

### Deck composition (target 8)
| Bucket | Count | Source |
|---|---|---|
| 🔁 banger | 2 | cookbook dishes with 🔥/banger verdicts, not cooked in ~4 weeks (existing rotation logic) |
| 💭 craving | up to 2 | this week's harvested channel + inbox craving lines |
| ✨ new | 3 | dishes NOT in the cookbook / never cooked — 小當家 proposes novel ones fitting prefs (high-protein bias) |
| 🥋 challenge | 1 | the next technique from `state/skills.md` (a `play` dish teaching an un-learned/初試 skill) |

**Fallback** when fewer than 2 cravings are saved this week (keep total = 8):
- 0 cravings → backfill **+1 banger + 1 new** (→ 3 bangers + 4 new + 1 challenge).
- 1 craving → backfill **+1 new** (favor novelty per Mike's lean).

First-ever / thin-history run: no bangers available → lean entirely into new +
challenge to reach 8.

### Card line format
```
{n}. {bucket emoji} {菜名} · {mode} · ~{min}分 · {P}P/{cal}kcal — {one-line hook}
```
New-dish macros are estimated on the fly for the deck (not yet in the cookbook).

### Interaction (Discord mode)
小當家 posts the deck as the TP1 reply, then **stops**. Mike/gf reply in free text:
> 「1 4 6 想吃 · 3不要 · 還有雞胸要用掉」

小當家 then: builds the week from the 👍 picks → fills remaining dinner slots
(default 6; mix 3 fast + 1 batch + 2 play) from staples/rotation honoring the
high-protein lean → **TP2 = the full proposal** as today. Apply tweaks, lock on
approval.

### Hard rules carried over
- Allergies are absolute — an allergen dish **never** enters the deck.
- Dislikes avoided unless explicitly requested.
- No-repeat: don't deck a dish from the last 2 weeks unless it's a requested banger.

### State / prompt edits
- `.claude/skills/plan-week/SKILL.md` Step 3 rewritten as the craving deck; Step 5
  reads the picks; Steps 6–7 carry the macro + breakfast changes above.

---

## Files

**New**
- `state/breakfasts.md` — the breakfast rotation set.

**Edited**
- `.claude/skills/plan-week/SKILL.md` — Step 3 (craving deck), recipe + summary
  formats (macro line), Step 6 (Breakfast shopping group), Step 7 (estimate+store
  macros; reconcile breakfast inbox edits; seed breakfasts if absent).
- `state/preferences.md` — nutrition defaults + breakfast week-shape note.
- `prompts/chat.md` — 「今天早餐吃啥」 query + capture breakfast-set edits.
- `state/cookbook/*.md` — one-time macro backfill.

(No `brain.py`, `nudge.py`, or new launchd jobs — this is ritual/chat/state only.)

## Verification (per "verify via real use")

- **Deck:** run a ritual → TP1 shows 8 cards in the right blend (test the 0/1
  craving fallback), each with a macro; picks build the week; allergens absent;
  no last-2-weeks repeats.
- **Nutrition:** new recipe cards + summary lines + deck cards all carry plausible
  `~Pg / ~kcal`; spot-check the cookbook backfill.
- **Breakfast:** seed `breakfasts.md`; confirm the weekly list grows a Breakfast
  group; 「今天早餐吃啥」 in chat returns a suggestion; an inbox 「早餐加 X」 is
  reconciled at the next ritual.
- Update `TEST-CHECKLIST.md` with these scenarios.

## Future enhancements

- Macro targets / optimization (protein floor + calorie cap) once display-only
  proves useful.
- Full macros (carbs/fat).
- Deck reaction via Discord emoji reactions instead of text.
- Live breakfast-set editing once chat has a safe write seam.
