# JARVIS Setup Guide (macOS)

Dein persönlicher KI-Assistent — optimiert für macOS.

**Was du bekommst:**
- `Cmd+Shift+J` → dein komplettes Arbeits-Setup startet
- JARVIS begrüßt dich mit Wetter und deinen Aufgaben
- Du sprichst mit JARVIS — er antwortet per Stimme
- JARVIS kann deinen Browser steuern (suchen, Seiten öffnen)
- JARVIS kann deinen Bildschirm sehen und beschreiben

---

## Voraussetzungen

- **macOS 14+** (Sonoma oder neuer)
- **Mac Mini M4** oder vergleichbar
- **Python 3.11** via Homebrew
- **Google Chrome** (für Spracheingabe + JARVIS UI)
- **Claude Code** installiert

---

## Installation

### 1. Homebrew Dependencies installieren

```bash
# Python 3.11 (falls noch nicht installiert)
brew install python@3.11

# Dependencies
pip3.11 install -r requirements.txt

# Playwright Browser
playwright install chromium
```

### 2. Python-Pfad verifizieren

```bash
which python3.11
# Sollte zeigen: /opt/homebrew/bin/python3.11
```

### 3. config.json erstellen

Kopiere `config.example.json` und passe sie an:

```bash
cp config.example.json config.json
```

Bearbeite `config.json` mit deinen API-Keys:

```json
{
  "anthropic_api_key": "sk-ant-...",
  "elevenlabs_api_key": "...",
  "elevenlabs_voice_id": "rDmv3mOhK6TnhYWckFaD",
  "user_name": "Matthias",
  "user_address": "Sir",
  "city": "Hamburg",
  "workspace_path": "/Users/matthiasschreiber/jarvis-voice-assistant",
  "spotify_track": "spotify:track:...",
  "browser_url": "https://skool.com/...",
  "apps": ["Mail", "Safari", "Visual Studio Code", "Music"]
}
```

---

## Starten

### Option A: Keyboard Trigger (Cmd+Shift+J)

```bash
python3.11 scripts/keyboard-trigger-macos.py
```

Drücke `Cmd+Shift+J` um die Session zu starten.

### Option B: Launch Script

```bash
./scripts/launch-session.sh
```

---

## macOS-Specific Setup

### Global Hotkey aktivieren

Der Keyboard Trigger nutzt die `keyboard` Library, welche System-Zugriff benötigt:

```bash
# Eventuell erforderlich für Accessibility-Zugriff
# System Settings → Privacy & Security → Accessibility
# → Python hinzufügen falls nötig
```

### Launchd Auto-Start (Optional)

Für automatischen Start bei Login:

1. Erstelle `~/Library/LaunchAgents/com.jarvis.launcher.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.launcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/python3.11</string>
        <string>/Users/matthiasschreiber/jarvis-voice-assistant/scripts/keyboard-trigger-macos.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

2. Aktivieren:

```bash
launchctl load ~/Library/LaunchAgents/com.jarvis.launcher.plist
```

---

## Troubleshooting

### "keyboard" Module Fehler

```bash
pip3.11 install keyboard
```

### Server startet nicht

```bash
# Prüfen ob Port 8340 belegt
lsof -i :8340

# Server manuell starten
python3.11 server.py
```

### Browser öffnet nicht

```bash
# Chrome als Standard setzen
open -a "Google Chrome" --args --make-default-browser
```

### Screen Capture funktioniert nicht

```bash
# Screen Recording Permission erforderlich
# System Settings → Privacy & Security → Screen Recording
# → Terminal hinzufügen
```

---

## Getestete Apps

| App | Funktion |
|-----|-----------|
| Mail | E-Mail Client |
| Safari | Browser |
| Visual Studio Code | Code Editor |
| Music | Apple Music |
| Spotify | Musik-Player |

---

## Commands

```bash
# Server starten
python3.11 server.py

# Keyboard Trigger starten
python3.11 scripts/keyboard-trigger-macos.py

# Launch Session
./scripts/launch-session.sh

# Git Status
git status
```

---

## Support

Bei Problemen:
1. Prüfe `config.json` (keine trailing commas!)
2. Prüfe Python-Pfad: `/opt/homebrew/bin/python3.11`
3. Prüfe API-Keys in der Anthropic Console