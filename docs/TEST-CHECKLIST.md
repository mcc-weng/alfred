# Alfred (小當家) — Living Test Checklist

Status: ⬜ untested · ✅ passed · ❌ failed · ⏳ partial
Tags: 🤖 = covered by `scripts/selftest.py` (automatable) · 💬 = needs a real Discord message from Mike · 🗓 = needs next week / real shop / multi-week · 🔧 = I can drive from my side

> Updated as the system gets used for real. selftest.py covers the plumbing; the LLM-behaviour + Discord round-trip + real-account fill need the live human-in-Discord run.

---

## A. Main flow — the E2E spine (do in order)
- [ ] A1 💬 `排菜單` with a flexible opener (cravings + text fridge, no photo) → ritual starts
- [ ] A2 🔧 Harvest reads inbox + channel (clean) — *I verify state*
- [ ] A3 💬 Touchpoint 1: asks ONE light inventory/intent question (doesn't demand a photo)
- [ ] A4 💬 Week proposal: 6 dinners, modes (fast/batch/play) + reasoning, **respects constraints** (no eggplant · no coriander/celery/皮蛋 · fish=salmon only)
- [ ] A5 💬 Tweak ("swap 週三" / "只要5天" / "這週不要牛") → adapts
- [ ] A6 🔧 Lock → saves plan + cookbook + skills; posts **summary + shopping (NOT recipes)** to #本週菜單
- [ ] A7 💬 Auto-chain fires: "菜單鎖定!我來看看要買什麼…" + cart proposal appears on its own
- [ ] A8 💬 Asian Pantry permalink → tap → cart pre-fills
- [ ] A9 💬 `裝吧` → approved → fill runs → items in real Woolies cart → "裝好了" ping
- [ ] A10 🔧 Don't pay — I remove the test items + verify cart empty

## B. Ritual start variations
- [ ] B1 💬 Start with a **real fridge photo** (tests the photo→Discord path — never verified)
- [ ] B2 💬 Start with **just cravings** ("想吃辣的、來點新菜")
- [ ] B3 💬 Start with **"隨便你 / surprise me"** → plans from staples + rotation + skills
- [ ] B4 💬 Request an **eating-out day** ("週五外食") → plan skips it
- [ ] B5 💬 **Allergen named in a craving** (a no-go item) → silently substituted/dropped, no extra question

## C. Chat & memory (mid-week)
- [x] C1 ✅ 💬 Verdict ("牛排超讚") → captured to inbox *(passed in testing)*
- [ ] C2 💬 Craving ("下週想吃韓式") → captured
- [ ] C3 💬 Preference change ("我們不太吃豬肝了") → captured (preference)
- [ ] C4 💬 Lesson ("原來脆皮要把皮擦超乾") → captured (lesson) → filed to lessons.md at next ritual
- [ ] C5 💬 Idle chatter ("今晚好累") → NOT captured
- [ ] C6 💬 Cooking question ("雞胸怎麼不柴?") → beginner coaching, reads lessons.md
- [ ] C7 💬 Recipe lookup ("週三煮什麼?") → pulls from plan/cookbook
- [ ] C8 💬 Dish photo (cooked food) → critique (hype + one improvement)
- [ ] C9 💬 Continuity: follow-up depending on prior reply → holds context
- [ ] C10 💬 Idle reset: wait >20 min, new topic → fresh conversation
- [ ] C11 💬 Persona holds: 小當家/中華一番, 繁中, even if messaged in English

## D. Daily nudge
- [x] D1 ✅ 🔧 Morning nudge posts today's full recipe *(passed after fix; re-confirmed live 2026-06-09 — auto-picked 週二 餛飩麵 on a non-Monday)*
- [ ] D2 🔧 Silent on Sunday / no-dinner day
- [x] D3 ✅ 💬 Prep-ahead notes appear (defrost/marinate) when the dish needs them *(verified live 2026-06-10 — 週三 牛排 nudge LED with "現在就要做:牛排回溫40分", repeated it in mise en place, and named the play technique)*

## E. Cart & threshold edge cases
- [ ] E1 💬 Under threshold → proposes top-ups from buffer to reach free delivery
- [ ] E2 💬 Already over threshold → proposes NO top-ups
- [ ] E3 💬 Can't reach threshold → reports the gap honestly, invents nothing
- [ ] E4 💬 Selective approve ("只加醬油就好") → applies only that
- [ ] E5 💬 不用加直接送 → approves without top-ups
- [ ] E6 💬 `裝吧` with no proposed cart → graceful ("先排菜單")
- [ ] E7 💬 Low-confidence product match → flagged for review
- [ ] E8 💬 Re-`裝車` over an existing proposal → re-proposes (overwrites pending.json)
- [x] E9 ✅ 🤖 Asian Pantry permalink resolves to a real pre-filled cart *(selftest)*

## F. Fill & safety
- [x] F1 ✅ 🔧 Awake fill: approval → fill → cart populated → live subtotal+fee → ping *(passed in testing)*
- [ ] F2 🔧 Self-heal: partial-fail stays `approved` + retries (I can simulate)
- [ ] F3 🔧 Login-expired → pings "登入一下", stays approved (I can simulate)
- [x] F4 ✅ 🤖 Idempotency: re-run on a non-approved cart → "nothing to fill", no double *(selftest)*
- [ ] F5 🗓 Set-absolute: re-POST same SKU → qty stays N, not 2N (needs real cart — next-week acceptance)
- [ ] F6 🔧 Never checkout — always stops at the cart, never pays
- [x] F7 ✅ 🤖 `.env` not readable by chat brain (Grep dropped, Read denied) *(selftest)*

## G. Daemon mechanics
- [ ] G1 💬 Debounce: 2 rapid messages → ONE combined reply
- [ ] G2 💬 Backfill: message while Mac asleep → late reply on wake (never lost)
- [ ] G3 💬 Brain error → graceful apology, daemon survives
- [ ] G4 💬 Two people: gf's messages + cravings handled alongside Mike's
- [ ] G5 💬 Long recipe (>2000 chars) splits into multiple messages cleanly
- [ ] G6 🔧 Sunday 4pm reminder nudge fires (ritual prompt)
- [x] G7 ✅ 🔧 Single-instance guard: stray `uv run listener.py` bails (flock on `.runtime/listener.lock`), live daemon undisturbed, holder PID preserved *(built + verified live 2026-06-09)*

## R. Recipe intake (v3 — drop a recipe → enriched cookbook card + queued craving)
**Doors (each → enriched 繁中 card saved + craving queued):**
- [x] R1 ✅ 💬 **IG/YT video link** → listener pre-fetches (now via Gemini — see Gemini block) → card saved *(live 2026-06-11 家常鹽水雞 · 2026-06-12 蔥香雞腿)*
- [ ] R2 💬 **Recipe webpage URL** → WebFetch reads the page → card saved
- [ ] R3 💬 **Screenshot / image / PDF** → Read (vision) → card saved
- [ ] R4 💬 **Pasted recipe text** → parsed in place → card saved
- [ ] R5 💬 **Non-recipe link** (news / funny reel) → normal chat, **nothing saved** (negative case)
- [ ] R6 💬 **Thin / no-caption video** → Gemini handles most; if Gemini is unavailable → frames fallback (scene-detection + vision); if all fails → asks for a screenshot / dish name

**Card quality (the enrichment):**
- [x] R7 ✅ 💬 **Scaled to 2人份**, original serving count shown; awkward fractions flagged, no "0.5 顆蛋" *(live 2026-06-11 — 原1支雞腿 → 2支)*
- [x] R8 ✅ 💬 **Simple dish → inline tips only, NO section boxes** *(live 2026-06-11)*
- [ ] R9 💬 **Complex/technique dish** (fry/sear/ferment/multi-component) → `🔪備料`/`⚠️新手翻車`/`🔥主廚秘訣`/`✅怎麼知道完成了` sections appear, no inline↔section duplication *(headless-verified 炸雞 2026-06-10; live pending)*
- [x] R10 ✅ 💬 **Pantry-aware** — staples (芝麻香油/薑/蒜…) tagged "(pantry 已有)" from `staples.md` *(live 2026-06-11)*
- [ ] R11 💬 **Dislike flagged** — recipe with 香菜/芹菜/皮蛋/豬肉 → `💡 建議` raises a swap/ask, **source unchanged**

**Faithfulness + the bugs we fixed:**
- [x] R12 ✅ 💬 **📌 原始食譜 verbatim block always present**; all 小當家 additions marked 🔥/⚠️/💡 *(live 2026-06-11)*
- [x] R13 ✅ 💬 **Discord reply includes the full 📌 block** (mirrors the saved file, not trimmed) *(bug fixed + live 2026-06-11)*
- [x] R14 ✅ 💬 **No history-anchoring** — a recipe dropped after a *different* one in recent history saves the NEW dish, not the old *(bug fixed + live 2026-06-11 — 鹽水雞 dropped after milk-mochi context)*
- [x] R15 ✅ 💬 **No process narration** — clean card, never "已存入…/等待批准傳送" *(bug fixed + live 2026-06-11)*
- [ ] R16 💬 **Dedup** — re-drop a recipe already in cookbook → replies "之前存過了", no duplicate file/craving
- [x] R17 ✅ 🤖 Unit tests: URL detect + caption/understanding injection (listener), slugify + cookbook/craving format (save_recipe), is_thin/frame_timestamps/extract_fields/is_youtube/_gemini_prompt/scene_filter (recipe_intake) *(pytest, 74)*
- [ ] R18 🗓 Queued recipe craving surfaces in the next Sunday ritual's harvest (inbox→ritual)

**Gemini video extraction (v3.3 — listener pre-fetches via Gemini, free tier; `GEMINI_API_KEY` in `.env`):**
- [x] G1 ✅ 💬 **IG reel → Gemini watches video + fuses caption** → card richer than caption alone (timing/火候/技巧 cues Gemini saw in the video) *(live-verified 2026-06-12 — 蔥香雞腿)*
- [ ] G2 💬 **YouTube link → Gemini URL-direct** (no download) — confirm no `g_*` dir under `.runtime/recipe_frames/` for it
- [x] G3 ✅ 💬 **Understanding distilled, not dumped** — focused card per the depth ladder, not the whole Gemini blob *(live 2026-06-12 — 755-char card from a long understanding)*
- [ ] G4 💬 **Caption fallback** — Gemini down / no key / quota → still saves via caption-only, no crash *(headless-verified; live pending)*
- [x] G5 ✅ 💬 **Heredoc save** — `save_recipe.py` runs via `uv run … <<'CARD'` (not `… |` pipe); **no "權限待批准" denial** *(bug fixed + verified 2026-06-12)*
- [x] G6 ✅ 💬 **240s enrichment budget** — a rich understanding enriches without the 180s timeout *(verified 2026-06-12 — 106s headless)*
- [ ] G7 💬 **Routing: only IG/YT links hit Gemini** — webpage→WebFetch, image→Read, text→parse; confirm no download/API call for a blog URL
- [ ] G8 🗓 **Ritual posts via input-redirect** (`uv run discord_io.py post … < /tmp/msg.md`, not `cat … |`) — Sunday #本週菜單 post not blocked by the tightened allowlist *(fix shipped 2026-06-12; live-verify next ritual)*

## H. Deferred — next week / multi-week
- [ ] H1 🗓 Dark-wake fill (approve → close lid → fills on 9am wake)
- [ ] H2 🗓 iyf 9am contention → fill defers while coin collector runs (check fill.log)
- [ ] H3 🗓 Mac off → fill on next boot
- [ ] H4 🗓 Real pay on a real shop (the trial)
- [ ] H5 🗓 No-repeat: next week's plan avoids this week's dishes
- [ ] H6 🗓 Skill progression: a play technique advances 已排入→初試→熟練 after cook+verdict
- [ ] H7 🗓 Inbox→ritual: this week's captures show up in next Sunday's plan
- [ ] H8 🗓 Woolies item out of stock / substitution at fill or checkout
- [ ] H9 🗓 Fulfillment switch delivery-trial → pickup (threshold $75→$50, trial cancel)

## Plumbing self-test (run anytime — `scripts/selftest.py` automates the 🤖 items)
- [x] P1 ✅ 🤖 `uv run --with pytest --with discord.py pytest tests/ -v` → 74 passed
- [x] P2 ✅ 🤖 `uv run scripts/selftest.py` → 7/7 (woolies+AP search live, AP permalink, cart_logic, capture, fill-guard, .env-deny)

---

## Dry-run findings (2026-06-09) — found & fixed
The first live Discord dry run surfaced 4 issues (all in plumbing, not the brain — the
ritual/cart/nudge logic passed). Recorded here so they're not re-discovered:
1. **Duplicate daemon** — a stray `uv run listener.py` overlapped launchd's copy → every
   message processed twice. **Fixed:** flock single-instance guard (G7), verified live.
2. **Cart output formatting** — markdown tables don't render in Discord; redundant "小當家:"
   prefix; process narration ("Finalize 完成…", "pending.json 已寫入"); mixed 中/英 jargon.
   **Fixed:** `prompts/cart.md` rewritten to line-based all-繁中 report.
3. **Approval reply leaked internals** — told Mike to run `bash scripts/fill_runner.sh`
   manually. **Fixed:** `prompts/cart.md` approval rule — short warm confirm, daemon auto-fills.
4. **Fill blocked by single-session** — an active interactive Claude session blocks the
   fill brain's claude-in-chrome; it correctly fell back + suppressed a false "登入過期".
   **Not a bug** — works at dark-wake / session-free moment. Stays manual (A9/F1).

## What's automated vs not (honest boundary)
- **🤖 Automated (`pytest` + `selftest.py`):** all pure logic, both live search APIs, AP permalink resolution, the fill guard, `.env` hardening, message-splitting. Run these anytime — they have zero side effects.
- **🔧 I can drive from my side:** the actual fill (touches the real cart — done sparingly, cleaned up), the nudge, simulated fail/login-expired paths.
- **💬 Needs you in Discord:** anything through the live daemon — the ritual conversation, auto-chain in-channel, debounce/backfill, two-person flow, dish-photo critique. Can't be auto-looped (need real messages + side effects).
- **🗓 Needs next week:** dark-wake, off-state, 9am contention, real pay, multi-week (no-repeat, skill progression, inbox→ritual reconciliation).
