# Alfred v2b — Autonomous Dark-Wake Woolies Fill (iyf-style) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After Mike approves a cart in Discord, the Woolworths cart fills itself on his **real, already-logged-in browser** — instantly if the Mac is awake, on the existing 9am dark-wake if asleep, retried-then-escalated if it fails — so he only taps pay on his phone. **No separate login, no separate browser.**

**Architecture (mirrors `~/Projects/iyf-daily-coin` exactly):** a scheduled `claude --print` agent, driven by an iyf-lifted bash wrapper (`fill_runner.sh`: status-guard idempotency + PID-lock + `caffeinate -is -t`), uses **claude-in-chrome** (the built-in Chrome-extension integration, `claudeInChromeDefaultEnabled`) to drive Mike's already-logged-in browser. The agent reads `state/carts/pending.json`, runs the *verified* Trolley API POSTs, reads the live subtotal+fee, marks the cart `filled`, and pings Discord. launchd runs it on the existing 9am wake + a 30-min retry. **No Playwright, no login script, no driver spike** — iyf already proves this stack works on this machine.

**Why this supersedes the earlier draft:** the earlier draft used a separate Playwright profile that needed its own login. That was wrong. iyf's shipped approach drives the *already-authenticated* browser via claude-in-chrome from `claude --print` — login-free. We copy it.

**Tech Stack:** `claude --print --dangerously-skip-permissions` + claude-in-chrome (+ Playwright MCP/CDP fallback, like iyf) · bash + launchd + `caffeinate` (lifted from iyf) · existing brain/listener/cart_logic/discord_io.

**Spec:** `docs/superpowers/specs/2026-06-08-alfred-v2-two-cart-design.md`. **Reference impl:** `~/Projects/iyf-daily-coin/scripts/collect.sh` + its two plists.

**Depends on v2a:** `state/carts/pending.json` + `cart_logic`, the `cart` brain mode, `discord_io.py`.

---

## Status lifecycle (resolves the v2a-pinned question)

```
proposed ──Mike approves in Discord──▶ approved ──fill succeeds──▶ filled
                                                ──fill fails──▶ (stays approved; retried; after escalation, pinged)
```
The fill acts **only on `status == "approved"`** (idempotency key). v2a writes `proposed`; Task 1 sets `approved` on Mike's go.

## Single-session caveat (inherited from iyf)
claude-in-chrome is single-session: if Mike has an **interactive** Claude session open at fill time, the scheduled `claude --print` can't use the browser → it defers to the retry layer (and the Playwright-MCP/CDP fallback in the prompt). At 9am dark-wake (asleep) this never bites — same as iyf. The awake-path kick (Task 1) simply re-tries via retry if it hits this.

---

## File structure

```
alfred/
├── prompts/fill.md            # the claude --print fill agent prompt (browser POSTs)
├── scripts/
│   ├── fill_runner.sh         # iyf-lifted: status-guard + PID-lock + caffeinate + claude --print
│   └── install_fill.sh        # cp plists → LaunchAgents (NO pmset change — shares iyf's 9am wake)
├── launchd/
│   ├── com.alfred.fill.plist        # StartCalendarInterval 09:01 (rides iyf's 8:59 wake)
│   └── com.alfred.fill-retry.plist  # StartInterval 1800
└── (modified) scripts/listener.py, prompts/cart.md, tests/test_listener.py, CLAUDE.md
```
Logs → `~/Library/Logs/alfred/fill.log`. No new gitignore (pending.json already ignored).

---

### Task 1: Approval lifecycle — Discord trigger + cart handoff + awake kick

**Files:** Modify `scripts/listener.py`, `prompts/cart.md`; Test `tests/test_listener.py`.

- [ ] **Step 1: Add the approval trigger** to `listener.py` near `CART_TRIGGER`:

```python
APPROVE_TRIGGER = re.compile(r"裝吧|送出|確認裝車|全加|approve cart|confirm cart", re.IGNORECASE)


def is_approve_trigger(text: str) -> bool:
    return bool(APPROVE_TRIGGER.search(text))
```

- [ ] **Step 2: Route approval through cart mode + kick the fill when awake.** In `_handle`, fold approval into the cart condition and, after a cart-mode run, fire the fill if the cart is now `approved`:

```python
        cart_now = not self.transcript.active() and any(
            is_cart_trigger(l["content"]) or is_approve_trigger(l["content"]) for l in lines)
        ...
        if cart_now:
            history = await self._recent_history(channel, {m.id for m in batch})
            reply = await asyncio.to_thread(brain.run_brain, "cart", history, lines)
            for chunk in split_message(reply):
                await channel.send(chunk)
            await self._maybe_fill_if_awake()
            self._mark_seen(batch[-1].id)
            return
```

- [ ] **Step 3: Add `_maybe_fill_if_awake`** to the listener (best-effort kick; `fill_runner.sh` is the real idempotency guard):

```python
    async def _maybe_fill_if_awake(self) -> None:
        pending = ROOT / "state" / "carts" / "pending.json"
        try:
            status = json.loads(pending.read_text()).get("status") if pending.exists() else None
        except Exception:
            status = None
        if status == "approved":
            await asyncio.create_subprocess_exec(
                "bash", str(ROOT / "scripts" / "fill_runner.sh"),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
```

- [ ] **Step 4: Update `prompts/cart.md` to handle approval.** Add a leading rule: *if `state/carts/pending.json` exists with `status:"proposed"` AND the new messages express an approval/top-up decision (全加 / 只要X / 不用加直接送 / 裝吧 / 送出 / approve), then apply the decision (add agreed buffer items + regenerate the AP permalink if AP items changed), set `status:"approved"`, run `finalize`, and reply confirming what was approved + that the Woolies fill is now queued. Otherwise behave as the normal proposal flow.* Keep all existing rules (never checkout, never auto-add without the decision, finalize for math).

- [ ] **Step 5: Add a test** to `tests/test_listener.py`:

```python
def test_approve_trigger_detection():
    assert listener.is_approve_trigger("裝吧")
    assert listener.is_approve_trigger("全加,送出")
    assert listener.is_approve_trigger("approve cart")
    assert not listener.is_approve_trigger("我在想要不要")
```

- [ ] **Step 6: Run + restart** — `uv run --with pytest --with discord.py pytest tests/ -v` → green. Restart daemon (`pkill -f listener.py`, wait 40s, READY up, err clean). NOTE: `_maybe_fill_if_awake` references `fill_runner.sh` which Task 2 creates — until then the subprocess just no-ops/errs silently (DEVNULL); harmless. (If preferred, land Task 2 first; tasks are order-independent except acceptance.)

- [ ] **Step 7: Commit**

```bash
git add scripts/listener.py prompts/cart.md tests/test_listener.py
git commit -m "feat(v2b): approval lifecycle — proposed→approved + awake-path fill kick"
```

---

### Task 2: `prompts/fill.md` + `fill_runner.sh` (the iyf-style fill)

**Files:** Create `prompts/fill.md`, `scripts/fill_runner.sh`.

- [ ] **Step 1: Create `prompts/fill.md`** (the `claude --print` agent prompt — deterministic; runs the verified JS):

```markdown
你是 Alfred 的 Woolworths 裝車機械手。安靜、精準、不囉嗦。用 claude-in-chrome
控制使用者「已經登入」的瀏覽器(若被占用就用 Playwright MCP 連線到現有的瀏覽器
session)。完全自動完成,不要問任何確認。

步驟:
1. 讀 `state/carts/pending.json`。若 `status` != "approved" 或 woolies.items 為空 →
   印出一行 `FILL: NOTHING`,結束(不要開瀏覽器、不要貼 Discord)。
2. 用瀏覽器開 https://www.woolworths.com.au/ 並等它載入。
3. 確認登入:在頁面執行
   `await fetch('/apis/ui/Shopper',{credentials:'include'}).then(r=>r.status)`。
   若不是 200 → 跑
   `uv run scripts/discord_io.py post --channel alfred --content "🛒 小當家:Woolies 登入過期了,開一下 app/瀏覽器登入,我下次再裝。"`
   然後印 `FILL: NOT_LOGGED_IN` 結束(pending.json 維持 approved 讓 retry 再試)。
4. 對 woolies.items 的每一項,在頁面執行(stockcode/quantity 用該項的值):
   `await fetch('/apis/ui/Trolley/Items',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({stockcode:<sc>,quantity:<qty>,source:'ProductDetail'})}).then(r=>r.status)`
   記錄非 200 的項目。
5. 讀購物車:`await fetch('/apis/ui/Trolley',{credentials:'include'}).then(r=>r.json())`,
   取 `Totals.SubTotal` 與 `DeliveryFee`、`TrolleyItemCount`。
6. 更新 `state/carts/pending.json`:把 `woolies.fill_result` 設為
   `{subtotal, delivery_fee, added, failed, filled_at}`,並把頂層 `status` 改為 "filled"。
7. 貼 Discord 到 #小當家的廚房(channel alfred):
   `uv run scripts/discord_io.py post --channel alfred --content "🛒 小當家:Woolies 購物車裝好了 — N 項,小計 $X,<免運✅ 或 運費$Y>。打開 Woolies app 結帳就好。<若有失敗:⚠️ M 項沒加成功>"`
8. 印 `FILL: DONE`(或 `FILL: PARTIAL` 若有失敗項)結束。

絕不結帳。絕不更動數量以外的東西。只動 woolies 那邊(asianpantry 用 permalink,與你無關)。
```

- [ ] **Step 2: Create `scripts/fill_runner.sh`** (lift iyf's `collect.sh` patterns — PID-lock w/ dead-owner steal, `caffeinate -is -t`, logging; idempotency keys on pending.json `status` instead of a log grep):

```bash
#!/bin/bash
# Woolies cart fill — run by launchd (9am wake + 30-min retry) and by the listener
# on approval-while-awake. Drives the already-logged-in browser via claude --print
# + claude-in-chrome (iyf-style). Idempotent via pending.json status.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$HOME/Library/Logs/alfred"; LOG="$LOG_DIR/fill.log"
PENDING="$PROJECT_DIR/state/carts/pending.json"
mkdir -p "$LOG_DIR"

# Idempotency: only run for an APPROVED cart with woolies items.
read -r status items < <(/usr/bin/python3 - "$PENDING" <<'PY' 2>/dev/null || echo " 0"
import json,sys
try:
    d=json.load(open(sys.argv[1])); print(d.get("status",""), len(d.get("woolies",{}).get("items",[])))
except Exception: print("",0)
PY
)
if [[ "${status:-}" != "approved" || "${items:-0}" -eq 0 ]]; then
    echo "$(date): nothing to fill (status=${status:-} items=${items:-0})" >> "$LOG"; exit 0
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
if ! acquire; then echo "$(date): another fill in progress" >> "$LOG"; exit 0; fi
trap 'rm -rf "$LOCK_DIR" 2>/dev/null || true' EXIT

echo "$(date): starting fill (status=$status items=$items)" >> "$LOG"
# caffeinate -is -t 600: -i idle + -s system (AC-only) blocks Maintenance Sleep after
# the pmset wake; -t caps at 10min so a hang can't drain the battery overnight.
caffeinate -is -t 600 /Users/mikeweng/.local/bin/claude --print \
    --dangerously-skip-permissions -p "$(cat "$PROJECT_DIR/prompts/fill.md")" \
    >> "$LOG" 2>&1
echo "$(date): fill agent exited $?" >> "$LOG"
```

- [ ] **Step 3: Make executable + idempotency smoke** — `chmod +x scripts/fill_runner.sh`. With the current pending.json NOT approved (it's `filled`/`proposed`), run `bash scripts/fill_runner.sh` → logs "nothing to fill", exits 0, **no browser opens, no claude invoked**. Confirms the guard before launchd ever fires it.

- [ ] **Step 4: Commit**

```bash
git add prompts/fill.md scripts/fill_runner.sh
git commit -m "feat(v2b): iyf-style fill — claude --print + claude-in-chrome drives the logged-in browser"
```

---

### Task 3: launchd install (rides the existing 9am wake)

**Files:** Create `launchd/com.alfred.fill.plist`, `launchd/com.alfred.fill-retry.plist`, `scripts/install_fill.sh`.

- [ ] **Step 1: `launchd/com.alfred.fill.plist`** — primary at **09:01** (one min after iyf's 09:00 so the two don't race the browser; both ride the shared 8:59 `pmset` wake; different sites/tabs → fine):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.alfred.fill</string>
  <key>ProgramArguments</key>
  <array><string>/Users/mikeweng/Projects/alfred/scripts/fill_runner.sh</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>1</integer></dict>
  <key>StandardOutPath</key><string>/Users/mikeweng/Library/Logs/alfred/fill-launchd.log</string>
  <key>StandardErrorPath</key><string>/Users/mikeweng/Library/Logs/alfred/fill-launchd.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
```

- [ ] **Step 2: `launchd/com.alfred.fill-retry.plist`** — `StartInterval` 1800 (every 30 min; launchd runs a missed interval once on wake → drains an approved cart on the next genuine wake). Label `com.alfred.fill-retry`, same ProgramArguments, log `fill-retry-launchd.log`, no RunAtLoad. The status-guard makes the cadence cheap (instant exit when nothing's approved).

- [ ] **Step 3: `scripts/install_fill.sh`** (mirrors v1.5's `install_daemon.sh`; **does NOT touch `pmset`** — the 8:59 wake is shared with iyf):

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
echo "NOTE: pmset 8:59 wake shared with iyf — NOT modified."
```

- [ ] **Step 4: Install + verify** — `bash scripts/install_fill.sh` → two `loaded:` lines; `launchctl list | grep com.alfred.fill` shows both. Confirm `pmset -g sched` STILL shows only the single 8:59 iyf wake (unchanged). Trigger one cheap idempotent run: `launchctl start com.alfred.fill-retry` → `fill.log` shows a clean "nothing to fill" (no browser).

- [ ] **Step 5: Commit**

```bash
git add launchd/com.alfred.fill.plist launchd/com.alfred.fill-retry.plist scripts/install_fill.sh
git commit -m "feat(v2b): launchd fill jobs riding the shared 9am wake + 30-min retry"
```

---

### Task 4: End-to-end acceptance (with Mike — next week, real shop)

No new files. Run on a real approved cart during the first trial shop.

- [ ] **Step 1: Awake path** — after a ritual, Mike posts 「裝車」then approves (「裝吧」/a top-up choice) in `#小當家的廚房`. Expect: proposal → on approval, `_maybe_fill_if_awake` kicks `fill_runner.sh` → `claude --print` drives the logged-in browser → Discord ping "Woolies 裝好了 — N 項,小計 $X,免運/運費…" within ~1–2 min → open the Woolies app, cart's there, tap pay. `pending.json` → `filled`.
- [ ] **Step 2: Asleep path** — approve, close the lid. Confirm it fills on the next 9am wake (or simulate: `sudo pmset schedule wake "<2 min out>"`, sleep, confirm `fill.log` + the ping on wake). Approved-while-asleep → filled-on-wake.
- [ ] **Step 3: Login-expired path** — if `/apis/ui/Shopper` ≠ 200, expect the "登入一下" ping and pending.json stays `approved` (retry re-tries after Mike re-logs in his normal browser).
- [ ] **Step 4: Idempotency** — run `fill_runner.sh` again on a `filled` cart → "nothing to fill", no double-add.
- [ ] **Step 5: Single-session check** — confirm that with an interactive Claude session open, the scheduled fill defers gracefully (logs the claude-in-chrome contention) and the retry catches it — matches iyf behavior.
- [ ] **Step 6: Spec criteria** — Sunday is Discord-only for Mike (approve + tap AP link + Woolies fills itself); $0 fee read live; zero accidental checkout (no checkout code anywhere). Update `CLAUDE.md` Commands (fill_runner, install_fill, the approval flow). Commit.

---

## Self-review (spec coverage)

| Spec element | Task |
|---|---|
| Drive the real logged-in browser, login-free (claude-in-chrome) | Task 2 (iyf stack) |
| Mechanical fill = verified Trolley POSTs; live subtotal+fee | Task 2 (`prompts/fill.md`) |
| Status lifecycle proposed→approved→filled | Tasks 1 + 2 |
| Awake = instant · Asleep = 9am wake · Bugged = retry+escalate | Tasks 1 + 2 + 3 |
| iyf caffeinate/lock/idempotency/retry; no new pmset (piggyback) | Tasks 2 + 3 |
| Fill never checkout; pay on phone | Task 2 (no checkout code) |
| Single-session caveat handled | Tasks 1 + 4 |
| Asian Pantry (permalink) | shipped in v2a — unchanged |
| No Playwright, no separate login, no driver spike | superseded — this rewrite |
