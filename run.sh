#!/bin/bash
# Start the web server (serving only public/) and the scraper. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p public probe

PORT="${TW_PORT:-7777}"
python3 -m http.server "$PORT" --directory public --bind 0.0.0.0 >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; tmux kill-session -t tw_claude 2>/dev/null; tmux kill-session -t tw_codex 2>/dev/null; true' EXIT

if command -v ipconfig >/dev/null 2>&1; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || true)
else
  IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
fi
IP="${IP:-<your-IP>}"
echo "Open on your tablet: http://$IP:$PORT"

# On macOS, prevent idle sleep while the scraper runs; closing the lid can still put the Mac to sleep.
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i python3 scrape.py
else
  python3 scrape.py
fi
