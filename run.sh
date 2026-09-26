#!/bin/bash
# Start the web server (serving only public/) and the scraper. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p public probe

PORT="${TW_PORT:-7777}"
python3 -m http.server "$PORT" --directory public --bind 0.0.0.0 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; tmux kill-session -t tw_claude 2>/dev/null; tmux kill-session -t tw_codex 2>/dev/null; true' EXIT

IP=$(ipconfig getifaddr en0 2>/dev/null || echo "<Mac-IP>")
echo "Open on your tablet: http://$IP:$PORT"

# Prevent idle sleep while the scraper runs; closing the lid can still put the Mac to sleep.
caffeinate -i python3 scrape.py
