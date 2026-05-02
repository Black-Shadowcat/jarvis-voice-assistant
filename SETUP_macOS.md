# JARVIS Setup Guide (macOS)

Dein persönlicher KI-Assistent — optimiert für macOS.

**Was du bekommst:**
- `Cmd+Shift+J` → dein komplettes Arbeits-Setup startet automatisch
- JARVIS begrüßt dich mit Wetter, Aufgaben und Kalender
- Du sprichst mit JARVIS — er antwortet per Stimme
- JARVIS steuert deinen Browser (suchen, Seiten öffnen)
- JARVIS sieht deinen Bildschirm und beschreibt ihn
- JARVIS schaltet Lichter via Home Assistant
- JARVIS schreibt Notizen direkt in deine Obsidian Inbox
- Automatischer Dark/Light Mode passend zur macOS-Systemeinstellung
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
  "obsidian_inbox_path": "/Users/matthias/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault/01 Inbox/Jarvis",
  "apps": ["Mail", "Visual Studio Code", "Home Assistant"],
  "window_layout": {
    "top_right":    "Visual Studio Code",
    "bottom_left":  "Mail",
    "bottom_right": "Home Assistant"
  }
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
| `obsidian_inbox_path` | ⚡ | Pfad zum Jarvis-Ordner in der Obsidian Inbox |
| `apps` | ✅ | Apps die beim Start geöffnet werden |
| `window_layout` | ⚡ | Fenster-Anordnung der 3 konfigurierbaren Quadranten |

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
- **Fenster-Anordnung** — visuelles 2×2 Raster, Quadranten per Dropdown zuweisen
- **Alle Felder** strukturiert in Karten mit Labels
- **Sofort wirksam** — nach Speichern kein Server-Neustart nötig

> API Keys werden als Passwortfelder dargestellt (👁 zum Anzeigen). Änderungen werden direkt in `config.json` gespeichert und im laufenden Server übernommen.

---

## Dark / Light Mode

JARVIS passt sich automatisch der macOS-Systemeinstellung an — kein manuelles Umschalten nötig. Sowohl die Haupt-UI als auch die Config UI reagieren live wenn macOS zwischen Hell und Dunkel wechselt (z.B. im Auto-Modus).

---

## Obsidian Integration

JARVIS kann Notizen direkt in deine Obsidian Inbox schreiben:

1. Erstelle einen Ordner in deiner Vault (z.B. `01 Inbox/Jarvis/`)
2. Trage den Pfad als `obsidian_inbox_path` in der Config UI ein
3. Sprich: *„Jarvis, notiere: ..."* oder *„Merke dir: ..."*

JARVIS erstellt eine `.md` Datei mit Zeitstempel als Dateiname. Obsidian zeigt die Notiz sofort in der Inbox an.

---

## Starten

### Option A: Hotkey (empfohlen im Alltag)

```
Cmd + Shift + J
```

Startet Server, öffnet JARVIS im Chrome App-Modus, alle Apps und arrangiert Fenster.

### Option B: Launch Script

```bash
./scripts/launch-session.sh
```

Vollständiger Start mit:
- FastAPI Server
- Chrome im App-Modus (via macOS Launch Services, kein Tab/Adressleiste)
- Konfigurierte Apps in konfigurierten Quadranten
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

## Launchd Auto-Start

JARVIS startet automatisch bei macOS-Login über zwei launchd-Jobs:

| Plist | Funktion |
|---|---|
| `com.jarvis.server.plist` | Server (KeepAlive — startet bei Absturz neu) |
| `com.jarvis.session.plist` | Session: Chrome + Apps + Fenster (einmalig bei Login) |

Die Session-Plist wartet auf Dock+Finder und schläft 20s — erst dann startet Chrome, damit der GPU-Stack vollständig bereit ist.

```bash
# Status prüfen
launchctl list | grep jarvis

# Neu laden (nach Änderung der Plist)
launchctl unload ~/Library/LaunchAgents/com.jarvis.session.plist
launchctl load   ~/Library/LaunchAgents/com.jarvis.session.plist
```

---

## Troubleshooting

### Server startet nicht / Port belegt

```bash
lsof -i :8340
kill <PID>
python3.11 server.py
```

### Chrome öffnet sich nicht beim Autostart

Der Session-Job wartet auf Dock+Finder. Falls Chrome trotzdem nicht startet:
```bash
# Session manuell auslösen
./scripts/launch-session.sh

# Chrome-Log prüfen
cat /tmp/jarvis-chrome.log
```

### `rumps` nicht gefunden (Mic-Mute Button)

```bash
pip3.11 install rumps
```

### Config UI nicht erreichbar

```bash
curl http://localhost:8340   # → HTML wenn OK
open http://localhost:8340/config
```

### Obsidian Notiz wird nicht erstellt

1. `obsidian_inbox_path` in Config UI prüfen — muss absoluter Pfad sein
2. Prüfen ob der Ordner existiert: `ls "<pfad>"`
3. Server-Log: `tail -f /tmp/jarvis-server.log`

### Voice Preview funktioniert nicht

Prüfe den ElevenLabs API Key in der Config UI (Test-Button).

### Screen Capture funktioniert nicht

```
System Settings → Privacy & Security → Screen Recording → Terminal hinzufügen
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
├── config.example.json          # Template mit allen Feldern
├── frontend/
│   ├── index.html               # JARVIS Haupt-UI (Orb)
│   ├── config.html              # Config UI (http://localhost:8340/config)
│   ├── main.js                  # Speech Recognition + WebSocket
│   └── style.css                # Dark/Light Theme (CSS custom properties)
└── scripts/
    ├── launch-session.sh        # Vollständiger Start
    └── mic-mute-menubar.py      # Menüleisten Mic-Mute Button
```

---

## Alle Sprach-Actions

| Action | Trigger-Beispiele | Beschreibung |
|---|---|---|
| `SEARCH` | „Suche nach...", „Was ist..." | DuckDuckGo + Seite lesen |
| `OPEN` | „Öffne...", „Geh zu..." | URL im Browser öffnen |
| `SCREEN` | „Was siehst du?", „Schau auf..." | Bildschirm analysieren |
| `NEWS` | „Aktuelle Nachrichten" | Weltnachrichten laden |
| `REMINDER_ADD` | „Erinnere mich...", „Füge hinzu..." | Apple Reminders Inbox |
| `REMINDER_DONE` | „Erledigt: ...", „Abhaken..." | Reminder abhaken |
| `TASKS_LIST` | „Was steht an?", „Aufgaben?" | Reminders live laden |
| `MAIL_READ` | „Meine Mails", „Mail von..." | Ungelesene Mails / Inhalt |
| `KALENDER` | „Termine heute/diese Woche" | Kalender via Home Assistant |
| `LICHT` | „Licht an", „Wohnzimmer 50%" | Home Assistant Lichter |
| `NOTIZ` | „Notiere...", „Merke dir..." | Markdown-Datei in Obsidian Inbox |

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

# Session starten
./scripts/launch-session.sh

# Mic-Mute Menüleiste
python3.11 scripts/mic-mute-menubar.py

# Server-Logs prüfen
tail -f /tmp/jarvis-server.log

# Server neu starten (nach Code-Änderungen)
pkill -f "server.py"   # launchd KeepAlive startet ihn automatisch neu
```

---

## Support

Bei Problemen:
1. Config UI: `http://localhost:8340/config` — API Keys testen
2. Server-Log: `tail -f /tmp/jarvis-server.log`
3. `config.json` prüfen (keine Kommas am Ende!)
4. Python-Pfad: `/opt/homebrew/bin/python3.11`
5. macOS-Berechtigungen: Accessibility, Screen Recording
