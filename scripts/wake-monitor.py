#!/opt/homebrew/bin/python3.11
"""Monitors macOS wake-from-sleep events and notifies the Jarvis server."""
import subprocess
import urllib.request
import time
import sys

JARVIS_WAKE_URL = "http://localhost:8340/api/wake"


def is_screen_locked() -> bool:
    """Returns True if the screen is currently locked."""
    try:
        r = subprocess.run(
            ["ioreg", "-n", "Root", "-d1"],
            capture_output=True, text=True, timeout=5,
        )
        return "CGSSessionScreenIsLocked = 1" in r.stdout
    except Exception:
        return False


def wait_for_unlock(timeout: int = 120) -> bool:
    """Blocks until screen is unlocked. Returns False if timeout exceeded."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_screen_locked():
            return True
        time.sleep(2)
    return False


def notify_jarvis():
    unlocked = wait_for_unlock()
    if not unlocked:
        print("[wake-monitor] Timeout — Screen blieb gesperrt, kein Brief", flush=True)
        return

    # Small buffer after unlock so audio system is ready
    time.sleep(3)

    for attempt in range(6):
        try:
            req = urllib.request.Request(JARVIS_WAKE_URL, method="POST")
            req.add_header("Content-Type", "application/json")
            urllib.request.urlopen(req, data=b"{}", timeout=5)
            print(f"[wake-monitor] Jarvis benachrichtigt", flush=True)
            return
        except Exception as e:
            print(f"[wake-monitor] Versuch {attempt + 1}: {e}", flush=True)
            time.sleep(5)


COOLDOWN = 120  # seconds — macOS logs multiple "Wake reason" lines per wake event

proc = subprocess.Popen(
    ["log", "stream", "--predicate", 'eventMessage contains "Wake reason"', "--style", "compact"],
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
)

print("[wake-monitor] Überwache System-Wake-Events...", flush=True)

last_wake = 0.0
for line in proc.stdout:
    if "Wake reason" in line:
        now = time.time()
        if now - last_wake < COOLDOWN:
            continue
        last_wake = now
        print(f"[wake-monitor] Wake erkannt: {line.strip()}", flush=True)
        notify_jarvis()
