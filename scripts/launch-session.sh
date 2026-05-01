#!/bin/zsh
# JARVIS — Launch Session (macOS)
# Starts FastAPI server, browser, and configured apps

# Give the desktop/windowserver time to fully initialize when launched at login
sleep 12

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
    APPS=$(python3.11 -c "import json; c=json.load(open('$CONFIG_FILE')); print(','.join(c.get('apps',[])))" 2>/dev/null)
else
    echo "[jarvis] Warning: config.json not found, using defaults"
    SPOTIFY_TRACK=""
    BROWSER_URL=""
    APPS=""
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

JARVIS_PREF="$JARVIS_PROFILE/Default/Preferences"
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
    echo "  → Chrome profile crash-state cleared"
fi

# Kill any stale JARVIS Chrome instance from previous session
pkill -f "jarvis-chrome-profile" 2>/dev/null
sleep 1

# Launch Chrome — binary directly so flags work even when Chrome is already open
nohup "$CHROME_BIN" \
    --app=http://localhost:8340 \
    --autoplay-policy=no-user-gesture-required \
    --user-data-dir="$JARVIS_PROFILE" \
    --window-size=959,579 \
    --window-position=0,30 \
    --force-dark-mode \
    --no-first-run \
    --disable-restore-session-state \
    --no-default-browser-check > /tmp/jarvis-chrome.log 2>&1 &
CHROME_PID=$!
echo "  → Chrome launched (PID: $CHROME_PID)"

# Wait and verify Chrome is actually running — retry once if it died
sleep 4
if ! pgrep -f "jarvis-chrome-profile" > /dev/null 2>&1; then
    echo "  → Chrome did not start — retrying in 3s..."
    sleep 3
    nohup "$CHROME_BIN" \
        --app=http://localhost:8340 \
        --autoplay-policy=no-user-gesture-required \
        --user-data-dir="$JARVIS_PROFILE" \
        --window-size=959,579 \
        --window-position=0,30 \
        --force-dark-mode \
        --no-first-run \
        --disable-restore-session-state \
        --no-default-browser-check > /tmp/jarvis-chrome.log 2>&1 &
    echo "  → Chrome retry launched (PID: $!)"
    sleep 3
else
    echo "  → Chrome running OK"
fi

# 3. Open configured apps
echo "[3/5] Opening apps..."
if [[ -n "$APPS" ]]; then
    APP_ARRAY=(${(s:,:)APPS})
    for app in "${APP_ARRAY[@]}"; do
        echo "  → Opening: $app"
        open -a "$app" 2>/dev/null || open "/System/Applications/${app}.app" 2>/dev/null
    done
else
    echo "  → Opening default apps: Mail, VS Code, Music"
    open -a "Mail"
    open -a "Visual Studio Code"
    open -a "Music"
fi

# 4. Arrange windows in 4 equal quadrants
echo "[4/5] Arranging windows..."
sleep 5
osascript << 'APPLESCRIPT'
-- VS Code → top right
tell application "System Events" to tell process "Code"
    set size of front window to {959, 579}
    set position of front window to {961, 30}
end tell

-- Mail → bottom left
tell application "Mail" to activate
delay 0.3
tell application "System Events" to tell process "Mail"
    set size of front window to {959, 580}
    set position of front window to {0, 611}
end tell

-- Home Assistant → bottom right
try
    tell application "Home Assistant" to activate
    delay 0.3
    tell application "System Events" to tell process "Home Assistant"
        set size of front window to {959, 580}
        set position of front window to {961, 611}
    end tell
end try

-- JARVIS Chrome → top left (bring to front)
delay 0.5
try
    tell application "System Events"
        set jarvisProcs to (every process whose name is "Google Chrome" and (exists window 1))
        repeat with p in jarvisProcs
            try
                set frontmost of p to true
            end try
        end repeat
    end tell
end try
APPLESCRIPT
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
