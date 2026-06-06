# Alfred — Lively Chef Agent (v1: Weekly Cooking Loop)

**Date:** 2026-06-06
**Status:** Approved design, pre-implementation
**Owners:** Mike + gf (household)

## Vision & staging

Alfred is a household **chef agent** — a lively presence both partners chat with:
drop cravings, fridge photos, and feedback anytime; get conversational replies and
scarce, useful proactive nudges. The general-butler ambition (chores, errands,
calendar) remains deferred until the cooking domain proves itself.

Three layers, shipped in stages:

| Layer | What | Stage |
|---|---|---|
| 🧠 Brain | Weekly planning, recipes, state, photo→inventory, Woolies list | v1 |
| 👂 Ears | Always-on listener — chat with Alfred anytime, instant replies | v1.5 |
| 📣 Voice | Proactive nudges (tonight's meal, expiry, ritual reminder) | v1.5 |

- **v1 (this week):** engine + first Sunday ritual (laptop, couch). Recipes, plan,
  and cart-ready list posted to Discord by the Alfred bot. Proves the content is
  good before adding liveliness.
- **v1.5 (next 1–2 weekends):** the live agent — gateway listener daemon +
  proactive crons. The Sunday ritual itself moves into chat; the laptop disappears.
- **v2 (gated):** browser automation fills the Woolworths cart ("cart, don't
  checkout"). Built only after ~2–3 weeks prove planned meals actually get cooked.
- **Later (if earned):** iOS app wraps the engine → other butler domains.

## Users

| Person | Role | Surface |
|---|---|---|
| Mike | Operator — triggers planning, orders groceries, cooks | Claude Code + Discord |
| Gf | Participant — drops cravings, cooks, gives verdicts | Discord only |

Design constraint: **nothing in the during-week experience may depend on Mike's
laptop or Mike being available.** The gf must be able to cook any night from her
phone alone.

## What Alfred is (v1)

Claude Code running in `~/Projects/alfred` — skills + markdown state, git-versioned.
The engine is always Claude Code on Mike's **Max subscription** (headless
`claude -p` for automated invocations) — **zero API credits at every stage**. No
cloud hosting: v1.5's listener and crons run as a launchd daemon on Mike's Mac
(the proven Jinx pattern). Integrations: Discord bot API (bot token), vision
(fridge photo), and in v2 browser automation (Claude-in-Chrome against
Woolworths).

## Planning drivers

All four carry weight, balanced per week:

1. **Cravings & mood** — requests from the Discord channel, plus live input during the ritual
2. **Use up the fridge** — perishables from the photo get planned first
3. **Fitness / nutrition** — default: every dinner anchored on a protein source
   (~30–40 g/serve), whole-food bias. No macro tracking in v1.
4. **Variety / discovery** — no repeats within ~2 weeks; `play` meals push new
   cuisines/techniques

### Effort model: two meal modes

The system separates "low time cost" from "get good at cooking" instead of
compromising every meal:

- **`fast`** — ~30 min weeknight meals. The floor; must survive zero motivation.
- **`batch`** — cook once, eat twice (counts as fast nights downstream).
- **`play`** — 1–2 sessions/week where the goal is learning: new technique or
  cuisine, slightly above current skill, no time pressure.

Default week mix: **3 fast + 1 batch + 1–2 play** (actual dinner count confirmed
each ritual — eating out, leftovers, etc.). Dinners only; lunches out of scope.
No cook-night assignment — meals are listed, nights are organic.

## The weekly ritual (couple ritual, ~10 min, Sunday-ish)

Two-touchpoint rule: Alfred asks for input at most twice (inventory correction,
plan tweaks). No twenty-questions.

1. Either partner snaps the fridge photo → posts it in the Discord channel
   (fallback: paste directly into the Claude Code session)
2. Mike (with gf on the couch): *"alfred, plan the week"*
3. Alfred reads the channel since the last plan: photo, cravings, notes
   ("out of olive oil")
4. Alfred lists what it sees in the fridge → **one-line human correction**
   ("plus tofu + half a cabbage in the crisper")
5. Alfred proposes the complete week in one shot — each dinner tagged
   `fast`/`batch`/`play` + time estimate + one line of reasoning (what it uses up,
   whose craving, protein anchor, what technique it teaches)
6. One round of live tweaks ("swap Tuesday, no fish") → locked
7. Alfred posts to `#meal-plan`, in this order so the channel always opens on the
   current week:
   - **① One message per dinner** — full stove-ready recipe (ingredients + steps,
     scannable on a phone; respect Discord's 2000-char limit, split if needed)
   - **② Cart-ready Woolworths list** — consolidated, de-duped, real product names +
     pack sizes + quantities; staples excluded unless flagged low
   - **③ "The Week"** — day-by-day summary, posted last = always the newest message
8. Mike orders in the Woolworths app (~2 min), picks the delivery/pickup slot

## During the week

- **Cooking a night:** open `#meal-plan` → newest message is the week summary →
  tap up to tonight's recipe → cook from the phone. Recipes are pre-posted at
  planning time precisely so this works without Mike or a laptop.
- **Verdicts (the learning signal):** say it in `#alfred`, any phrasing — *"pad thai
  was a banger, less salt next time"*. No format required; Alfred parses at harvest.
  (Written words beat emoji taps: they carry the *why*, and they work identically
  before and after the live agent ships. Bot-API reactions become readable at v1.5
  and may be added as a bonus signal then.) Verdicts land in the cookbook; bangers
  join the favorites rotation
  (resurface ~monthly), failures don't repeat, gf's tastes get learned too.
- **Cravings/notes anytime:** type into `#alfred`; harvested next ritual.
- **Swaps are free:** plans are suggestions, not contracts. Skipped meals need no
  bookkeeping — unused ingredients appear in next week's photo and get re-planned
  (self-healing via ephemeral inventory).

## State model

| State | Treatment | Location |
|---|---|---|
| Fridge inventory | **Ephemeral** — captured per ritual (photo + correction), used once, discarded. Never a database; cannot drift. | nowhere |
| Pantry staples (assumed always present) | Durable, set once, edited rarely | `state/staples.md` |
| Tastes, dislikes, allergies, nutrition defaults | Durable | `state/preferences.md` |
| Cooked recipes + verdicts | Durable, grows weekly | `state/cookbook/` |
| Past weekly plans (variety window) | Durable | `state/plans/` |
| Woolworths product map ("chicken thigh" → preferred SKU/pack) | Durable, **learned from corrections** | `state/woolworths.md` |

Inventory is deliberately ephemeral while product preferences are deliberately
persistent — opposite treatments, on purpose.

## Discord conventions

Two channels in a small private server, one job each. (The MCP cannot pin or edit
messages — verified — and mobile Discord buries pins anyway, so "latest message in
a quiet channel" is the UX anchor instead of pinning.)

- **`#alfred`** — humans talk here: cravings, notes, fridge photo, verdicts. Read
  by Alfred at planning time only (v1). **It is an inbox, not a live bot** —
  messages are not answered in real time. That friction maturing is the trigger
  for v2/v3 conversational upgrades.
- **`#meal-plan`** — Alfred-only posts: recipes → Woolies list → week summary
  (newest). The plan can never get buried under chat.

### Access: real bot account, from day one

Alfred is a proper Discord **bot application** with its own token — not the
Playwright-based discord-mcp scraping a user session. (That MCP was verified
working 2026-06-06 and remains an emergency fallback; the bot API is simpler and
strictly more capable.) What the bot API gives us:

- **v1 needs only two REST calls** — read channel history (harvest the week's
  cravings/verdicts) and post messages. No daemon required yet.
- Messages visibly come from **Alfred** (own name + avatar).
- History is pull-based → if the v1.5 daemon is ever down, Alfred **backfills on
  wake** and replies late rather than going deaf. Nothing said in `#alfred` is
  ever lost.
- Reactions and pins become available (bonus only — written verdicts stay primary,
  and the two-channel layout stays because mobile Discord buries pins anyway).

### Setup required before the first ritual (~15 min, one-time)

1. Create a private Discord server with `#alfred` + `#meal-plan`; both partners join.
2. Discord Developer Portal → new application **"Alfred"** → create bot, enable the
   message-content intent, copy the token (stored locally, never committed) →
   invite to the server with read/send/pin permissions.
3. Record the two channel IDs in local config.

## The live agent (v1.5): Ears & Voice

A launchd daemon on Mike's Mac (the Jinx pattern). No cloud, no tunnel — the
Discord gateway is an *outbound* websocket.

- **Ears:** on message in `#alfred` → invoke headless Claude Code (`claude -p`,
  Max subscription) with the alfred repo + state → conversational reply
  (*"got it — pad thai queued for next week 👍"*). Mac asleep → gateway reconnects
  on wake, backfills, replies late. Never deaf, never lossy.
- **Voice:** scheduled invocations (launchd) for proactive nudges:
  - *Morning-of:* "Tonight: miso salmon (fast, ~25 min) — take the salmon out."
  - *Expiry:* "That spinach from Sunday is day 5 — use it tonight?" Derived from
    the plan + purchase date, **not** live inventory tracking — the
    ephemeral-inventory decision survives intact.
  - *Ritual:* "Sunday 5pm — fridge photo + plan?"
- **Proactive budget (hard rule):** at most ~1 Alfred-initiated message/day,
  default quieter. Replies may be warm and instant; *initiations* must be scarce
  and useful, or Alfred gets muted and the system dies.
- At v1.5 the Sunday ritual itself moves into `#alfred` (photo posted in chat,
  conversation with live Alfred) — the laptop disappears from the loop.

## Groceries (Woolworths + Everyday Rewards)

- Australia: no Instacart; no public ordering API for Woolworths/Coles.
  Channel = Woolworths online (delivery or Direct to Boot).
- **v1:** Alfred outputs the cart-ready list (real product names, pack-size
  reasoning — recipe "1 brown onion" → sensible purchasable unit). Mike adds to
  cart manually (~2 min) and checks out.
- **v2 ("cart, don't checkout"):** Alfred drives Mike's **already-logged-in** Chrome
  session to fill the cart, then **stops at the review/payment screen**. Mike checks
  substitutions, slot, and total, and taps pay. A human always stays on the money.
  - Auth model: Alfred never sees or stores credentials; it operates the
    authenticated browser session only.
  - Risk stated plainly: site automation may breach Woolworths ToS and trips bot
    detection → account-lockout risk. Mitigation: human-paced, once-weekly, in
    Mike's real browser profile; human completes checkout. Full auto-checkout is
    explicitly rejected.
  - Mismatch corrections feed `state/woolworths.md`, so the cart gets cleaner
    weekly.

## Error handling

- **Photo misses items** → one-line correction catches what matters; worst case a
  mid-week top-up shop.
- **Wrong/stale product names in v1 lists** → list marks uncertain items
  "or equivalent"; corrections persist to the product map.
- **Plan abandoned mid-week** (life happens) → nothing breaks; see self-healing.
- **Discord bot/daemon down** → ritual still runs in-session; plan/recipes posted
  manually as a copy-paste block. Gateway backfill means nothing said in `#alfred`
  is lost while the daemon sleeps (degraded, not broken).

## Success criteria (review after 3 weeks)

1. ≥4 planned dinners/week actually cooked
2. Planning ritual ≤10 min
3. ≥1 gf craving landed in a plan
4. Ordering ≤5 min with the cart-ready list
5. Verdicts being given without nagging (else the feedback UX is wrong)
6. (post-v1.5) Proactive nudges still welcome after 2 weeks — Alfred not muted

If met → build v2 (cart automation). If not → fix the loop, don't add automation.

## Out of scope (v1)

Lunches/breakfasts · cook-night assignment · macro tracking · pantry photo
inventory · price optimization/specials hunting · meal-kit comparisons · any
butler domain beyond cooking · cloud hosting & iOS app (the only infrastructure
is the local launchd daemon at v1.5).
