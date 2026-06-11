# Alfred — Gemini Video Recipe Extraction — Design

- **Date:** 2026-06-11
- **Status:** Approved design, pending implementation plan
- **Builds on:** the recipe-intake feature (`2026-06-10-alfred-recipe-intake-design.md`) + its
  enrichment (`2026-06-10-alfred-recipe-intake-enrichment-design.md`), both shipped & live.
- **Feature:** Replace the hand-rolled "caption → frames → Whisper" extraction with **Gemini
  watching the video** (free tier) to produce a *comprehensive understanding* of the reel,
  which 小當家 (Claude) then enriches into the teaching card. Gemini is the **extractor**;
  小當家 stays the **enricher**.

## Problem

The frames+Whisper fallback for caption-less videos is a hand-rolled approximation of what a
native video model does in one pass. The spike (2026-06-10) showed why it's weak: even
scene-detected frames can't recover info that's *only* in the caption, and Whisper is slow +
useless on music-only reels. A native video model (Gemini) ingests video frames densely +
audio, fused — strictly better extraction. Gemini's free tier covers this low volume (~a few
reels/week) at $0.

## Spike evidence (verified 2026-06-11, `GEMINI_API_KEY` in `.env`)

- **Gemini `gemini-2.5-flash` extracts the 鹽水雞 reel well.** Fused (video + caption) is the
  richest: structured ingredients from the caption **plus** method/timings the caption lacked
  (醃15分鐘, 外鍋兩杯水, 汆燙3分鐘) **plus** the caption's 小叮嚀 tips. ~21s for the call.
- **Instagram URL-direct FAILS:** `400 Cannot fetch content from the provided URL` — Gemini
  refuses to fetch IG reel URLs → **must download + upload the bytes for Instagram.**
- **YouTube URL-direct WORKS:** Gemini fetches + analyzes a YT URL natively (no download).
- **The "comprehensive understanding" prompt works** — deep, structured, nuanced output.

## Decisions (from brainstorm)

| Question | Decision |
|---|---|
| Run Gemini on every recipe link, or fallback-only? | **Every link** (max comprehensiveness; low volume). Caption-fallback keeps it from hard-breaking. |
| What does Gemini return? | A **comprehensive understanding** — 菜名 / 食材+份量 / 步驟 **plus** technique nuance, 火候/timing/sensory cues, visual observations, "what a chef notices" — not a flat recipe. |
| URL vs download? | **Branch by platform:** YouTube → pass URL directly (no download); Instagram → download (yt-dlp) + upload bytes (Files API). |
| Whisper? | **Dropped.** Gemini subsumes audio. The frames fallback stays visual-only. |
| Frames fallback? | **Kept + upgraded** to scene-detection + frame cap (keyless safety net). |

## Architecture

Same seam as today's deterministic caption pre-fetch — the listener does extraction *before*
the brain so 小當家 enriches the exact dropped recipe (the history-anchoring fix stays intact).

### Source routing — Gemini is ONLY for video links

The listener's `extract_recipe_url` regex matches **only Instagram (reel/p/tv) and YouTube
(watch/shorts/youtu.be)** links. Routing is by source type; Gemini never runs for non-video
sources:

| Dropped source | Handler | Gemini? |
|---|---|---|
| **IG / YouTube video link** | listener pre-fetches via `cmd_gemini` | ✅ yes |
| **Recipe webpage / blog URL** | 小當家 reads it with `WebFetch` (unchanged) | ❌ no |
| **Image / screenshot / PDF** | 小當家 reads it with `Read` (vision, unchanged) | ❌ no |
| **Pasted recipe text** | 小當家 parses the message (unchanged) | ❌ no |
| **Non-recipe link** | normal chat, nothing saved (unchanged) | ❌ no |

A bare webpage URL simply fails `extract_recipe_url` → the listener injects nothing → the brain
falls to its WebFetch door. No download, no Gemini call, no API cost for non-video sources.

### New / changed components

**`scripts/recipe_intake.py` — new `cmd_gemini(url) -> dict`**
- Reads `GEMINI_API_KEY` (via `discord_io.load_env`). **Lazy-imports** `from google import genai`
  *inside* the function, so `caption`/`frames` keep working without the dependency.
- **YouTube** url → `contents=[Part(file_data=FileData(file_uri=url)), PROMPT]` (no download).
- **Instagram** (and other non-YT) → download via the existing yt-dlp path → `client.files.upload`
  → poll until `ACTIVE` → `generate_content([file, PROMPT])`.
- Model `gemini-2.5-flash` with fallback to `gemini-2.0-flash` on model error.
- Returns `{"source": "gemini", "understanding": <text>}` or `{"error": <msg>}`.
- The PROMPT asks for the comprehensive understanding (recipe + nuance + cues + observations),
  in 繁中, **and to quote the source's own ingredient/step text verbatim** so 小當家 can build
  the 📌 原始食譜 block faithfully.

**`scripts/recipe_intake.py` — `frames` upgraded to scene-detection**
- Replace even-spacing with `ffmpeg "select='gt(scene,T)'"` + a hard cap (`MAX_FRAMES`). If
  scene-detection yields too few (< floor) or too many (> cap), adjust threshold / fall back to
  even-spacing so output is always bounded and non-empty. Pure helper `scene_frame_plan` is
  unit-tested; the ffmpeg call is not.

**`scripts/listener.py` — `_inject_recipe_captions` becomes Gemini-first**
- For an IG/YT link: `cmd_gemini(url)` in-process (timeout-guarded) → on any error/timeout,
  fall back to `cmd_caption(url)` → inject whichever succeeded, tagged with its source and the
  same "use only this, don't pull from chat history" guard.
- Add `google-genai` to listener's `# /// script` deps (it imports recipe_intake, whose
  `cmd_gemini` lazy-imports genai at runtime in the listener process).

**`prompts/chat.md` — door #1 note**
- The injected block may now be a Gemini "comprehensive understanding". Instruct 小當家 to build
  the enriched card from it (same enrichment rules), and to lift the verbatim ingredients/steps
  Gemini quoted into the 📌 原始食譜 block. If the injection is a plain caption (Gemini fell
  back), behave as today (thin → frames → screenshot).

**`.env`** — `GEMINI_API_KEY` (present, gitignored).

### Fallback ladder (no hard Gemini dependency)

1. **Gemini** (video [+ caption] fused → comprehensive understanding) — primary
2. **Caption-only** (`yt-dlp`) — Gemini error / timeout / quota / no key
3. **Frames + Claude vision** (scene-detection) — caption thin & Gemini unavailable
4. **Ask for a screenshot** — final

## Data flow

```
link in #小當家的廚房
   listener._inject_recipe_captions:
      YT?  → cmd_gemini(url)         [Gemini fetches URL natively]
      IG?  → download + upload → cmd_gemini   [Gemini watches bytes]
      Gemini ok → inject understanding (+ "use only this") 
      Gemini fail → cmd_caption → inject caption
   brain (chat): 小當家 enriches → teaching card + 📌 verbatim original → save_recipe → post
```

## Error handling

- `cmd_gemini` returns `{"error": ...}` (never raises) on: missing key, upload/processing
  failure, API/quota error, timeout. Listener catches anything else and falls to caption.
- Listener timeout on the Gemini call (~75s) → fall back to caption so a slow Gemini never
  blows the turn.
- yt-dlp download failure (private/walled IG) → `cmd_gemini` returns error → caption fallback →
  (thin) frames → screenshot.

## Scope boundaries (YAGNI)

- **No new brain mode**; reuse the chat door + the deterministic pre-fetch seam.
- **No Whisper.** **No per-recipe cart pre-match** (declined earlier).
- **No video caching/retention** beyond the throwaway download under `.runtime/` and Gemini's
  own 48h file TTL.
- Gemini key is the only new secret; treated like the Discord token (gitignored, never logged).

## Testing

- **Unit (pytest):** `scene_frame_plan` (bounded/non-empty frame plan), the Gemini-vs-caption
  injection formatting + source tagging, platform branch selection (YT vs IG) in `cmd_gemini`'s
  URL classifier.
- **Live (real Discord drops):** Gemini path on a captioned IG reel (richer card than caption
  alone); a YouTube recipe link (URL-direct, no download); forced caption fallback (temporarily
  bad key) → still saves; the frames path. Confirm 📌 original stays verbatim and no
  history-anchoring regression. New checklist items append to section R.

## Future (out of this change)

- Cache Gemini understanding per URL to avoid re-extracting on a re-drop (dedup already prevents
  re-save; this would only save API calls).
- Use Gemini's richer understanding to auto-populate skill/technique notes for the ritual.
