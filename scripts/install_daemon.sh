#!/bin/bash
# Install/refresh Alfred's launchd jobs. Run from repo root: bash scripts/install_daemon.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .runtime
for plist in launchd/*.plist; do
  name=$(basename "$plist")
  dest="$HOME/Library/LaunchAgents/$name"
  launchctl unload "$dest" 2>/dev/null || true
  cp "$plist" "$dest"
  launchctl load "$dest"
  echo "loaded: $name"
done
launchctl list | grep com.alfred || true
