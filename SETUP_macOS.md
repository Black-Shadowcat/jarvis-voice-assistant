# JARVIS Setup Guide (macOS)

Dein persönlicher KI-Assistent — optimiert für macOS.

**Was du bekommst:**
- `Cmd+Shift+J` → dein komplettes Arbeits-Setup startet automatisch
- JARVIS begrüßt dich mit Wetter, Aufgaben und Kalender
- Du sprichst mit JARVIS — er antwortet per Stimme
- JARVIS steuert deinen Browser (suchen, Seiten öffnen)
- JARVIS sieht deinen Bildschirm und beschreibt ihn
- JARVIS schaltet Lichter via Home Assistant
- Mic-Mute-Button in der macOS Menüleiste
- **Config UI** im Browser — alle Einstellungen ohne Texteditor

---

## Voraussetzungen

| Anforderung | Version / Hinweis |
|---|---|
| macOS | 14+ (Sonoma oder neuer) |
| Python | 3.11 via Homebrew |
| Google Chrome | Aktuell (für Web Speech API) |
| Claude Code | Installiert (für Setup-Hilfe) |

---

## Installation

### 1. Homebrew & Python

```bash
# Python 3.11 (falls noch nicht installiert)
brew install python@3.11

# Pfad prüfen
which python3.11
# → /opt/homebrew/bin/python3.11
```

### 2. Dependencies installieren

```bash
pip3.11 install -r requirements.txt

# Playwright Browser
playwright install chromium
```

> **Hinweis:** `rumps` (für den Mic-Mute Menüleisten-Button) ist ebenfalls in `requirements.txt` enthalten.

### 3. config.json erstellen

```bash
cp config.example.json config.json
```

Bearbeite `config.json` mit deinen Daten. Alle verfügbaren Felder:

```json
{
  "anthropic_api_key": "sk-ant-...",
  "elevenlabs_api_key": "sk_...",
  "elevenlabs_voice_id": "rDmv3mOhK6TnhYWckFaD",
  "user_name": "Matthias",
  "user_address": "Sir",
  "city": "Hamburg",
  "lat": 53.55,
  "lon": 10.00,
  "kachelmann_api_key": "...",
  "ha_url": "http://10.0.0.190:8123",
  "ha_token": "eyJhbGci...",
  "ha_enabled": true,
  "workspace_path": "/Users/matthias/jarvis-voice-assistant",
  "spotify_track": "spotify:track:...",
  "browser_url": "https://your-website.com",
  "obsidian_inbox_path": "/Users/matthias/Documents/Obsidian/Inbox",
  "apps": ["Mail", "Safari", "Visual Studio Code", "Music"]
}
```

| Feld | Pflicht | Beschreibung |
|---|---|---|
| `anthropic_api_key` | ✅ | Claude Haiku API Key |
| `elevenlabs_api_key` | ✅ | ElevenLabs TTS Key |
| `elevenlabs_voice_id` | ✅ | Voice ID für TTS |
| `user_name` | ✅ | Dein Name (für Begrüßung) |
| `user_address` | ✅ | Anrede (z.B. "Sir", "Chef") |
| `city` | ✅ | Stadt (für Wetteransage) |
| `lat` / `lon` | ✅ | GPS-Koordinaten (Kachelmann) |
| `kachelmann_api_key` | ⚡ | Wetter-API (kachelmannwetter.com) |
| `ha_url` | ⚡ | Home Assistant URL |
| `ha_token` | ⚡ | HA Long-Lived Access Token |
| `ha_enabled` | ⚡ | HA-Integration aktiviert (true/false) |
| `workspace_path` | ✅ | Absoluter Pfad zum Projektordner |
| `spotify_track` | ⚡ | Spotify Track URI beim Start |
| `browser_url` | ⚡ | Start-URL im Browser |
| `obsidian_inbox_path` | ⚡ | Pfad zur Obsidian Inbox |
| `apps` | ✅ | Apps die beim Start geöffnet werden |

✅ = Erforderlich &nbsp; ⚡ = Optional

---

## Config UI (empfohlen)

Statt `config.json` manuell zu bearbeiten, nutze die eingebaute **Config UI**:

```bash
# Server starten (falls nicht läuft)
python3.11 server.py

# Browser öffnen
open http://localhost:8340/config
```

Die Config UI bietet:
- **API Key Test-Buttons** — prüft Anthropic & ElevenLabs direkt
- **Voice-Dropdown** — alle verfügbaren ElevenLabs Voices auswählen
- **Voice Preview** — neue Stimme direkt anhören
- **Home Assistant Toggle** — HA-Integration ein-/ausschalten
- **Alle Felder** strukturiert in Karten mit Labels
- **Sofort wirksam** — nach Speichern keine Server-Neustart nötig

> API Keys werden als Passwortfelder dargestellt (👁 zum Anzeigen). Änderungen werden direkt in `config.json` gespeichert und im laufenden Server übernommen.

---

## Starten

### Option A: Sofort-Start

```bash
python3.11 scripts/keyboard-trigger-macos.py
```

Startet Server, öffnet JARVIS im Chrome App-Modus und alle konfigurierten Apps.

### Option B: Launch Script (empfohlen)

```bash
./scripts/launch-session.sh
```

Vollständiger Start mit:
- FastAPI Server
- Chrome im App-Modus (kein Tab-/Adressleiste)
- Konfigurierte Apps
- Window-Arrangement (4 Quadranten)
- Mic-Mute-Button in der Menüleiste

### Option C: Nur Server

```bash
python3.11 server.py
# Dann im Browser: http://localhost:8340
```

---

## macOS Berechtigungen

### Accessibility (Pflicht für Hotkeys)

```
System Settings → Privacy & Security → Accessibility
→ Terminal (oder deine App) hinzufügen
```

### Screen Recording (für "Was siehst du?" Feature)

```
System Settings → Privacy & Security → Screen Recording
→ Terminal hinzufügen
```

### Mic-Mute Menüleisten-Button

`scripts/mic-mute-menubar.py` zeigt ein 🎙️-Symbol in der macOS Menüleiste.  
Klick → Mikrofon stummschalten/aktivieren.

```bash
# Manuell starten (wird von launch-session.sh automatisch gestartet)
python3.11 scripts/mic-mute-menubar.py
```

---

## Launchd Auto-Start (Optional)

JARVIS automatisch bei macOS-Login starten:

**1. Plist erstellen** (`~/Library/LaunchAgents/com.jarvis.launcher.plist`):

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
        <string>/Users/DEIN_USERNAME/jarvis-voice-assistant/scripts/keyboard-trigger-macos.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/jarvis-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/jarvis-launchd-err.log</string>
</dict>
</plist>
```

> Ersetze `DEIN_USERNAME` mit deinem macOS-Benutzernamen (`whoami`).

**2. Aktivieren:**

```bash
launchctl load ~/Library/LaunchAgents/com.jarvis.launcher.plist

# Deaktivieren:
launchctl unload ~/Library/LaunchAgents/com.jarvis.launcher.plist
```

---

## Troubleshooting

### Server startet nicht / Port belegt

```bash
# Prüfen welcher Prozess Port 8340 belegt
lsof -i :8340

# Prozess beenden
kill <PID>

# Server manuell starten
python3.11 server.py
```

### "keyboard" Module Fehler

```bash
pip3.11 install keyboard
# Eventuell Accessibility-Berechtigung erforderlich (siehe oben)
```

### `rumps` nicht gefunden (Mic-Mute Button)

```bash
pip3.11 install rumps
```

### Config UI nicht erreichbar

```bash
# Server läuft?
curl http://localhost:8340
# → Gibt HTML zurück wenn OK

# Config UI direkt
open http://localhost:8340/config
```

### Voice Preview funktioniert nicht

Prüfe den ElevenLabs API Key in der Config UI (Test-Button). Stelle sicher, dass `elevenlabs_voice_id` gesetzt ist.

### Browser öffnet nicht im App-Modus

```bash
# Chrome-Pfad prüfen
ls /Applications/Google\ Chrome.app/Contents/MacOS/
```

### Screen Capture funktioniert nicht

```
System Settings → Privacy & Security → Screen Recording
→ Terminal hinzufügen → Neustart der App
```

### Home Assistant antwortet nicht

Prüfe `ha_url` und `ha_token` in der Config UI. Der HA Token muss ein **Long-Lived Access Token** sein (HA → Profil → Long-Lived Access Tokens).

---

## Projektstruktur

```
jarvis-voice-assistant/
├── server.py                    # FastAPI Backend (Haupt-Server)
├── browser_tools.py             # Playwright Browser-Steuerung
├── screen_capture.py            # Screenshot + Claude Vision
├── requirements.txt             # Python Dependencies
├── config.json                  # Deine Config (gitignored)
├── config.example.json          # Template
├── frontend/
│   ├── index.html               # JARVIS Haupt-UI (Orb)
│   ├── config.html              # Config UI (http://localhost:8340/config)
│   ├── main.js                  # Speech Recognition + WebSocket
│   └── style.css                # Dark Theme
└── scripts/
    ├── launch-session.sh        # Vollständiger Start (empfohlen)
    ├── keyboard-trigger-macos.py # Sofort-Start Script
    └── mic-mute-menubar.py      # Menüleisten Mic-Mute Button
```

---

## API Keys besorgen

| Service | Link | Kosten |
|---|---|---|
| Anthropic (Claude) | console.anthropic.com | ~$0.25 / 1M Tokens |
| ElevenLabs (TTS) | elevenlabs.io | Free: 10k Zeichen/Monat |
| Kachelmann Wetter | kachelmannwetter.com/api | Kostenloser Tier verfügbar |

---

## Commands Übersicht

```bash
# Server starten
python3.11 server.py

# Config UI öffnen
open http://localhost:8340/config

# Session starten (empfohlen)
./scripts/launch-session.sh

# Keyboard Trigger
python3.11 scripts/keyboard-trigger-macos.py

# Mic-Mute Menüleiste
python3.11 scripts/mic-mute-menubar.py

# Server-Logs prüfen
tail -f /tmp/jarvis-server.log
```

---

## Support

Bei Problemen:
1. Config UI aufrufen: `http://localhost:8340/config` — API Keys testen
2. Server-Log prüfen: `tail -f /tmp/jarvis-server.log`
3. `config.json` prüfen (keine Kommas am Ende!)
4. Python-Pfad prüfen: `/opt/homebrew/bin/python3.11`
5. macOS-Berechtigungen prüfen (Accessibility, Screen Recording)
