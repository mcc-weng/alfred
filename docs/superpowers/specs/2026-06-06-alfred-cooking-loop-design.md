# Alfred v1 — Weekly Cooking Loop

**Date:** 2026-06-06
**Status:** Approved design, pre-implementation
**Owners:** Mike + gf (household)

## Vision & staging

Alfred is a household agent. The long-term ambition (general butler: chores, errands,
calendar) is explicitly deferred. We build one tight loop first, live with it, and let
the butler emerge from proven usage.

- **v1 (this spec):** the weekly cooking loop — plan → recipes → cart-ready list.
  Runs immediately, manual grocery ordering.
- **v2 (fast-follow, gated):** browser automation fills the Woolworths cart
  ("cart, don't checkout"). Built only after ~2–3 weeks prove planned meals
  actually get cooked.
- **v3 (someday, if earned):** Discord becomes a live bot → proactive Alfred →
  iOS app wraps the engine → other butler domains.

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
No backend, no hosting. Integrations: Discord MCP (read/post the shared channel),
vision (fridge photo), and in v2 browser automation (Claude-in-Chrome against
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
  (Reactions are invisible to Alfred — verified — so verdicts are words, not emoji
  taps.) Verdicts land in the cookbook; bangers join the favorites rotation
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

### Verified capabilities (checked 2026-06-06 against the live MCP)

discord-mcp is Playwright-based — it drives Discord's web app as a logged-in user
(env: `DISCORD_EMAIL`/`DISCORD_PASSWORD`), not the bot API. Toolset: list
servers/channels, read messages, send message. Weekly cadence keeps that fragility
class acceptable.

- ✅ Connects; reads message content + author + timestamp
- ✅ `attachments` field present in payloads — photo-via-Discord plausible; one live
  test with a real image remains (fallback unchanged: paste photo into the session)
- ❌ Reactions not exposed → verdicts are written messages (see During the week)
- ❌ No pin/edit → two-channel layout (above)

### Setup required before the first ritual

1. Create a private Discord server with `#alfred` + `#meal-plan`; both partners join.
   (The connected account currently only sees a community server — no couple space
   exists yet.)
2. Decide posting identity: Alfred posts as whatever account `DISCORD_EMAIL` belongs
   to. If that's Mike's main, consider a dedicated free "Alfred" account (messages
   visibly from *Alfred*) and invite it to the server.
3. ~~Install Playwright browser for the MCP~~ — done 2026-06-06.

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
- **Discord MCP unavailable** → ritual still runs in-session; plan/recipes posted
  manually as a copy-paste block (degraded but functional).

## Success criteria (review after 3 weeks)

1. ≥4 planned dinners/week actually cooked
2. Planning ritual ≤10 min
3. ≥1 gf craving landed in a plan
4. Ordering ≤5 min with the cart-ready list
5. Verdicts being given without nagging (else the feedback UX is wrong)

If met → build v2 (cart automation). If not → fix the loop, don't add automation.

## Out of scope (v1)

Lunches/breakfasts · cook-night assignment · macro tracking · pantry photo
inventory · price optimization/specials hunting · meal-kit comparisons · any
butler domain beyond cooking · hosting/backend/iOS app.
