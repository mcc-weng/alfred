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

# Defer to the iyf coin collector if it's mid-run — claude-in-chrome is single-session.
IYF_LOCK="$HOME/Library/Logs/iyf-daily-coin/.collect.lock/pid"
if [[ -f "$IYF_LOCK" ]]; then
    iyf_pid="$(cat "$IYF_LOCK" 2>/dev/null || true)"
    if [[ -n "$iyf_pid" ]] && kill -0 "$iyf_pid" 2>/dev/null; then
        echo "$(date): iyf collection in progress (pid $iyf_pid) — deferring to retry" >> "$LOG"
        exit 0
    fi
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
