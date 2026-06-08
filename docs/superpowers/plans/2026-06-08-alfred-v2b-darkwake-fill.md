# Alfred v2b — Autonomous Dark-Wake Woolies Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Mike approves a cart in Discord, the Woolworths cart fills itself on his real logged-in browser — instantly if the Mac is awake, on the existing 9am dark-wake if asleep, on next boot if off, retried-then-escalated if it fails — so he only ever taps pay on his phone.

**Architecture:** A mechanical fill script (`woolies_fill.py`, no AI) reads `state/carts/pending.json`, drives Mike's real logged-in browser (driver chosen by the Task 1 spike — Playwright persistent profile vs CDP to real Chrome), POSTs each SKU to the verified Trolley API, reads the live subtotal+fee, marks the cart `filled`, and pings Discord. An iyf-lifted wrapper (`fill_runner.sh`: PID-lock + idempotency + `caffeinate -is`) is run by launchd (rides the existing 9am `pmset` wake + a 30-min retry) and by the listener immediately when a cart is approved while awake.

**Tech Stack:** Python 3.11+ + Playwright (`uv run`), bash + launchd + `caffeinate` (lifted from `~/Projects/iyf-daily-coin`), the existing brain/listener/cart_logic from v1.5/v2a, pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-alfred-v2-two-cart-design.md` (esp. "The Woolies fill", the laptop-state table, and "Plan B design inputs").

**Depends on v2a:** `state/carts/pending.json` (schema + `cart_logic.validate_pending`/`finalize`), the `cart` brain mode, `discord_io.py`.

---

## Status lifecycle (the v2a-pinned design, resolved here)

```
proposed  ──Mike approves in Discord──▶  approved  ──fill runs──▶  filled
                                                   ──fill fails──▶ (stays approved; retried; after N → escalated)
```

- v2a's `cart` mode writes `proposed`.
- **Approval (Task 4):** Mike replies with intent (「裝吧」/「全加」/「只要X」/「不用加直接送」/approve/confirm). The listener routes that to `cart` mode again; the updated `cart.md` applies the top-up decision, sets `status:"approved"`, re-runs `finalize`, and — if the Mac is awake — kicks the fill immediately.
- **The fill only ever acts on `status == "approved"`.** It never fills a `proposed` (un-approved) or `filled` (done) cart. This is the idempotency key.

---

## File structure

```
alfred/
├── scripts/
│   ├── woolies_fill.py        # mechanical fill: pending.json → real browser → Trolley API → result
│   ├── fill_runner.sh         # iyf-lifted wrapper: lock + idempotency + caffeinate + logging
│   └── install_fill.sh        # cp plists → LaunchAgents + launchctl load (NO pmset change)
├── launchd/
│   ├── com.alfred.fill.plist        # StartCalendarInterval 09:01 (rides iyf 8:59 wake)
│   └── com.alfred.fill-retry.plist  # StartInterval 1800
├── tests/
│   ├── test_woolies_fill.py   # pure logic: pending selection, result shaping, status guard
│   └── (extend) test_listener.py
└── (modified) prompts/cart.md, scripts/listener.py, scripts/brain.py, .gitignore
```

`.runtime/profiles/woolies/` (Playwright profile, gitignored) and
`.runtime/fill.log` hold browser state + logs.

---

### Task 1: Fill-driver spike (GATE — decides the whole approach)

**No production files.** A throwaway spike in `/tmp/alfred-fillspike/` that answers: *can an automated/headless-launched browser, reusing Mike's one-time login, do authenticated Trolley cart-adds without Akamai blocking?* The answer picks the driver for Task 2.

The verified facts (from prior spikes): Woolworths blocks *headless* Playwright (Akamai); a *headed* Playwright homepage load passed; Mike's *real Chrome* (Claude-in-Chrome) does authenticated add/read/remove + live fee perfectly. Unknown: does **headed Playwright with a persistent logged-in profile** survive on *authenticated POSTs* (not just homepage)?

- [ ] **Step 1: One-time interactive login into a Playwright persistent profile.** Write `/tmp/alfred-fillspike/login.py`:

```python
import pathlib
from playwright.sync_api import sync_playwright
PROFILE = pathlib.Path("/Users/mikeweng/Projects/alfred/.runtime/profiles/woolies")
PROFILE.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(str(PROFILE), headless=False,
              viewport={"width": 1200, "height": 820})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://www.woolworths.com.au/", timeout=45000)
    print("Log in manually in the window (handle 2FA/captcha). Press Enter here when the header shows 'Hi, <name>'.")
    input()
    ok = page.evaluate("async () => (await fetch('/apis/ui/Shopper', {credentials:'include'})).status")
    print("Shopper status:", ok)  # expect 200
    ctx.close()
```
Run `uv run --with playwright python /tmp/alfred-fillspike/login.py`. **Mike logs in once** in the window. Confirm it prints `Shopper status: 200`.

- [ ] **Step 2: Headless re-use test** (the real question). Write `/tmp/alfred-fillspike/fill_test.py`:

```python
import json, pathlib
from playwright.sync_api import sync_playwright
PROFILE = "/Users/mikeweng/Projects/alfred/.runtime/profiles/woolies"
def run(headless):
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE, headless=headless,
                  viewport={"width": 1200, "height": 820})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.woolworths.com.au/", timeout=45000)
        denied = "Access Denied" in page.content()
        shopper = page.evaluate("async()=>(await fetch('/apis/ui/Shopper',{credentials:'include'})).status")
        add = page.evaluate("""async()=>{const r=await fetch('/apis/ui/Trolley/Items',{method:'POST',
            credentials:'include',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({stockcode:144329,quantity:1,source:'ProductDetail'})});return r.status;}""")
        t = page.evaluate("async()=>{const r=await fetch('/apis/ui/Trolley',{credentials:'include'});const j=await r.json();return {n:j.TrolleyItemCount,sub:j.Totals?.SubTotal,fee:j.DeliveryFee};}")
        page.evaluate("""async()=>{await fetch('/apis/ui/Trolley/Items',{method:'POST',credentials:'include',
            headers:{'Content-Type':'application/json'},body:JSON.stringify({stockcode:144329,quantity:0,source:'Trolley'})});}""")
        ctx.close()
        return {"headless": headless, "denied": denied, "shopper": shopper, "add": add, "trolley": t}
for h in (True, False):
    print(json.dumps(run(h)))
```
Run it. **Decision gate:**
- If `headless:true` gives `denied:false, shopper:200, add:200, trolley.n:1` → **Driver A: headless Playwright persistent profile** (best — fully invisible on dark-wake). Record in the plan.
- Else if `headless:false` works but headless is blocked → **Driver A-headed** (headed Playwright; on dark-wake there's no display so it runs invisibly anyway). Record.
- Else (both blocked on authenticated POST) → **Driver B: CDP to Mike's real Chrome** launched with `--remote-debugging-port=9222` and his everyday profile; document the security note (localhost-only debug port, opened only during the fill window). Write a 5-line CDP variant and confirm `add:200`.

- [ ] **Step 3: Record the verdict** in this plan file (edit Task 2's "DRIVER" note) and clean up `/tmp/alfred-fillspike/` (keep `.runtime/profiles/woolies` — that's the real login). If ALL drivers fail, STOP and escalate: v2b falls back to v2a's interactive Claude-in-Chrome push (still phone-pay); do not build the autonomous fill.

---

### Task 2: `woolies_fill.py` — the mechanical fill

**DRIVER:** _(set by Task 1 — default assume Driver A-headed Playwright persistent profile unless the spike says otherwise)_

**Files:**
- Create: `scripts/woolies_fill.py`
- Test: `tests/test_woolies_fill.py`

The browser I/O is live-verified (not unit-tested); the **pure logic** (which cart to act on, result shaping, the status guard) is TDD'd.

- [ ] **Step 1: Write failing tests** — `tests/test_woolies_fill.py`:

```python
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
import woolies_fill as wf


def test_should_fill_only_when_approved():
    assert wf.should_fill({"status": "approved", "woolies": {"items": [{"stockcode": 1, "qty": 1}]}}) is True
    assert wf.should_fill({"status": "proposed", "woolies": {"items": [{"stockcode": 1, "qty": 1}]}}) is False
    assert wf.should_fill({"status": "filled", "woolies": {"items": [{"stockcode": 1, "qty": 1}]}}) is False


def test_should_fill_false_when_no_woolies_items():
    # nothing to add to Woolies this week → nothing to fill
    assert wf.should_fill({"status": "approved", "woolies": {"items": []}}) is False


def test_adds_payload_from_items():
    items = [{"stockcode": 144329, "qty": 2}, {"stockcode": 999, "qty": 1}]
    assert wf.add_payloads(items) == [
        {"stockcode": 144329, "quantity": 2, "source": "ProductDetail"},
        {"stockcode": 999, "quantity": 1, "source": "ProductDetail"},
    ]


def test_fill_result_shape():
    r = wf.make_result(subtotal=96.4, delivery_fee=0.0, added=14, failed=[])
    assert r["subtotal"] == 96.4 and r["delivery_fee"] == 0.0
    assert r["added"] == 14 and r["failed"] == [] and "filled_at" in r
```

- [ ] **Step 2: Run, verify fail** — `uv run --with pytest pytest tests/test_woolies_fill.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Create `scripts/woolies_fill.py`:**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "certifi"]
# ///
"""Mechanical Woolworths cart fill. NO AI.

Reads state/carts/pending.json; if status=approved with woolies items, drives the
real logged-in browser (Playwright persistent profile) to POST each SKU to the
Trolley API, reads live subtotal+fee, writes fill_result + status=filled, and
pings Discord. Idempotent: only acts on status==approved; sets filled on success.

Usage: uv run scripts/woolies_fill.py [--dry-run]
Login once first: uv run scripts/woolies_fill.py login   (headed; Mike logs in)
"""
import datetime
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PENDING = ROOT / "state" / "carts" / "pending.json"
PROFILE = ROOT / ".runtime" / "profiles" / "woolies"
HEADLESS = True  # Task 1 sets this; on dark-wake there's no display regardless


def should_fill(p: dict) -> bool:
    return p.get("status") == "approved" and bool(p.get("woolies", {}).get("items"))


def add_payloads(items: list[dict]) -> list[dict]:
    return [{"stockcode": i["stockcode"], "quantity": i["qty"], "source": "ProductDetail"}
            for i in items]


def make_result(subtotal, delivery_fee, added, failed) -> dict:
    return {"subtotal": subtotal, "delivery_fee": delivery_fee, "added": added,
            "failed": failed, "filled_at": _now()}


def _now() -> str:
    # launchd runs set a real clock; this is allowed at runtime (not in workflow scripts)
    return datetime.datetime.now().isoformat(timespec="seconds")


def _ping(msg: str) -> None:
    subprocess.run(["/opt/homebrew/bin/uv", "run", str(ROOT / "scripts" / "discord_io.py"),
                    "post", "--channel", "alfred", "--content", msg], cwd=ROOT, check=False)


def _browser(pw, headless: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        str(PROFILE), headless=headless, viewport={"width": 1200, "height": 820})


def login() -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _browser(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.woolworths.com.au/", timeout=45000)
        print("Log in manually (2FA/captcha ok). Enter when header shows your name.")
        input()
        print("Shopper:", page.evaluate(
            "async()=>(await fetch('/apis/ui/Shopper',{credentials:'include'})).status"))
        ctx.close()


def fill(dry_run: bool = False) -> int:
    from playwright.sync_api import sync_playwright
    if not PENDING.exists():
        print("no pending.json — nothing to do"); return 0
    p = json.loads(PENDING.read_text())
    if not should_fill(p):
        print(f"status={p.get('status')}, woolies items="
              f"{len(p.get('woolies', {}).get('items', []))} — not fillable; skip"); return 0
    payloads = add_payloads(p["woolies"]["items"])
    with sync_playwright() as pw:
        ctx = _browser(pw, headless=HEADLESS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.woolworths.com.au/", timeout=45000)
        if page.evaluate("async()=>(await fetch('/apis/ui/Shopper',{credentials:'include'})).status") != 200:
            ctx.close()
            _ping("🛒 小當家:Woolies 登入過期了,開一下 Woolies 登入,我下次再裝。")
            print("not logged in — pinged Mike"); return 2
        failed = []
        for pl in payloads:
            st = page.evaluate("""async(pl)=>{const r=await fetch('/apis/ui/Trolley/Items',
                {method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},
                 body:JSON.stringify(pl)});return r.status;}""", pl)
            if st != 200:
                failed.append({"stockcode": pl["stockcode"], "status": st})
        tot = page.evaluate("""async()=>{const r=await fetch('/apis/ui/Trolley',{credentials:'include'});
            const j=await r.json();return {sub:j.Totals?.SubTotal, fee:j.DeliveryFee, n:j.TrolleyItemCount};}""")
        ctx.close()
    result = make_result(tot["sub"], tot["fee"], len(payloads) - len(failed), failed)
    if not dry_run:
        p["woolies"]["fill_result"] = result
        p["status"] = "filled"
        PENDING.write_text(json.dumps(p, ensure_ascii=False, indent=1))
    fee_line = "免運 ✅" if (tot["fee"] or 0) == 0 else f"運費 ${tot['fee']}"
    warn = f" ⚠️ {len(failed)} 項沒加成功" if failed else ""
    _ping(f"🛒 小當家:Woolies 購物車裝好了 — {result['added']} 項,小計 ${tot['sub']},{fee_line}。"
          f"打開 Woolies app 結帳就好。{warn}")
    print(json.dumps(result)); return 1 if not failed else 3


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        login(); return
    sys.exit(0 if fill(dry_run="--dry-run" in sys.argv) in (0, 1) else 1)


if __name__ == "__main__":
    main()
```

(If Task 1 chose Driver B/CDP, replace `_browser` with a `connect_over_cdp` variant — same `page.evaluate` calls — and set `HEADLESS` accordingly. The pure functions and tests are unchanged.)

- [ ] **Step 4: Run tests** — `uv run --with pytest pytest tests/test_woolies_fill.py -v` → 4 passed. Full suite green.

- [ ] **Step 5: Live verify** — with a hand-made approved pending.json (one cheap real SKU, e.g. 144329 brown onion, status `approved`), run `uv run scripts/woolies_fill.py`. Expect: cart filled, Discord ping with subtotal+fee, pending.json now `filled`. Then check the item in the Woolies app/site (it synced). Remove it after.

- [ ] **Step 6: Commit**

```bash
git add scripts/woolies_fill.py tests/test_woolies_fill.py
git commit -m "feat(v2b): mechanical woolies cart fill via real logged-in browser"
```

---

### Task 3: `fill_runner.sh` — iyf-lifted wrapper (lock + idempotency + caffeinate)

**Files:**
- Create: `scripts/fill_runner.sh`

- [ ] **Step 1: Create `scripts/fill_runner.sh`** (lifts `~/Projects/iyf-daily-coin/scripts/collect.sh` patterns — PID-lock with dead-owner steal, idempotency, `caffeinate -is -t`, `--retry` deferral is N/A here so omitted; idempotency keys on pending.json status instead of a log grep):

```bash
#!/bin/bash
# Woolies cart fill wrapper. Run by launchd (9am wake + 30-min retry) and by the
# listener when a cart is approved while awake. Idempotent via pending.json status.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/Library/Logs/alfred"
LOG="$LOG_DIR/fill.log"
PENDING="$PROJECT_DIR/state/carts/pending.json"
mkdir -p "$LOG_DIR"

# Idempotency: only run when an APPROVED cart with woolies items is waiting.
status="$(/usr/bin/python3 -c "import json,sys;d=json.load(open('$PENDING'));print(d.get('status',''))" 2>/dev/null || echo "")"
items="$(/usr/bin/python3 -c "import json;d=json.load(open('$PENDING'));print(len(d.get('woolies',{}).get('items',[])))" 2>/dev/null || echo 0)"
if [[ "$status" != "approved" || "$items" -eq 0 ]]; then
    echo "$(date): nothing to fill (status=$status items=$items) — exit" >> "$LOG"
    exit 0
fi

# PID-tracked single-run lock (dead-owner steal — survives crashes, no fixed timeout).
LOCK_DIR="$LOG_DIR/.fill.lock"
acquire() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then echo $$ > "$LOCK_DIR/pid"; return 0; fi
    local owner; owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [[ -n "$owner" ]] && kill -0 "$owner" 2>/dev/null; then return 1; fi
    rm -rf "$LOCK_DIR" 2>/dev/null || true; mkdir "$LOCK_DIR" 2>/dev/null || return 1
    echo $$ > "$LOCK_DIR/pid"; return 0
}
if ! acquire; then echo "$(date): another fill in progress — exit" >> "$LOG"; exit 0; fi
trap 'rm -rf "$LOCK_DIR" 2>/dev/null || true' EXIT

echo "$(date): starting fill" >> "$LOG"
# caffeinate -is -t 600: -i (idle) + -s (system, AC-only) blocks Maintenance Sleep
# after a pmset wake; -t caps at 10min so a hang can't drain the battery overnight.
caffeinate -is -t 600 /opt/homebrew/bin/uv run "$PROJECT_DIR/scripts/woolies_fill.py" >> "$LOG" 2>&1
echo "$(date): fill done (exit $?)" >> "$LOG"
```

- [ ] **Step 2: Make executable + smoke** — `chmod +x scripts/fill_runner.sh`. With pending.json NOT approved (e.g. the current `filled`/`proposed`), run `bash scripts/fill_runner.sh` → logs "nothing to fill", exits 0, no browser launched. (Confirms the idempotency guard before launchd ever fires it.)

- [ ] **Step 3: Commit**

```bash
git add scripts/fill_runner.sh
git commit -m "feat(v2b): fill_runner.sh — iyf-lifted lock/idempotency/caffeinate wrapper"
```

---

### Task 4: Approval lifecycle — Discord trigger + cart-mode handoff + awake fill

**Files:**
- Modify: `scripts/listener.py`, `prompts/cart.md`
- Test: extend `tests/test_listener.py`

- [ ] **Step 1: Add approval trigger to `listener.py`.** Near `CART_TRIGGER`:

```python
APPROVE_TRIGGER = re.compile(r"裝吧|送出|確認裝車|全加|approve cart|confirm cart", re.IGNORECASE)


def is_approve_trigger(text: str) -> bool:
    return bool(APPROVE_TRIGGER.search(text))
```

- [ ] **Step 2: Route approval through cart mode + kick the fill if awake.** In `_handle`, fold approval into the cart branch so an approval message also runs `cart` mode (which will read pending.json + Mike's decision, set `approved`, re-finalize). After a cart-mode run, if the resulting pending.json is `approved`, trigger the fill in the background:

```python
        cart_now = not self.transcript.active() and any(
            is_cart_trigger(l["content"]) or is_approve_trigger(l["content"]) for l in lines)
        ...
        if cart_now:
            history = await self._recent_history(channel, {m.id for m in batch})
            reply = await asyncio.to_thread(brain.run_brain, "cart", history, lines)
            for chunk in split_message(reply):
                await channel.send(chunk)
            await self._maybe_fill_if_awake()   # see Step 3
            self._mark_seen(batch[-1].id)
            return
```

- [ ] **Step 3: Add `_maybe_fill_if_awake` to the listener** — fires the wrapper only when a cart is `approved`; the wrapper itself is the idempotency guard, so this is a best-effort kick:

```python
    async def _maybe_fill_if_awake(self) -> None:
        pending = ROOT / "state" / "carts" / "pending.json"
        try:
            status = json.loads(pending.read_text()).get("status") if pending.exists() else None
        except Exception:
            status = None
        if status == "approved":
            # awake path: run the fill now in the background; launchd/retry covers asleep.
            await asyncio.create_subprocess_exec(
                "bash", str(ROOT / "scripts" / "fill_runner.sh"),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
```

- [ ] **Step 4: Update `prompts/cart.md` to handle approval.** Add a leading rule: *if `state/carts/pending.json` already exists with `status:"proposed"` AND the user's new messages express an approval/top-up decision (全加/只要X/不用加直接送/裝吧/送出), then: apply the decision to the woolies+asianpantry items (add agreed buffer items, regenerate the AP permalink if items changed), set `status:"approved"`, run `finalize`, and reply confirming what was approved + that the Woolies fill is now queued. Otherwise behave as the normal proposal flow (status proposed).* Keep all existing rules (never checkout, never auto-add without the decision, finalize for math).

- [ ] **Step 5: Add tests** — `tests/test_listener.py`:

```python
def test_approve_trigger_detection():
    assert listener.is_approve_trigger("裝吧")
    assert listener.is_approve_trigger("全加,送出")
    assert listener.is_approve_trigger("approve cart")
    assert not listener.is_approve_trigger("我在想要不要")
```

- [ ] **Step 6: Run tests** — `uv run --with pytest --with discord.py pytest tests/ -v` → all green. Restart daemon (`pkill -f listener.py`, wait 40s, READY increased, err clean).

- [ ] **Step 7: Commit**

```bash
git add scripts/listener.py prompts/cart.md tests/test_listener.py
git commit -m "feat(v2b): approval lifecycle — proposed→approved + awake-path fill kick"
```

---

### Task 5: launchd install (rides the existing 9am wake)

**Files:**
- Create: `launchd/com.alfred.fill.plist`, `launchd/com.alfred.fill-retry.plist`, `scripts/install_fill.sh`

- [ ] **Step 1: Create `launchd/com.alfred.fill.plist`** — primary, 09:01 (one min after iyf's 09:00 so they don't collide; both ride the 8:59 `pmset` wake). Different browser profile than iyf (Woolies Chromium vs iyf Brave) → no collision.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alfred.fill</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/mikeweng/Projects/alfred/scripts/fill_runner.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>1</integer></dict>
  <key>StandardOutPath</key><string>/Users/mikeweng/Library/Logs/alfred/fill-launchd.log</string>
  <key>StandardErrorPath</key><string>/Users/mikeweng/Library/Logs/alfred/fill-launchd.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

- [ ] **Step 2: Create `launchd/com.alfred.fill-retry.plist`** — `StartInterval 1800` (every 30 min; launchd runs a missed interval once on wake → drains an approved cart whenever the Mac is next awake). Same ProgramArguments, label `com.alfred.fill-retry`, logs to `fill-retry-launchd.log`, no RunAtLoad. The `fill_runner.sh` idempotency guard makes the 30-min cadence cheap (instant exit when nothing's approved).

- [ ] **Step 3: Create `scripts/install_fill.sh`** (mirrors the v1.5 `install_daemon.sh`; **does NOT touch `pmset`** — the iyf 8:59 wake is shared):

```bash
#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p "$HOME/Library/Logs/alfred"
for plist in launchd/com.alfred.fill.plist launchd/com.alfred.fill-retry.plist; do
  name=$(basename "$plist"); dest="$HOME/Library/LaunchAgents/$name"
  launchctl unload "$dest" 2>/dev/null || true
  cp "$plist" "$dest"; launchctl load "$dest"; echo "loaded: $name"
done
launchctl list | grep com.alfred.fill || true
echo "NOTE: pmset wake is shared with iyf (8:59am) — not modified."
```

- [ ] **Step 4: Install + verify** — `bash scripts/install_fill.sh` → two `loaded:` lines; `launchctl list | grep com.alfred.fill` shows both. With nothing approved, confirm neither fires a browser (check `~/Library/Logs/alfred/fill.log` stays "nothing to fill" on the next retry tick, or trigger one: `launchctl start com.alfred.fill-retry` → log shows clean idempotent exit). Confirm `pmset -g sched` STILL shows only the single 8:59 iyf wake (unchanged).

- [ ] **Step 5: Commit**

```bash
git add launchd/com.alfred.fill.plist launchd/com.alfred.fill-retry.plist scripts/install_fill.sh
git commit -m "feat(v2b): launchd fill jobs riding the shared 9am wake + 30-min retry"
```

---

### Task 6: End-to-end acceptance (with Mike)

No new files. Exercises the full lifecycle across laptop states.

- [ ] **Step 1: One-time login** — `uv run scripts/woolies_fill.py login` → Mike logs into Woolies in the window once. Confirm `Shopper: 200`.

- [ ] **Step 2: Awake path (the happy case)** — after a ritual, Mike posts 「裝車」then approves (「裝吧」or a top-up choice) in `#小當家的廚房`. Expect: proposal → on approval, `_maybe_fill_if_awake` kicks `fill_runner.sh` → within ~1 min a Discord ping "Woolies 裝好了 — N 項,小計 $X,免運/運費 …" → open the Woolies app on the phone, the cart is there, tap pay. `pending.json` is `filled`.

- [ ] **Step 3: Asleep path** — approve a cart, immediately sleep the Mac (close lid). Confirm the cart fills on the next 9am wake (or, to test now, `sudo pmset schedule wake "<2 min from now>"`, sleep, and confirm the fill ran on wake — check `fill.log` + the Discord ping). Approved-while-asleep → filled-on-wake.

- [ ] **Step 4: Failure/escalation path** — set pending.json `approved` but break login (in a throwaway test, point at an empty profile): run `fill_runner.sh` → expect the "登入過期" Discord ping and pending.json stays `approved` (not `filled`) so the retry re-tries. Restore the real profile after.

- [ ] **Step 5: Idempotency** — run `fill_runner.sh` twice on an already-`filled` cart → second run logs "nothing to fill", no double-add. Confirm.

- [ ] **Step 6: Spec criteria** — Sunday is Discord-only for Mike (approve + tap AP link + Woolies fills itself); $0 fee read live; zero accidental checkout (no checkout code exists). Note results.

- [ ] **Step 7: Commit** any doc/state updates; update `CLAUDE.md` Commands with the fill + login + install_fill notes.

```bash
git add -A && git commit -m "docs(v2b): acceptance + fill/login/install commands in CLAUDE.md"
```

---

## Self-review (spec coverage)

| Spec element | Task |
|---|---|
| Mechanical fill of real logged-in browser (no AI) | Task 2 |
| Driver choice (headless/headed Playwright vs CDP) — spiked first | Task 1 (gate) |
| Live subtotal + delivery fee read; $0-fee confirmation | Task 2 (`/apis/ui/Trolley`) |
| Status lifecycle proposed→approved→filled (v2a-pinned) | Tasks 2 + 4 |
| Awake = instant fill | Task 4 (`_maybe_fill_if_awake`) |
| Asleep = fill on existing 9am dark-wake | Task 5 (rides iyf `pmset`) |
| Off = fill on next boot / Bugged = retry then escalate | Tasks 3 (retry) + 2 (login-expired ping) |
| iyf pattern: caffeinate/lock/idempotency/retry | Tasks 3 + 5 |
| No new pmset wake (piggyback) | Task 5 (install_fill.sh note) |
| Fill never checkout; pay on phone | Task 2 (no checkout code) |
| Login: one-time manual + .env fallback | Task 2 (`login`) + (.env fallback deferred unless Task 1 needs it) |
| Asian Pantry (permalink) | already shipped in v2a — unchanged |
```
