# Alfred v2 — 雙購物車 (Two-Cart, Dark-Wake Autonomous)

**Date:** 2026-06-08
**Status:** Spiked & validated — ready for implementation plan
**Owner goal:** "We don't touch the laptop." Finish planning with 小當家 in
Discord → both carts get filled → pay from the phone. Laptop awake = instant;
asleep = filled on the existing 9am dark-wake; off/bugged = filled on next boot /
retried then escalated.

## Locked decisions

- **Approach:** two carts (Woolworths + Asian Pantry), top-ups propose-first.
- **Fill, not checkout** — money never moves without a human thumb (pay on phone).
- **Woolies cart-fill = a mechanical script** (`woolies_fill`, no AI) driving Mike's
  **real logged-in browser via CDP** — real fingerprint beats Akamai (proven). The
  daemon does the *thinking*; this script does the deterministic *fill*.
- **Asian Pantry = Shopify cart permalink** — 小當家 posts a URL; tap on phone.
- **Autonomy via the iyf dark-wake pattern** (lifted from `~/Projects/iyf-daily-coin`):
  `pmset` wake + launchd + `caffeinate -is` + retry plist + PID-lock + idempotency.
- **No new wake event.** `pmset repeat` allows only ONE recurring wake; iyf owns
  the 9am slot. 小當家's fill **piggybacks** on that existing 9am dark-wake +
  a 30-min retry. Instant when the Mac is already awake.
- **Woolworths fulfillment is two-phase:**
  - **Phase 1 (weeks 1–4):** Delivery Unlimited **free 30-day trial** (door
    delivery, optimizer targets $75). Cancel-by task logged when it starts;
    cart report shows trial-day count.
  - **Phase 2 (default):** **Direct to Boot pickup** — $0 forever, $50 min,
    Monday windows (dodge the $2 Sunday surcharge). Woolies threshold games
    disappear; optimizer becomes Asian-Pantry-only ($130). Config flag
    `"woolies_fulfillment": "delivery-trial" | "pickup"`.

**Context:** v1/v1.5 live. Mike pulled v2 forward (owner's call). Spikes
2026-06-08 reshaped the architecture twice: headless-Playwright (Akamai-blocked)
→ Claude-in-Chrome interactive → **dark-wake autonomous** once the iyf pattern
proved a *scheduled headless* run can drive the real logged-in browser.

## Spike results (2026-06-08)

- Woolworths blocks **headless** browsers (Akamai). Headless Playwright dropped.
- Driving Mike's **real logged-in browser** (Claude-in-Chrome / CDP) beats Akamai.
  Verified live against the site:
  - ✅ Logged in as Mike (`GET /apis/ui/Shopper` → 200, header "Hi, Mike").
  - ✅ Search API → clean JSON (name/SKU/price/pack/availability); also works via
    plain unauthenticated HTTP → matching can run unattended.
  - ✅ Add: `POST /apis/ui/Trolley/Items {stockcode, quantity, source}`.
  - ✅ Remove / set qty: same endpoint, `quantity:0` (or N).
  - ✅ Live totals: `GET /apis/ui/Trolley` → `Totals.SubTotal` + `DeliveryFee` →
    threshold/free-delivery status is **exact, read live**.
  - Test item added then removed; cart left empty.
- **iyf-daily-coin proves the dark-wake pattern works end-to-end** on this Mac:
  `sudo pmset repeat wakeorpoweron MTWRFSU 08:59:00` dark-wakes (lid closed, AC);
  launchd `StartCalendarInterval` 09:00 runs the job; `caffeinate -is -t 3600`
  holds it awake; a `StartInterval 1800` retry plist catches missed runs; PID-lock
  + idempotency prevent races/double-runs. A scheduled headless `claude --print`
  drives the real logged-in browser (even past a slider captcha). ~75% of that
  infra is site-agnostic and liftable.
- **Asian Pantry = Shopify:** `products.json` ✅, `search/suggest.json` ✅ (good
  staple coverage: 地瓜粉/樹薯粉/豆瓣醬/麻油/米酒/餛飩/5kg米), cart permalink
  `/cart/<variant>:<qty>` honored (verified via `cart.js`).
- ⚠️ `IsWowRewardsCardRegistered:false` — Everyday Rewards may not be linked to
  the online account (Mike: check, to earn points).

## End-to-end flow

### Sunday (the thinking — autonomous, in Discord)
1. Ritual completes → 小當家:「菜單鎖定!要我去裝購物車嗎?」
2. Mike 「裝」→ `cart` brain mode runs (no browser): matches every `woolies` /
   `asianpantry` list line to a real product via the search scripts; runs the
   threshold optimizer; proposes top-ups if short.
3. 小當家 reports to phone: Woolies items + est. subtotal vs threshold; Asian
   Pantry items + subtotal vs $130 + top-up proposals; fresh-Asian residue
   (豬血-tier → human Box Hill line). Mike approves/declines top-ups.
4. On approval, 小當家 writes **`state/carts/pending.json`** (the Woolies SKU+qty
   list, the Asian Pantry permalink, fulfillment mode, timestamp) and posts the
   **Asian Pantry permalink** (tap on phone → checkout, done).

### The Woolies fill (mechanical, dark-wake aware)
`woolies_fill` reads `pending.json`, connects via CDP to the logged-in browser,
POSTs each SKU to the Trolley API, reads live SubTotal + DeliveryFee, marks the
cart `filled`, and pings 📱「裝好了:$X,運費 $Y。手機結帳」.

| Laptop state | What happens |
|---|---|
| 🟢 **Awake** (Mike home Sun eve) | Daemon triggers the fill immediately → cart filled ~1 min → phone ping. No wake needed. |
| 🟡 **Asleep** | `pending.json` waits → Mac dark-wakes 9am (existing iyf wake) → fill job runs in that window → cart ready ~Mon 9am → phone ping. (Battery: `-s` may re-sleep; retry catches it next genuine wake.) |
| 🔴 **Off** | `wakeorpoweron` may power it on (then fills); if not, `pending.json` survives → fill runs on **next boot** (launchd RunAtLoad + retry). Filled within ~1 min of opening the laptop. Never lost. |
| 🟠 **Bugged / failed** | Cart marked `filled` **only on success** → retry every 30 min on subsequent wakes. Login-expired → 小當家 pings 「開 app 登入一下」→ one-tap → next retry succeeds. After N fails → escalate: post the plain shopping list (degraded beats broken). Crashed run's PID-lock is stolen by the next. |

**Pay:** always the human, on the phone — Woolies app (cart synced) + Asian
Pantry link. No checkout code exists anywhere.

## Architecture (units)

### Autonomous (Sunday daemon — no browser)
- `scripts/woolies_search.py` — plain-HTTP Woolworths product search.
  `search <term>` → ranked candidates (SKU/name/price/pack/available).
- `scripts/asianpantry.py` — Shopify catalog client. `search <term>` → candidates
  (variant_id/title/price/available); `permalink <variant:qty,…>` → cart URL.
- Both consult learned maps first (`state/woolworths.md`, new
  `state/asianpantry.md`); unknowns best-guessed + flagged; corrections update
  the maps via the existing Sunday harvest.
- New `cart` brain mode (listener-spawned): matches/optimizes/proposes, writes
  `state/carts/pending.json`. allowedTools = Read/Glob/Grep, Write, Edit,
  `Bash(uv run scripts/woolies_search.py:*)`, `Bash(uv run scripts/asianpantry.py:*)`.
  (Write/Edit unscopeable by tooling; restricted to state maps + `state/carts/`
  by prompt contract — same trust level as ritual mode.) Timeout 900s.

### The fill (mechanical — drives the real browser)
- `scripts/woolies_fill.py` — connects via CDP to the logged-in Chrome (launches
  it with the persistent logged-in profile + debug port if not running), POSTs
  the `pending.json` SKUs to the Trolley API, reads live totals, writes result +
  marks `filled`, pings Discord via `discord_io.py`. **No AI, no tokens** — the
  matching already happened; this is deterministic.
- `scripts/fill_runner.sh` — the iyf-style wrapper: PID-lock, idempotency guard
  (skip if `pending.json` already `filled`), `caffeinate -is -t`, logging, then
  runs `woolies_fill.py`. Invoked by the daemon (awake path) AND launchd.
- `launchd/com.alfred.fill.plist` — `StartCalendarInterval` 09:00 (rides the iyf
  wake) + a separate `StartInterval 1800` retry plist. No `pmset` change.

### Auth
- **Primary:** persistent logged-in browser profile (Mike logs in once; persists
  weeks). **Fallback:** scripted login from `.env` (`WOOLWORTHS_EMAIL/PASSWORD`),
  iyf-style, attempted only when the session check fails; if it hits a bot-wall,
  escalate to Discord「登入一下」. Login check: `GET /apis/ui/Shopper` == 200.
- Harden: project settings **deny the brain `Read` on `.env`** — only scripts read
  creds; no brain mode can see them. Creds never used for the fingerprint (real
  browser session handles that).

### Threshold optimizer (pure logic, cart-mode prompt)
- Config `"thresholds": {"woolies": 75, "asianpantry": 130}` (woolies ignored once
  `woolies_fulfillment` = `pickup` → $50 min only).
- Subtotal < threshold → propose top-ups, priority: (a) 「快用完了」 flags from chat,
  (b) `state/buffer.md` standing candidates (rice/oils/米酒/frozen wontons/soy…;
  humans edit), (c) predictable staples. **Propose-only.** For Woolies the true
  fee is read **live during the fill** and reported before Mike pays.

### Channel split
Ritual Step 6 tags each list line `woolies` / `asianpantry` / `fresh-asian`.
fresh-asian (豬血-tier: same-day fresh / not online) → human Box Hill line.
Split knowledge accumulates in the two maps.

## Risk posture

- **Fill, never checkout** — both channels. Money needs a phone tap.
- No bot-detection arms race: the fill is Mike's real logged-in browser, weekly,
  human-paced; no stored-password login in the normal path; real fingerprint.
- Asian Pantry permalink = just a URL; zero account risk.
- **Never lost / never double:** `pending.json` persists; idempotency marks
  filled-once; retry drains on any wake; persistent failure → Discord + plain-list
  fallback (degraded beats broken — shopping never blocks).
- Secrets in gitignored `.env` + `.runtime/`; `.env` denied to brains.
- Shares the Mac's 9am wake with iyf but uses a different browser profile → no
  collision; never modifies iyf's `pmset`/launchd.

## Plan B design inputs (pinned during v2a build)
- **Status lifecycle:** cart mode (v2a) writes `pending.json` as `proposed`. Plan B
  must define how it reaches `approved` and which status the fill consumes — esp.
  the no-top-up-needed case (already over threshold), where nothing currently flips
  it. Likely: a follow-up "approve"/"裝吧" handling, or the fill consumes the latest
  `proposed` after Mike's confirmation. Decide in Plan B's first task.
- **finalize before fill:** Plan B should re-run `cart_logic.py finalize` (or trust
  v2a's filled `est_subtotal`/`threshold_status`) and reconcile against the LIVE
  Woolies subtotal+fee read during the fill before reporting "ready to pay".
- v2a delivered (verified 2026-06-08): HTTP matching, AP permalink (resolves to a
  real cart), propose-first optimizer, channel tags, `pending.json` + validator +
  `finalize` CLI, `.env` denied to brains. 38 tests green.

## Integration spike (during build, before wiring launchd)
Confirm the full chain on THIS Mac: write a test `pending.json` → run
`fill_runner.sh` → it connects via CDP to the logged-in browser → adds the SKUs →
reads back subtotal+fee → marks filled. Then confirm it fires in the 9am wake
window once (or simulate via `pmset schedule wake` for a near-future minute).
Red → fall back to the interactive Claude-in-Chrome push (still phone-pay) and
re-scope autonomy.

## Human tasks (Mike)
1. Start the Delivery Unlimited free 30-day trial; note the cancel-by date.
2. Check Everyday Rewards is linked to the online account.
3. One-time: log into Woolworths in the persistent browser profile when prompted.

## Success criteria (3 weeks after launch)
1. Sunday is Discord-only for Mike (approve + tap Asian Pantry link); Woolies cart
   appears on his phone with **no laptop interaction**.
2. ≥90% items matched to correct products by week 3 (maps warmed).
3. $0 delivery fees both channels in normal weeks (Woolies fee read live).
4. 亞超 in-person trips reduced to fresh-only or zero.
5. Zero accidental checkouts/charges (structurally impossible — no checkout code).
6. The fill never silently dies: every failure surfaces in Discord within a day.

## Out of scope
Auto-checkout (never) · price/specials hunting · extra channels
(KFL/HungryPanda/Coles — revisit only if Asian Pantry coverage proves poor) ·
delivery-slot booking · returns/refunds · multi-store routing · a standing
always-on server for true laptop-off autonomy (a later move; Mac-on-wake is the
v2 answer) · any headless-browser automation against Woolworths (proven blocked).
