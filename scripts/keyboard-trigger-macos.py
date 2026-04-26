#!/usr/bin/env /opt/homebrew/bin/python3.11
"""
JARVIS — Keyboard Trigger (macOS)
Startet JARVIS Session mit F5 oder via launch-session.sh

- Starts FastAPI server if not running
- Opens browser to http://localhost:8340
- Opens configured apps (Mail, Safari, VS Code, Apple Music)
"""

import subprocess
import time
import os
import sys
import json
import signal
import webbrowser

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

WORKSPACE_PATH = config.get("workspace_path", os.path.dirname(os.path.dirname(__file__)))
SERVER_URL = "http://localhost:8340"


def is_server_running():
    """Check if FastAPI server is already running."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 8340))
    sock.close()
    return result == 0


def start_server():
    """Start the FastAPI server in background."""
    server_path = os.path.join(WORKSPACE_PATH, "server.py")
    print(f"[jarvis] Starting FastAPI server...", flush=True)
    subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    for _ in range(10):
        time.sleep(1)
        if is_server_running():
            print(f"[jarvis] Server running at {SERVER_URL}", flush=True)
            return True
    print("[jarvis] Warning: Server may not have started properly", flush=True)
    return False


def open_browser():
    """Open default browser to JARVIS UI."""
    print(f"[jarvis] Opening browser: {SERVER_URL}", flush=True)
    webbrowser.open(SERVER_URL)


def open_apps(config):
    """Open configured applications."""
    apps = config.get("apps", [])
    
    if not apps:
        apps = ["Mail", "Safari", "Visual Studio Code", "Music"]
    
    for app in apps:
        print(f"[jarvis] Opening: {app}", flush=True)
        try:
            subprocess.run(["open", "-a", app], check=False)
        except Exception as e:
            print(f"[jarvis] Could not open {app}: {e}", flush=True)


def trigger_jarvis():
    """Start the JARVIS session."""
    print("\n[jarvis] Starting session...", flush=True)
    
    if not is_server_running():
        start_server()
    
    open_browser()
    open_apps(config)
    
    print("[jarvis] Session started!", flush=True)


def main():
    print("=" * 50)
    print("JARVIS Keyboard Trigger (macOS)")
    print("=" * 50)
    print(f"Workspace: {WORKSPACE_PATH}")
    print("=" * 50)
    print("\n[Option A] Starte sofort mit:")
    print("  python3.11 scripts/keyboard-trigger-macos.py")
    print("\n[Option B] Oder nutze Launch Script:")
    print("  ./scripts/launch-session.sh")
    print("\n[Option C] Automatisch bei Login (Launchd):")
    print("  Siehe SETUP_macOS.md")
    print("\nDrücke Ctrl+C zum Beenden.\n")
    
    # Register signal handler
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    
    # Start the session immediately
    print("[jarvis] Starte Session...")
    trigger_jarvis()
    
    # Keep running
    print("\n[jarvis] Warte... (Strg+C zum Beenden)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[jarvis] Beendet.")
        sys.exit(0)


if __name__ == "__main__":
    main()