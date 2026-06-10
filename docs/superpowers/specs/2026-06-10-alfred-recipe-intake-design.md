# Alfred Recipe Intake — Design

- **Date:** 2026-06-10
- **Status:** Approved design, pending implementation plan
- **Author:** 小當家 + Mike
- **Feature:** Drop any recipe source (video link, webpage, image, file, text) into
  #小當家的廚房 → 小當家 extracts the recipe, saves it to the cookbook, and queues it
  as a craving for the next weekly ritual.

## Problem

Today, when someone pastes an Instagram reel link in #小當家的廚房, 小當家 replies
"Instagram 連結我打不開——要告訴我是什麼料理嗎?或者直接截圖丟過來" (see the 2026-06-10
screenshot). The gap is **tooling, not capability**: chat mode's allowlist is
`Read,Glob,Bash(capture.py)` — no `yt-dlp`, no `WebFetch`, no browser — so the brain
literally cannot open the link. Mike wants to send a video (or any) link and have
小當家 "do its thing": extract the recipe, remember it, and tee it up for next week.

## Spike evidence (verified 2026-06-10 against the real reel `instagram.com/reel/DUNy6_ADXyp/`)

Every load-bearing assumption was tested live before this design was committed
(per the `spike-before-plan` lesson):

1. **Caption fetch works, no auth.** `yt-dlp --skip-download --print "%(description)s"`
   returned the **full recipe** in ~2s — title, bilingual ingredient list (減糖版
   甜湯 + 麻糬), and 2 numbered steps. For recipe reels the caption usually *is* the
   complete recipe.
2. **Video download works, no auth.** `yt-dlp -f mp4/best` downloaded the 5.46 MB clip
   in ~1s with no logged-in browser.
3. **Frame extraction works.** `ffmpeg -vf fps=1/4` produced 8 clean frames.
4. **Vision reads the frames.** `Read` on the frames cleanly picked up the burned-in
   on-screen captions ("攪拌攪拌 / Mix well", "想著一定要來試試看", "新年快樂♥") *and* the
   visual technique. For recipe reels this is **better than audio**, because the recipe
   lives in on-screen text overlays, not the (often music-only) soundtrack.

`ffmpeg` and `yt-dlp` are both already installed on the machine.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| How far down the pipe does one link travel by default? | **Save + queue for ritual** — extract → 繁中 recipe card → write to cookbook → queue a craving in `inbox.md`. (Not auto-cart.) |
| Write behavior when a link lands | **Auto-save, announce, undoable** — do it, then say so; one word undoes it. |
| Accepted sources | **Any format** — video link, webpage, image, file, pasted text. |
| No-caption fallback | **Watch the video itself** — auto frame-extraction + vision; only ask the human if that also comes up empty. |
| Frames when caption is already complete | **Caption-first** — skip the download/frames unless the caption is thin. |

## Architecture

**Expand `chat` mode; do not add a new brain mode.** Chat is already the default door
for any non-ritual/non-cart message, already reads image/file attachments via `Read`
(vision), and already has exactly one controlled write-seam (`capture.py`). A bare URL
or attachment already routes to chat mode through the existing
`listener.py` → debounce → `brain.run_brain("chat", …)` path — no new trigger needed.

**Alternative considered and rejected:** a dedicated `intake` brain mode with its own
regex trigger. Rejected because it needs a reliable "*is this a recipe?*" router at the
daemon/regex layer — precisely the fuzzy judgment an LLM does well and a regex does
badly. It adds surface area and a worse trigger for no benefit.

**Design shape: one back-end, many front-doors.** All sources funnel into the same
normalize → save → queue → announce back-end.

### New components

Two helper scripts, following the existing `capture.py` / `woolies_search.py` pattern
so the brain never touches raw `yt-dlp`/`ffmpeg`/`Write`:

**1. `scripts/recipe_intake.py`** — the extractor. Subcommands:
- `caption <url>` → prints title, uploader, duration, the full caption/description, and
  an `is_thin` hint, via `yt-dlp -j --skip-download`. Fast, no download. This is the
  primary path. (YouTube auto-subtitles are deferred to Future — the frames path covers
  the same caption-less gap without VTT parsing.)
- `frames <url>` → downloads the clip (`yt-dlp -f mp4/best`), samples ~8–12 frames with
  `ffmpeg` into `.runtime/recipe_frames/<id>/`, prints the frame paths for the brain to
  `Read`. Bounded by: max frame count, max download size, and max duration guards (skip
  / warn on oversized long-form video). Internally calls `yt-dlp`/`ffmpeg` via
  subprocess; the brain only needs the wrapper allowlisted.

**2. `scripts/save_recipe.py`** — the controlled write-seam (mirrors `capture.py`'s
narrow, append-only blast radius). Given the normalized recipe (markdown on stdin +
metadata args: title, source url, who shared):
- Writes `state/cookbook/<slug>.md` in the existing cookbook format
  (`# Title` / `tags · time · serves N — saved YYYY-MM-DD` / `**Ingredients:**` /
  `**Steps:**` / `## Verdicts`), plus a `**Source:**` line with the link and sharer.
  Dedupes by slug — if the file exists, it updates rather than duplicating.
- Appends a craving line to `state/inbox.md` that also points at the saved recipe, e.g.
  `- 2026-06-10 [craving] 想做鮮奶麻糬甜湯 — 已存 cookbook/milk-mochi-dessert-soup.md (ball, IG reel)`.
  The ritual (`plan-week/SKILL.md` Step 1) already reads + clears `inbox.md`, so the
  recipe surfaces as a next-week candidate **with no live-plan mutation** — the ritual
  self-heals, consistent with "the plan is just a suggestion."

### Changed components

**`scripts/brain.py` — `mode_args("chat")` / `CHAT_TOOLS`:** add
`Bash(uv run scripts/recipe_intake.py:*)`, `Bash(uv run scripts/save_recipe.py:*)`, and
`WebFetch`. (`Read`, `Glob`, and `Bash(capture.py)` are already present.) The nudge mode
shares `CHAT_TOOLS`; the extra tools are harmless there (nudge never receives links).

**`prompts/chat.md` — new "料理擷取 (recipe intake)" section** instructing the brain to:
- **Detect** when a message carries a recipe to capture — a video/blog URL, an image/
  file attachment, or pasted recipe text that is plausibly a real recipe. A non-recipe
  link or a casual photo is *not* intake → handle as normal chat (existing fridge/dish
  photo behavior preserved).
- **Extract** via the right door (the fallback ladder below).
- **Normalize** to a faithful 繁體中文 recipe card: 標題, 份量, 食材 (with quantities),
  步驟, 時間, 來源. Translate non-Chinese source recipes into 繁中. Flag any conflict with
  `state/preferences.md` (e.g. 豬肉) — surface it, do **not** silently alter the recipe.
- **Auto-save** via `save_recipe.py`, then reply with the card + a warm undoable line
  ("存好了,排進下週候選 ✅ 不要就說一聲"). Signed per house style.

### Fallback ladder (extraction)

1. **Caption** (`recipe_intake.py caption`) — fast, synchronous, usually complete. If it
   contains ingredients + steps, save it and stop here.
2. **Frames + vision** (`recipe_intake.py frames` → `Read`) — only when the caption is
   thin/missing. 小當家 watches the video itself, reading on-screen captions + technique.
3. **Webpage** → `WebFetch`; **image/file** → `Read`; **pasted text** → parse in place.
4. **Ask the human** — only if 1–3 yield nothing usable: ask for the dish name or a
   screenshot (phone-friendly; works for the phone-only household member).

## End-to-end flow

```
message in #小當家的廚房 (link / image / file / text)
        │  listener.py debounce → not ritual/cart trigger
        ▼
   brain.run_brain("chat", …)         [chat.md "料理擷取" section]
        │  is this a recipe to capture?
        ├─ no  → normal chat (unchanged)
        └─ yes → extract (caption → frames → webpage/image/text → ask-human)
                 → normalize to 繁中 recipe card, flag preference conflicts
                 → save_recipe.py:  state/cookbook/<slug>.md  +  inbox.md craving
                 → reply: recipe card + "存好了,排進下週候選 ✅"
                                    │
              (next Sunday) ritual Step 1 reads inbox.md → recipe is a candidate
```

## Scope boundaries (YAGNI for v1)

- **No auto-cart.** Rung 4 (match to Woolies/Asian Pantry SKUs) was explicitly declined.
  The 「裝車」flow stays separate; a saved recipe reaches the cart only through the normal
  ritual → cart path.
- **No Whisper / audio transcription.** Weakest source for recipe reels and needs an
  async/background runner. Out of v1; can be added later as an explicit opt-in.
- **No auth/login flows.** Public download works headlessly; a private/walled reel that
  fails to download falls gracefully to ask-the-human. No scripted IG login (account risk).
- **No live-plan mutation.** Cravings ride `inbox.md` → the ritual; the current week's
  locked plan is never edited mid-week.

## Edge cases

- **Non-recipe link / casual photo** → normal chat, nothing saved.
- **Duplicate dish** (same recipe shared twice) → `save_recipe.py` dedupes by slug.
- **Long-form YouTube** → prefer caption/subtitles; cap frame count + download size so
  the chat turn stays inside its 180s budget. If extraction would blow the budget, fall
  to ask-the-human rather than hang.
- **Private / walled / geo-blocked reel** → download fails → ask the human for a
  screenshot or the dish name.
- **Multiple links in one message** → extract each (or, if that risks the time budget,
  the first and note the rest). Resolve during planning.
- **Caption in English / another language** → translate to 繁中 for the cookbook (the
  Woolworths shopping list stays English, but that only applies in the ritual/cart flow,
  not here).

## Testing

Per the `alfred-verify-via-real-use` lesson — no test harness or sandbox. Verify through
real Discord usage:
- The original milk-mochi reel → saved to cookbook + queued craving + warm reply.
- A caption-less reel → frames path fires, recipe still extracted.
- A recipe blog URL → `WebFetch` path.
- A recipe screenshot image → `Read` path.
- A pasted recipe text → parse path.
- A non-recipe link → normal chat, nothing written.
- Confirm the queued craving appears in the next ritual's harvest.

## Future (explicitly out of v1)

- Whisper audio transcription as an on-demand opt-in for narration-only videos (async,
  modeled on `fill_runner.sh`).
- YouTube auto-subtitle ingestion (`--write-auto-subs` + VTT parsing) for long-form
  cooking videos where the narration carries the recipe.
- Optional "want it this week?" → nudge the current plan instead of only next week's.
- Recipe-intake → cart pre-match (rung 4) once the base loop is proven in real use.
