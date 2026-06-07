# Alfred v2 — 雙購物車 (Two-Cart Automation)

**Date:** 2026-06-08
**Status:** Approved design, pre-spike
**Decisions locked:** Approach A (two carts) · Woolworths via Delivery Unlimited
(optimizer target $75) · top-ups are propose-first, never auto-added.
**Context:** v1/v1.5 shipped and live. Mike pulled v2 forward ahead of the
original 3-week gate — owner's call, recorded.

## Goal

After the Sunday ritual locks, 小當家 fills the Woolworths cart and prepares the
Asian Pantry cart so that the humans' total shopping effort is: approve top-ups
in Discord, tap pay in the Woolies phone app, tap one link and check out at
Asian Pantry. Delivery costs $0 on both channels (Delivery Unlimited ≥$75;
Asian Pantry free shipping ≥$130). No laptop. **Cart, never checkout — money
never moves without a human thumb.**

## The Sunday flow (UX contract)

1. Ritual completes → 小當家 asks in #小當家的廚房:「菜單鎖定!要我去裝購物車嗎?」
2. Human says 「裝」(or "fill the carts") → cart mode runs (~3 min)
3. 小當家 reports per channel:
   - 🛒 Woolies: N items · $subtotal · threshold status vs $75 · substitutions/
     uncertain matches called out explicitly
   - 🥢 Asian Pantry: N items · $subtotal · threshold status vs $130 ·
     top-up proposals if short (「加 米酒x2+麻油 就到免運,要嗎?」)
   - 🏪 Fresh-Asian residue (豬血-tier): listed clearly as the human Box Hill line
4. Human approves/declines top-ups → 小當家 finalizes → posts: Woolies「打開
   app,購物車已就位」+ Asian Pantry cart link
5. Checkout: Woolworths phone app (cart syncs account-wide) + Asian Pantry
   link checkout. Both human-performed, always.

## Architecture

Three new units behind the existing brain/daemon; no new always-on processes.

### 1. `scripts/woolies.py` — Woolworths cart builder
- Headless Playwright with a **persistent browser profile** at
  `.runtime/profiles/woolies/` (gitignored). One-time interactive headed login
  by Mike; only cookies persist. **No passwords stored, ever.**
- Product search: prefer Woolworths' public product-search API (spike 1);
  DOM automation only where API can't (cart-add if needed, spike 3).
- Operations: `search <term>` → candidates JSON · `add <sku> <qty>` ·
  `subtotal` · `cart` (list current cart).
- Matching uses `state/woolworths.md` first; unknowns get best-guess + are
  flagged in the Discord report; corrections update the map (existing loop).

### 2. `scripts/asianpantry.py` — Asian Pantry cart-link builder
- Asian Pantry is expected to be Shopify (spike 4): public `products.json`
  catalog for matching + **cart permalink** (`/cart/<variant>:<qty>,…`) for
  fulfillment. No login, no automation, no bot risk — the deliverable is a URL.
- New learned map: `state/asianpantry.md` (ingredient → product/variant),
  same correction loop as Woolies.
- If spike 4 fails (not Shopify / permalinks blocked): fallback is a
  per-item-linked shopping list; channel stays useful, just less magical.

### 3. Threshold optimizer (pure logic, inside cart mode's brain prompt)
- Config: `"thresholds": {"woolies": 75, "asianpantry": 130}` in config.json.
- If subtotal < threshold: propose top-ups from, in priority order:
  (a) items flagged 「快用完了」 in chat since last week,
  (b) `state/buffer.md` — standing pre-approved-to-PROPOSE candidates
  (rice, oils, 米酒, frozen wontons, soy sauce …; humans edit this file/chat),
  (c) next week's predictable staples.
- **Propose-only.** Nothing is added without a yes in Discord.

### Channel split
The ritual (Step 6) now tags every shopping-list line: `woolies` /
`asianpantry` / `fresh-asian`. fresh-asian = items needing same-day fresh
handling or unavailable online (豬血-tier) → human Box Hill line, clearly
marked in the report. Split knowledge accumulates in the two product maps.

### Cart mode (daemon wiring)
- New brain mode `cart`: allowedTools = Read/Glob/Grep, Write, Edit,
  `Bash(uv run scripts/woolies.py:*)`, `Bash(uv run scripts/asianpantry.py:*)`.
  (Write/Edit cannot be path-scoped by the tool system; restriction to the two
  state maps is enforced by prompt contract — same trust level as ritual mode,
  which already holds broader tools.) Timeout 900s.
- Trigger: listener keyword (「裝車」/「裝購物車」/"fill the carts") OR offered
  automatically by ritual mode at completion. Runs under the existing
  brain_lock; transcript-style replay for the approve-top-ups turn.

## Risk posture

- **Cart, never checkout** — both channels, non-negotiable.
- Woolies bot detection: weekly human-paced cart fills on a persistent profile;
  no scraping sweeps; failure degrades to the v1 posted list (degraded beats
  broken — dinner never blocks on automation).
- Asian Pantry: permalink = just a URL; zero account risk.
- Secrets: cookies only, in gitignored `.runtime/`; token hygiene unchanged.
- Sunday $2 Woolies surcharge exists; optimizer notes it, humans pick slots.

## Spikes — run BEFORE the implementation plan (house rule)

1. Woolworths product search via public API: returns name/price/SKU reliably?
2. Persistent Playwright profile: login survives ≥1 week + daemon restarts?
3. Headless cart-add works AND the cart appears in the Woolies phone app?
4. Asian Pantry: Shopify? `products.json` live? cart permalink honored?
   Stocks the household's actual staples (地瓜粉/黑糖/豆瓣醬/冷凍餛飩/樹薯粉)?
5. Mike: activate Delivery Unlimited (30-day free trial) — human task.

Any red spike reshapes the plan before code is written (the listener/launchd
lesson). Spike 3 red → Approach C fallback for Woolies (links not bots).
Spike 4 red → linked-list fallback for Asian Pantry.

## Success criteria (3 weeks after launch)

1. Sunday human shopping effort ≤5 min (approve + two taps)
2. ≥90% of items matched to correct products by week 3 (maps warmed)
3. $0 delivery fees on both channels in normal weeks
4. 亞超 in-person trips reduced to fresh-only or zero
5. Zero accidental checkouts/charges (must be structurally impossible)

## Out of scope

Auto-checkout (never) · price comparison/specials hunting · additional channels
(KFL/HungryPanda/Coles — revisit only if Asian Pantry coverage proves poor) ·
delivery-slot booking · returns/refunds handling · multi-store route planning.
