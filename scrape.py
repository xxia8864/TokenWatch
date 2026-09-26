#!/usr/bin/env python3
"""
Tokenwatch usage scraper.

Every TW_INTERVAL seconds, start a fresh Claude Code or Codex session in tmux,
run /usage or /status, read the percentages from the screen, write them to
public/usage.json, and close the session.

The script does not read credential files or call service APIs directly. It
only types commands and reads their output. A fresh session prevents stale
values from being reused.

Usage:
  python3 scrape.py           # Run continuously
  python3 scrape.py --once    # Scrape once and print results for debugging
Environment variables:
  TW_INTERVAL   Seconds between scrapes; default: 300
  TW_BOOT_WAIT  Seconds to wait after starting the CLI; default: 8
  TW_TOOLS      Tools to scrape; default: "claude,codex"
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PUBLIC = BASE / "public"
OUT = PUBLIC / "usage.json"
PROBE_DIR = BASE / "probe"          # Start the CLIs here to avoid touching other projects.
INTERVAL = int(os.environ.get("TW_INTERVAL", "300"))
BOOT_WAIT = int(os.environ.get("TW_BOOT_WAIT", "8"))
RENDER_TIMEOUT = 20


# ---------- Parsing ----------

def _window(name, used, resets):
    return {"name": name, "used": max(0, min(100, used)), "resets": resets.strip()}


def parse_claude(text):
    """Parse Claude Code's Usage page: '7% used' and 'Resets 6pm (America/New_York)'."""
    s = re.search(r"Current session.*?(\d+)% used.*?Resets\s+([^\n(│]+)", text, re.S)
    w = re.search(r"Current week.*?(\d+)% used.*?Resets\s+([^\n(│]+)", text, re.S)
    if not (s and w):
        return None
    return [_window("5h", int(s[1]), s[2]), _window("week", int(w[1]), w[2])]


def parse_codex(text):
    """Parse Codex /status and convert '80% left' to a percentage used."""
    s = re.search(r"5h limit:.*?(\d+)% left.*?\(resets ([^)]+)\)", text, re.S)
    w = re.search(r"Weekly limit:.*?(\d+)% left.*?\(resets ([^)]+)\)", text, re.S)
    if not (s and w):
        return None
    return [_window("5h", 100 - int(s[1]), s[2]), _window("week", 100 - int(w[1]), w[2])]


TOOLS = [
    {"id": "claude", "label": "Claude", "bin": "claude", "command": "/usage", "parse": parse_claude},
    {"id": "codex", "label": "Codex", "bin": "codex", "command": "/status", "parse": parse_codex},
]


# ---------- tmux ----------

def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def scrape(tool):
    sess = f"tw_{tool['id']}"
    tmux("kill-session", "-t", sess)
    r = tmux("new-session", "-d", "-s", sess, "-x", "160", "-y", "60",
             "-c", str(PROBE_DIR), tool["bin"])
    if r.returncode:
        raise RuntimeError(f"tmux failed to start: {r.stderr.strip()}")

    screen = ""
    try:
        time.sleep(BOOT_WAIT)
        for _ in range(2):                       # Retry if the first command produces no result.
            tmux("send-keys", "-t", sess, "-l", tool["command"])
            time.sleep(0.5)
            tmux("send-keys", "-t", sess, "Enter")
            deadline = time.time() + RENDER_TIMEOUT
            while time.time() < deadline:
                time.sleep(1)
                screen = tmux("capture-pane", "-p", "-J", "-t", sess).stdout
                result = tool["parse"](screen)
                if result:
                    return result
            tmux("send-keys", "-t", sess, "Escape")

        if "trust" in screen.lower():
            raise RuntimeError(f"{tool['bin']} is waiting for you to trust the probe directory. "
                               f"Run {tool['bin']} once in {PROBE_DIR} and confirm it manually.")
        raise RuntimeError("Usage numbers were not found. The captured screen was saved in probe/last_*.txt")
    finally:
        (PROBE_DIR / f"last_{tool['id']}.txt").write_text(screen)
        tmux("kill-session", "-t", sess)


# ---------- State file ----------

def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def load_state():
    try:
        return json.loads(OUT.read_text())
    except (OSError, ValueError):
        return {"services": {}}


def write_state(state):
    tmp = BASE / ".usage.json.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(tmp, OUT)                          # Atomic replacement prevents partial reads.


def run_once(state, tools):
    for t in tools:
        svc = state["services"].setdefault(t["id"], {"windows": None, "fetched": None})
        svc["label"] = t["label"]
        svc["checked"] = now()
        try:
            svc["windows"] = scrape(t)
            svc["fetched"] = svc["checked"]
            svc["error"] = None
        except Exception as e:                    # Keep the last good data if a scrape fails.
            svc["error"] = str(e)
        state["updated"] = now()
        state["interval"] = INTERVAL
        write_state(state)
        print(f"[{svc['checked']}] {t['id']}: {svc['error'] or svc['windows']}", flush=True)


def main():
    if not shutil.which("tmux"):
        sys.exit("需要 tmux：brew install tmux")
    PUBLIC.mkdir(exist_ok=True)
    PROBE_DIR.mkdir(exist_ok=True)

    wanted = os.environ.get("TW_TOOLS", "claude,codex").split(",")
    tools = []
    for t in TOOLS:
        if t["id"] not in wanted:
            continue
        if shutil.which(t["bin"]):
            tools.append(t)
        else:
            print(f"Skipping {t['id']}: {t['bin']} was not found in PATH", flush=True)
    if not tools:
        sys.exit("no usable tools")

    state = load_state()
    if "--once" in sys.argv:
        run_once(state, tools)
        return
    while True:
        run_once(state, tools)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
