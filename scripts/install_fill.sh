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
