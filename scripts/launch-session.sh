#!/bin/zsh
# JARVIS — Launch Session (macOS)
# Starts FastAPI server, browser, and configured apps

# Wait until macOS is truly ready — Dock + Finder running = UI fully initialised.
# A fixed sleep is unreliable; GPU/WindowServer may not be ready even after 12s.
echo "[boot] Waiting for macOS to be fully ready..."
until pgrep -x "Dock" > /dev/null 2>&1 && pgrep -x "Finder" > /dev/null 2>&1; do
    sleep 3
done

# On a cold boot the GPU/WindowServer stack needs time to settle.
# If the system has been running for more than 2 minutes (manual Cmd+Shift+J),
# skip the long wait entirely.
BOOT_TIME=$(sysctl -n kern.boottime | awk '{print $4}' | tr -d ',')
UPTIME_SECS=$(( $(date +%s) - BOOT_TIME ))
if [[ $UPTIME_SECS -lt 120 ]]; then
    echo "[boot] Fresh boot (${UPTIME_SECS}s uptime) — waiting 20s for GPU/display stack..."
    sleep 20
else
    echo "[boot] System running (${UPTIME_SECS}s uptime) — skipping GPU wait"
    sleep 2
fi

# Get the directory where this script is located
SCRIPT_DIR="${0:A:h}"
WORKSPACE_PATH="$(dirname "$SCRIPT_DIR")"
CHROME_BIN="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
JARVIS_PROFILE="$HOME/.jarvis-chrome-profile"

# Load config if exists
CONFIG_FILE="$WORKSPACE_PATH/config.json"
if [[ -f "$CONFIG_FILE" ]]; then
    SPOTIFY_TRACK=$(python3.11 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c.get('spotify_track',''))" 2>/dev/null)
    BROWSER_URL=$(python3.11 -c "import json; c=json.load(open('$CONFIG_FILE')); print(c.get('browser_url',''))" 2>/dev/null)
    PROGRAMS=$(python3.11 -c "import json; c=json.load(open('$CONFIG_FILE')); print(','.join([p for p in c.get('programs',[]) if p]))" 2>/dev/null)
else
    echo "[jarvis] Warning: config.json not found, using defaults"
    SPOTIFY_TRACK=""
    BROWSER_URL=""
    PROGRAMS=""
fi

SERVER_URL="http://localhost:8340"

echo "========================================"
echo "JARVIS Launch Session (macOS)"
echo "========================================"
echo "Workspace: $WORKSPACE_PATH"
echo ""

# Function to check if server is running
is_server_running() {
    curl -s -o /dev/null -w "%{http_code}" "$SERVER_URL" 2>/dev/null | grep -q "200" && return 0 || return 1
}

# 1. Start FastAPI server if not running
echo "[1/5] Starting FastAPI server..."
if is_server_running; then
    echo "  → Server already running at $SERVER_URL"
else
    cd "$WORKSPACE_PATH"
    nohup /opt/homebrew/bin/python3.11 server.py > /tmp/jarvis-server.log 2>&1 &
    SERVER_PID=$!
    echo "  → Server started (PID: $SERVER_PID)"

    echo "  → Waiting for server..."
    for i in {1..15}; do
        sleep 1
        if is_server_running; then
            echo "  → Server ready!"
            break
        fi
        if [[ $i -eq 15 ]]; then
            echo "  → Warning: Server may not be ready"
        fi
    done
fi

# 2. Open Jarvis in Chrome app mode
# Reset Chrome crash-state first — after a system restart Chrome marks the
# profile as "crashed", which shows a restore-dialog instead of the JARVIS URL.
echo "[2/5] Opening Jarvis in Chrome app mode..."

JARVIS_DEFAULT="$JARVIS_PROFILE/Default"
JARVIS_PREF="$JARVIS_DEFAULT/Preferences"

# Clear corrupted caches — root cause of GPU crash + window closing
rm -rf "$JARVIS_DEFAULT/Cache" \
       "$JARVIS_DEFAULT/Code Cache" \
       "$JARVIS_DEFAULT/GPUCache" \
       "$JARVIS_DEFAULT/blob_storage" 2>/dev/null
echo "  → Chrome cache cleared"

# Reset crash-state so Chrome skips the restore-pages dialog
if [[ -f "$JARVIS_PREF" ]]; then
    /opt/homebrew/bin/python3.11 - <<PYEOF 2>/dev/null
import json
with open("$JARVIS_PREF", "r") as f:
    p = json.load(f)
p.setdefault("profile", {})["exit_type"] = "Normal"
p.setdefault("profile", {})["exited_cleanly"] = True
with open("$JARVIS_PREF", "w") as f:
    json.dump(p, f)
PYEOF
    echo "  → Chrome crash-state cleared"
fi

# Kill any stale JARVIS Chrome instance from previous session
pkill -f "jarvis-chrome-profile" 2>/dev/null
sleep 1

# Launch Chrome via macOS Launch Services — 'open' gives Chrome the correct
# GUI bootstrap context that launchd-started processes don't inherit directly.
open -na "Google Chrome" --args \
    --app=http://localhost:8340 \
    --autoplay-policy=no-user-gesture-required \
    --user-data-dir="$JARVIS_PROFILE" \
    --window-size=959,579 \
    --window-position=0,30 \
    --no-first-run \
    --disable-restore-session-state \
    --no-default-browser-check \
    --disable-gpu \
    --in-process-gpu
echo "  → Chrome gestartet via Launch Services"

# Wait for Chrome process to appear — 3s is enough on M4
sleep 3
if ! pgrep -f "jarvis-chrome-profile" > /dev/null 2>&1; then
    echo "  → Chrome nicht gestartet — retry..."
    sleep 3
    open -na "Google Chrome" --args \
        --app=http://localhost:8340 \
        --autoplay-policy=no-user-gesture-required \
        --user-data-dir="$JARVIS_PROFILE" \
        --window-size=959,579 \
        --window-position=0,30 \
            --no-first-run \
        --disable-restore-session-state \
        --no-default-browser-check \
        --disable-gpu \
        --in-process-gpu
    echo "  → Chrome retry gestartet"
    sleep 5
else
    echo "  → Chrome läuft"
fi

# 3. Open configured apps
echo "[3/5] Opening apps..."
if [[ -n "$PROGRAMS" ]]; then
    PROGRAM_ARRAY=(${(s:,:)PROGRAMS})
    for program in "${PROGRAM_ARRAY[@]}"; do
        echo "  → Opening: $program"
        open -a "$program" 2>/dev/null || open "/System/Applications/${program}.app" 2>/dev/null
    done
else
    echo "  → No programs configured in Config UI"
fi

# 4. Arrange windows in 4 equal quadrants
echo "[4/5] Arranging windows..."
sleep 3
/opt/homebrew/bin/python3.11 - <<'PYEOF'
import json, subprocess, sys

try:
    with open("config.json") as f:
        cfg = json.load(f)
except Exception as e:
    print(f"  Config lesen fehlgeschlagen: {e}", file=sys.stderr)
    sys.exit(0)

layout = cfg.get("window_layout", {
    "top_right":    "Visual Studio Code",
    "bottom_left":  "Mail",
    "bottom_right": "Home Assistant",
})

# AppleScript process name differs from app name for some apps
PROC = {
    "Visual Studio Code": "Code",
}

SLOTS = {
    "top_right":    (961, 30,  959, 579),
    "bottom_left":  (0,   611, 959, 580),
    "bottom_right": (961, 611, 959, 580),
}

parts = []
for slot, (x, y, w, h) in SLOTS.items():
    app = layout.get(slot, "")
    if not app:
        continue
    proc = PROC.get(app, app)
    parts.append(f"""try
    tell application "{app}" to activate
    delay 0.3
    tell application "System Events" to tell process "{proc}"
        set size of front window to {{{w}, {h}}}
        set position of front window to {{{x}, {y}}}
    end tell
end try""")

# JARVIS Chrome always top-left, bring to front last
parts.append("""delay 0.5
try
    tell application "System Events"
        set jarvisProcs to (every process whose name is "Google Chrome" and (exists window 1))
        repeat with p in jarvisProcs
            try
                set frontmost of p to true
            end try
        end repeat
    end tell
end try""")

r = subprocess.run(["osascript"], input="\n".join(parts), text=True, capture_output=True)
if r.returncode != 0:
    print(f"  AppleScript: {r.stderr[:200]}", file=sys.stderr)
PYEOF
echo "  → Windows arranged"

# 5. Start mic mute menu bar button
echo "[5/5] Starting mic mute button..."
if ! pgrep -f "mic-mute-menubar.py" > /dev/null; then
    nohup /opt/homebrew/bin/python3.11 "$SCRIPT_DIR/mic-mute-menubar.py" > /tmp/mic-mute.log 2>&1 &
    echo "  → Mic mute button started"
else
    echo "  → Mic mute button already running"
fi

echo ""
echo "========================================"
echo "JARVIS session started!"
echo "========================================"
echo "Server:  $SERVER_URL"
echo "Config:  $SERVER_URL/config"
echo ""
echo "Chrome log: /tmp/jarvis-chrome.log"
echo "Server log: /tmp/jarvis-server.log"
