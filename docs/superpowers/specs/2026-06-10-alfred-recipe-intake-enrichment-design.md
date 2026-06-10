# Alfred Recipe Intake — Enrichment Design

- **Date:** 2026-06-10
- **Status:** Approved design, pending implementation plan
- **Builds on:** `docs/superpowers/specs/2026-06-10-alfred-recipe-intake-design.md` (the base intake feature, shipped + live-verified earlier today)
- **Feature:** When 小當家 saves an external recipe, present it in his own teaching voice — inline tips, scaled servings, preference-aware suggestions, and on-demand rich sections — **without ever altering the source recipe.**

## Problem

The base recipe-intake feature extracts a faithful but plain 繁中 card (just 食材 + 步驟). Mike wants 小當家 to add his value on top — the same teaching richness as the ritual recipes (sensory cues, beginner traps, chef secrets, doneness checks), scaled to the household, with suggestions drawn from their tastes — **while keeping the original source recipe exactly intact** (his repeated, load-bearing constraint: "use the exact recipe, don't alter the original").

The tension: enrich and personalize, yet guarantee provenance. The whole design is the resolution of that tension.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Card layout | **Inline-hybrid** — the original method *is* the body's steps; 小當家's tips sit indented **right beneath the step they're about**; the verbatim source recipe is preserved as a `📌 原始食譜` block at the bottom. |
| Why not side-by-side columns | Discord/markdown can't do real columns, and the house rule bans markdown tables in Discord output. "At the side" → "indented under each step." |
| Servings | **Scale to 2** (household default), and **always show the original serving count** so the scaling is transparent. Batch/freezer recipes are kept at their original yield with a note. |
| Suggestions | 小當家 reads `state/preferences.md`, `state/staples.md`, `state/lessons.md` and adds a `💡 建議` line **only when genuinely useful** — never filler, never folded into the recipe, always clearly his and optional. |
| Rich sections (備料 / ⚠️新手翻車 / 🔥主廚秘訣 / ✅怎麼知道完成了) | Appear **on-demand**: only when the dish is complex enough AND the content is **whole-dish** (not tied to one step). No duplication with inline tips. Depth scales with the dish. |

## The faithfulness guarantee (the core invariant)

A saved card has two zones, and the rule is absolute:

1. **The body** (食材 + 步驟 + tips + sections) — the original *method*, lightly cleaned for clarity, with **quantities scaled** to the target servings. 小當家's additions live here but are **always visually marked** (`🔥` tip, `⚠️` trap, `💡` suggestion, indentation) so the reader can always tell source from commentary. 小當家 may reword a step for clarity and weave in sensory cues, but **never changes which ingredients are used or the substance of the method.**
2. **`📌 原始食譜`** — the source recipe **verbatim and unaltered, at its original servings/quantities.** This is the untouched ground truth. It is always present.

If the source is non-Chinese, the body is in 繁中 (translated method); the `📌` block is a **faithful 繁中 rendering of the source** — translated but with ingredients, quantities, and steps unchanged. (The cookbook is 繁中 throughout; only the ritual's Woolworths list stays English, which this flow does not touch.)

## Architecture

**This is a prompt change only — no code change.** The mechanism already exists:
- `save_recipe.py` takes the recipe body markdown on stdin and wraps it with `# {title}`, a `**Source:**` line (the link), and `## Verdicts`. The richer card is just richer body markdown the brain composes — `save_recipe.py` is unchanged.
- Chat mode already has `Read`/`Glob`, so it can read `preferences.md`, `staples.md`, and `lessons.md` for tips and suggestions. No tool change.
- The Discord reply is the card (already the case). Long cards are chunked by the existing `split_message`.

So the entire change is rewriting the **「料理擷取」 section of `prompts/chat.md`** to specify: the inline-hybrid structure, scaling, suggestion sourcing, on-demand sections, and the faithfulness invariant + verbatim `📌` block.

### Canonical card template (what 小當家 produces as the save_recipe body)

`save_recipe.py` prepends `# {title}` and appends the `**Source:**` + `## Verdicts` lines, so the brain pipes everything between:

```
{份量(scaled)} · 原{orig}人份 · 約{time}

**Ingredients:**
- {scaled 食材, 含份量}
  🔥 {食材相關 tip — 只在有用時}

【備料(開火前完成)】              ← only when there is real mise-en-place
- {prep items}

**Steps:**
1. {原始方法第一步,忠實}
   🔥 {step-specific 線索/秘訣 — only where it earns it}
2. {原始方法第二步}
   ⚠️ {step-specific 雷點 if needed}

⚠️ 新手最容易翻車:{1–2 highest-stakes mistakes}    ← on-demand, complex dishes
🔥 主廚秘訣:{cross-cutting secrets not tied to one step}  ← on-demand
✅ 怎麼知道完成了:{doneness cues}                  ← on-demand, only if non-obvious

💡 建議:{preference/staples/lessons-based, only when useful}

────────────
📌 原始食譜(來源原文,未改動 · 原{orig}人份)
{source's exact 食材 + 步驟, faithful, original servings}
```

**Depth ladder (the discipline that keeps simple cards clean):**
- *Simple dish* (e.g. a 2-step dessert soup) → `**Ingredients:**` + `**Steps:**` with 1–2 inline tips + maybe one `💡 建議` + the `📌` block. **No** 備料/翻車/秘訣/完成 headers — they'd be padding.
- *Complex / play dish* (e.g. a steak) → the full spread: 備料 block, steps with inline cues, the 1–2 biggest `⚠️ 新手翻車`, cross-cutting `🔥 主廚秘訣`, `✅ 怎麼知道完成了` — plus the `📌` block.

The prompt must instruct 小當家 to **annotate selectively** (a sharp tip where it matters, not a comment on every line) and to **promote a tip to a section only when it's whole-dish, never duplicating an inline tip.**

### Worked example — simple dish (milk-mochi soup)

```
2人份 · 原2人份 · 約15分

**Ingredients:** 黑糖30g · 水300g · 薑3-4片 ｜ 牛奶300g · 地瓜粉30g · 糖20g
  🔥 薑拍裂再下,薑香更出;愛甜的話黑糖可加到40g

**Steps:**
1. 甜湯材料煮沸,煮到黑糖完全融化
   🔥 鍋邊冒小泡就夠,別煮過頭
2. 另鍋下麻糬材料,小火持續攪拌至濃稠
   🔥 一定要小火!大火10秒就結底;地瓜粉先和牛奶拌勻才不結塊

💡 建議:沒地瓜粉 → 太白粉1:1代

────────────
📌 原始食譜(來源原文,未改動 · 原2人份)
甜湯:黑糖30g/水300g/薑3-4片 ｜ 麻糬:牛奶300g/地瓜粉30g/糖20g
做法:1. 甜湯煮沸至黑糖融化 2. 麻糬小火攪拌至濃稠
```

## Scope boundaries (YAGNI)

- **No code changes.** `save_recipe.py` and `recipe_intake.py` are untouched; the body is just richer markdown. (If a `--orig-servings` metadata flag turns out to help the ritual later, that's a future add — not in this change.)
- **No new state files.** Suggestions read existing `preferences.md` / `staples.md` / `lessons.md`.
- **No auto-capture of new preferences.** "You love sweeter" only surfaces once that preference exists in `preferences.md` (via the existing chat/ritual capture path). 小當家 suggests from whatever is currently known.
- **Does not touch** the ritual, the Woolworths list, or the cart flow.

## Edge cases

- **Original servings unmarked** → state the assumption (use the source's implied yield; if truly unknown, note 「份量未標,以原方為準」 and don't fabricate a scale factor).
- **Scaling that doesn't halve cleanly** (1 egg, "a pinch", baking ratios) → 小當家 notes the awkward item rather than writing "0.5 顆蛋"; round sensibly and flag it.
- **Very long complex recipe** → the reply is chunked by `split_message`; keep the card focused (the depth ladder prevents bloat).
- **Non-Chinese source** → body in 繁中; `📌` block is a faithful 繁中 rendering (ingredients/quantities/steps unchanged).
- **Thin/sloppy source** (recovered only from frames) → still produce the card honestly; if a quantity is genuinely unknown, mark it 「(影片未標,自行斟酌)」 rather than inventing it. The `📌` block reflects what the source actually gave.

## Testing

Per `alfred-verify-via-real-use` — verify through real Discord use, no harness:
- A **simple** recipe (milk-mochi or similar) → inline tips only, `📌` block present, **no** empty 備料/秘訣 headers, scaled to 2 with original servings shown.
- A **complex** recipe (a steak/braise/fried dish) → the rich sections appear and hold whole-dish teaching, with inline cues at steps, no duplication.
- A recipe whose **original servings ≠ 2** → quantities scaled correctly, original count shown, `📌` block at original yield.
- A recipe touching a **known preference/dislike** (e.g. a coriander-heavy dish) → 小當家 flags it / suggests a swap in `💡 建議`, source unchanged.
- Confirm the `📌` original block is **always** present and matches the source.

## Refinements (locked during inline build + eval loop — 2026-06-10)

Tuned by running 3 real recipes (trivial milk-mochi, simple-technique 番茄炒蛋, complex
韓式炸雞) through the chat brain headlessly and inspecting the cards. Final decisions,
now reflected in `prompts/chat.md` (commit `5a0f421`):

- **Labels are 繁中** (`**食材**` / `**步驟**`), matching the ritual recipe voice — **not**
  the English `**Ingredients:**` / `**Steps:**` the original draft specified. (Nothing
  parses these labels; confirmed by grep.)
- **"Middle" transformation dial:** 小當家 **preserves the source's step backbone — no
  adding, splitting, or merging numbered steps** (a too-dense source step may get
  sub-bullets *under* that step, never a new numbered step). Rich teaching rides as
  indented inline annotations; the body's step count mirrors the source.
- **Depth ladder sharpened:** a dish with no real technique (stir, boil) gets **食材 +
  步驟 + inline tips and NO section boxes at all**. Only technique-heavy dishes (fry, sear,
  ferment, multi-component) promote `🔪 備料` / `⚠️ 新手最容易翻車` / `🔥 主廚秘訣` /
  `✅ 怎麼知道完成了`. A complex-dish `⚠️` recap that echoes inline cautions is fine (matches
  the ritual), but simple dishes are never padded with empty section headers.

## Future (out of this change)

- A `--orig-servings` (and/or `--scaled-servings`) metadata flag on `save_recipe.py` if the ritual later wants to re-scale cookbook recipes programmatically.
- Capturing a structured sweetness/spice-level preference so suggestions get sharper.
