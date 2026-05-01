#!/bin/zsh
# JARVIS — Launch Session (macOS)
# Starts FastAPI server, browser, and configured apps

# Give the desktop time to fully initialize when launched at login
sleep 8

# Get the directory where this script is located
SCRIPT_DIR="${0:A:h}"
WORKSPACE_PATH="$(dirname "$SCRIPT_DIR")"

# Load config if exists
CONFIG_FILE="$WORKSPACE_PATH/config.json"
if [[ -f "$CONFIG_FILE" ]]; then
    # Extract values using python (more reliable than parsing JSON in shell)
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
echo "[1/4] Starting FastAPI server..."
if is_server_running; then
    echo "  → Server already running at $SERVER_URL"
else
    cd "$WORKSPACE_PATH"
    nohup /opt/homebrew/bin/python3.11 server.py > /tmp/jarvis-server.log 2>&1 &
    SERVER_PID=$!
    echo "  → Server started (PID: $SERVER_PID)"
    
    # Wait for server to be ready
    echo "  → Waiting for server..."
    for i in {1..10}; do
        sleep 1
        if is_server_running; then
            echo "  → Server ready!"
            break
        fi
        if [[ $i -eq 10 ]]; then
            echo "  → Warning: Server may not be ready"
        fi
    done
fi

# 2. Open Jarvis in Chrome app mode (no address bar, tabs or browser chrome)
# Use binary directly — "open -a" ignores --args when Chrome is already running
echo "[2/4] Opening Jarvis in Chrome app mode..."
nohup /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --app=http://localhost:8340 \
    --autoplay-policy=no-user-gesture-required \
    --user-data-dir="$HOME/.jarvis-chrome-profile" > /dev/null 2>&1 &
echo "  → Chrome app mode opened"

# 3. Open configured apps
echo "[3/5] Opening apps..."
if [[ -n "$APPS" ]]; then
    # Split comma-separated apps
    APP_ARRAY=(${(s:,:)APPS})
    for app in "${APP_ARRAY[@]}"; do
        echo "  → Opening: $app"
        open -a "$app" 2>/dev/null || open "/System/Applications/${app}.app" 2>/dev/null
    done
else
    # Default apps
    echo "  → Opening default apps: Mail, Safari, VS Code, Music"
    open -a "Mail"
    open -a "Safari"
    open -a "Visual Studio Code"
    open -a "Music"
fi

# 4. Arrange windows in 4 equal quadrants
echo "[4/5] Arranging windows..."
sleep 4
osascript << 'APPLESCRIPT'
-- Position Chrome app-mode window (URL already set via --app flag)
tell application "System Events" to tell process "Google Chrome"
    set retries to 0
    repeat while (count of windows) = 0 and retries < 20
        delay 0.5
        set retries to retries + 1
    end repeat
    if (count of windows) > 0 then
        set size of front window to {959, 579}
        set position of front window to {0, 30}
    end if
end tell

tell application "System Events" to tell process "Code"
    set size of front window to {959, 579}
    set position of front window to {961, 30}
end tell

tell application "Mail" to activate
delay 0.3
tell application "System Events" to tell process "Mail"
    set size of front window to {959, 580}
    set position of front window to {0, 611}
end tell

tell application "Home Assistant" to activate
delay 0.3
tell application "System Events" to tell process "Home Assistant"
    set size of front window to {959, 580}
    set position of front window to {961, 611}
end tell
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
echo "Server: $SERVER_URL"
echo ""
echo "Press Ctrl+C to stop server (optional)"