# Alfred v2 — 雙購物車 (Two-Cart Automation)

**Date:** 2026-06-08
**Status:** Spiked & validated — ready for implementation plan
**Decisions locked:** Approach A (two carts) · top-ups propose-first, never
auto-added · **two-tool architecture** (autonomous matching + interactive
Woolies push via Claude-in-Chrome + Asian Pantry permalink — Playwright dropped)
· Woolworths fulfillment is **two-phase**:
- **Phase 1 (weeks 1–4):** Delivery Unlimited **free 30-day trial** — door
  delivery, optimizer targets $75. A/B test period.
- **Phase 2 (default destination):** **Direct to Boot pickup** — $0 forever,
  $50 min, Monday windows (dodges the $2 Sunday surcharge). Woolies threshold
  optimization disappears; optimizer becomes Asian-Pantry-only ($130).
- **Decision point ~day 25:** cancel the trial before it charges ($59.50 yr 1 /
  $119 ongoing) unless Mike actively chooses to keep it. 小當家's cart report
  shows trial-day count during Phase 1; cancel-reminder task logged when the
  trial starts. Config flag: `"woolies_fulfillment": "delivery-trial" | "pickup"`.

**Context:** v1/v1.5 shipped & live. Mike pulled v2 forward ahead of the original
3-week gate (owner's call). Spikes run 2026-06-08 — see "Spike results" below;
they reshaped the architecture from headless-Playwright to Claude-in-Chrome.

## Spike results (2026-06-08) — what reshaped this design

- **Woolworths blocks headless browsers** (Akamai "Access Denied"). Headless
  Playwright is dead on arrival → **dropped**.
- **Claude-in-Chrome drives Mike's REAL Chrome → beats Akamai trivially** (it's
  a real user session, not a robot). Verified end-to-end against the live site:
  - ✅ Logged in as Mike (`/apis/ui/Shopper` → 200, header "Hi, Mike"). **Login
    needs ZERO automation** — it's his normal browser; persists for weeks.
  - ✅ Product search API returns clean JSON (name/SKU/price/pack/availability).
  - ✅ Add to cart: `POST /apis/ui/Trolley/Items {stockcode, quantity, source}`.
  - ✅ Remove / set qty: same endpoint with `quantity:0` (or N).
  - ✅ Live totals readable: `GET /apis/ui/Trolley` → `Totals.SubTotal` +
    `DeliveryFee` → **threshold/free-delivery status is EXACT, not estimated.**
  - Test item added then removed; cart left empty.
- **Woolworths search API also works via plain HTTP (urllib), unauthenticated**
  → product *matching* can run unattended in the Sunday daemon; only the
  authenticated *cart-push* needs the real browser.
- **Asian Pantry = Shopify.** `products.json` ✅, `search/suggest.json` ✅
  (good staple coverage: 地瓜粉/樹薯粉/豆瓣醬/麻油/米酒/餛飩/5kg米), **cart
  permalink `/cart/<variant>:<qty>` honored** (verified via `cart.js`). Just a
  URL → fully phone-friendly, zero account risk.
- ⚠️ Side-finding: `IsWowRewardsCardRegistered:false` — Mike's Everyday Rewards
  may not be linked to the online account (he should check, to earn points).

## Architecture — two tools, split by what each half needs

The work splits into **thinking** (autonomous, in Discord) and **cart-push**
(authenticated, per-store).

### Half 1 — Matching & optimization (autonomous, Sunday daemon)
Runs inside a new `cart` brain mode spawned by the listener; no browser.
- `scripts/woolies_search.py` — plain-HTTP wrapper over Woolworths' public
  product search. Ops: `search <term>` → ranked candidates (SKU/name/price/pack/
  available). Used to match every `woolies`-tagged list item to a real SKU.
- `scripts/asianpantry.py` — Shopify catalog client. Ops: `search <term>` →
  candidates (variant_id/title/price/available); `permalink <variant:qty,…>` →
  the cart URL. Matching + the final deliverable link.
- Both consult learned maps first (`state/woolworths.md`, new
  `state/asianpantry.md`); unknowns get best-guess + are flagged; corrections
  update the maps (existing Sunday-harvest loop).
- **Output:** a committed `state/carts/YYYY-MM-DD.json` — the proposed Woolies
  SKU list (with est. subtotal from search prices) + the Asian Pantry permalink +
  fresh-Asian residue. Posted to Discord for approval.

### Half 2 — Cart-push (authenticated)
- **Asian Pantry → permalink.** 小當家 posts the `/cart/…` URL in Discord. Mike
  taps on his phone, checks out. Fully autonomous + couch-friendly. Done.
- **Woolworths → Claude-in-Chrome.** No permalink (not Shopify). An **interactive
  "shopping run"**: Mike at the Mac with Chrome open + a Claude session
  (Claude Code / remote-control) says e.g. "push this week's Woolies cart."
  That session reads `state/carts/<latest>.json` and, via the verified Trolley
  API in his real browser, adds each SKU, then reports the **live** subtotal +
  delivery fee. Mike reviews substitutions in the Woolies UI and taps pay.
  - Driven by an interactive Claude session, NOT the headless daemon (browser
    tools only exist interactively). This is the one Mac-bound step.
  - Captured as a documented procedure (`docs/woolies-push.md`) + a thin helper
    `scripts/woolies_cart.js` (the verified add/read JS) the session pastes/runs,
    so it's repeatable and not improvised each week.

### Threshold optimizer (pure logic, in cart-mode prompt)
- Config `"thresholds": {"woolies": 75, "asianpantry": 130}` (woolies threshold
  ignored once `woolies_fulfillment` = `pickup` → $50 min only).
- Subtotal < threshold → propose top-ups, priority: (a) items flagged 「快用完了」
  in chat since last week, (b) `state/buffer.md` standing candidates (rice, oils,
  米酒, frozen wontons, soy…; humans edit), (c) predictable staples.
- **Propose-only.** Nothing added without a Discord yes. For Woolies the true
  fee is read live during the push, so the optimizer's estimate is reconciled
  against reality before Mike pays.

### Channel split
Ritual Step 6 already tags every shopping-list line `woolies` / `asianpantry` /
`fresh-asian`. fresh-asian (豬血-tier: same-day fresh / not online) → human Box
Hill line, clearly marked. Split knowledge accumulates in the two maps.

### Daemon wiring
- New brain mode `cart`: allowedTools = Read/Glob/Grep, Write, Edit,
  `Bash(uv run scripts/woolies_search.py:*)`,
  `Bash(uv run scripts/asianpantry.py:*)`. (Write/Edit unscopeable by tooling;
  restriction to state maps + `state/carts/` by prompt contract — same trust
  level as ritual mode.) Timeout 900s. **No browser in this mode** — it only
  matches/optimizes/proposes and writes the cart JSON.
- Trigger: ritual mode offers it at completion; or listener keyword
  (「裝車」/「裝購物車」/"fill the carts").

## Risk posture

- **Cart, never checkout** — both channels, non-negotiable. Money needs a thumb.
- No bot-detection arms race: Woolies push is Mike's real logged-in browser,
  human-paced, weekly. No headless automation, no stored Woolies password, no
  persistent bot profile.
- Asian Pantry: permalink = just a URL; zero account risk.
- Degraded mode: if search APIs change, cart mode still posts the v1-style list
  (degraded beats broken — dinner never blocks on automation).
- `.env` now holds Woolworths creds (Mike's choice). Harden: project settings
  **deny brain `Read` on `.env`**; only scripts read it. Creds are NOT used for
  login (real-browser session handles that) — kept only as a convenience/fallback.
- Secrets in gitignored `.runtime/` + `.env`; token hygiene unchanged.

## Open spike (non-blocking, do during build)
- Confirm `woolies_search.py` plain-HTTP search stays unblocked over repeated
  weekly use (Akamai may rate-limit datacenter IPs). Fallback if it flags:
  do matching via Claude-in-Chrome too (same interactive session), OR cache/
  throttle. Low risk at weekly volume.

## Human tasks (Mike)
1. Start the Delivery Unlimited free 30-day trial; log the cancel-by date.
2. Check Everyday Rewards is linked to the online account (earn points).

## Success criteria (3 weeks after launch)
1. Sunday thinking is autonomous; Mike's shopping effort = approve in Discord +
   tap Asian Pantry link + a ≤2-min Woolies push run.
2. ≥90% of items matched to correct products by week 3 (maps warmed).
3. $0 delivery fees on both channels in normal weeks (read live for Woolies).
4. 亞超 in-person trips reduced to fresh-only or zero.
5. Zero accidental checkouts/charges (structurally impossible — no checkout code).

## Out of scope
Auto-checkout (never) · price/specials hunting · additional channels
(KFL/HungryPanda/Coles — revisit only if Asian Pantry coverage proves poor) ·
delivery-slot booking · returns/refunds · multi-store route planning · any
headless browser automation against Woolworths (proven blocked).
