# CLAUDE.md

Dieses Workspace ist **Jarvis** — ein persoenlicher KI-Assistent mit Sprachsteuerung, Browser-Kontrolle und Cmd+Shift+J Hotkey (macOS). Version: siehe `version.json`.

---

## Setup-Modus

Wenn der Nutzer nach dem Setup fragt oder "Richte Jarvis ein" sagt, folge `SETUP_macOS.md`.  
Frage nach Name, Taetigkeit und bevorzugter Anrede — diese Infos gehoeren in den Systemprompt in `server.py`.

**Voraussetzungen pruefen:**
1. `Python 3.11`: `/opt/homebrew/bin/python3.11 --version`
2. `pip install -r requirements.txt`
3. `playwright install chromium`

---

## Projektstruktur

```
.
├── CLAUDE.md                    # Diese Datei
├── SETUP_macOS.md               # Setup-Anleitung
├── README.md / README_de.md     # Projektdoku (EN/DE)
├── version.json                 # Aktuelle Version (z.B. 2.1.1)
├── config.json                  # Persoenliche Config (gitignored)
├── config.example.json          # Template (alle Keys mit Defaults)
├── voice.json                   # ElevenLabs Voice-Config (gitignored)
├── voice.example.json           # Voice-Config Template
├── requirements.txt             # Python Dependencies
├── server.py                    # FastAPI Backend — Hauptdatei
├── browser_tools.py             # Playwright Browser-Steuerung
├── screen_capture.py            # Screenshot + Claude Vision (SCREEN-Action)
├── frontend/
│   ├── index.html               # Jarvis Dashboard — Haupt-UI (/)
│   ├── config.html              # Config UI (/config)
│   ├── config.js                # Config UI Logik
│   ├── handbuch.html            # Benutzerhandbuch (/handbuch)
│   ├── main.js                  # Einfache Jarvis-UI (kein Dashboard)
│   └── style.css                # Dark Theme (nur fuer main.js-UI)
├── docs/
│   ├── JARVIS_Handbuch.pdf      # PDF-Handbuch
│   └── Jarvis-Start.mp4         # Demo-Video
├── scripts/
│   ├── launch-session.sh        # Startet Server + Chrome App Mode
│   ├── mic-mute-menubar.py      # Mic-Mute in macOS Menuleiste
│   └── wake-monitor.py          # Wake-from-Sleep → /api/wake
└── JARVIS_Handbuch.html         # HTML-Handbuch (Quelle fuer PDF)
```

---

## Architektur

| Komponente | Detail |
|---|---|
| Backend | FastAPI, Python 3.11, Port **8340** |
| KI-Modell | `claude-haiku-4-5-20251001` (Anthropic) |
| TTS | ElevenLabs `eleven_turbo_v2_5`, chunked parallel |
| Spracherkennung | Web Speech API (Chrome, `de-DE`) |
| Browser | Playwright Chromium (headless) |
| Autostart | macOS launchd (keepalive) |

**Wichtige Routen:**
- `/` → Dashboard (`index.html`) — HUD, Chat, Mail, Tasks, Programme
- `/config` → Konfiguration (`config.html`)
- `/handbuch` → Benutzerhandbuch (`handbuch.html`)
- `/dashboard` → **301 Redirect** auf `/` (veraltet, `dashboard.html` geloescht)
- `/ws` → WebSocket (Sprachsteuerung + TTS)
- `/api/*` → REST-Endpoints

---

## Config-System

`config.json` wird beim Start geladen. Fehlt die Datei oder ein Pflicht-Key → `SystemExit(1)` mit klarer Fehlermeldung.

**Pflicht-Keys:** `anthropic_api_key`, `elevenlabs_api_key`  
**Alle Keys:** siehe `config.example.json`

`ha_enabled: false` → `HA_URL` wird auf `""` gesetzt, alle HA-Guards greifen automatisch.  
`voice.json` steuert ElevenLabs Voice-ID (getrennt von `config.json`).

---

## Wichtige Invarianten

- **`main.js` nicht anfassen** ohne guten Grund — wird von der einfachen Jarvis-UI genutzt (kein Dashboard)
- **`index.html` ist die aktive Hauptdatei** — alle State-, Audio- und WS-Fixes gehoeren dort rein
- **`dashboard.html` existiert nicht mehr** — `/dashboard` redirectet auf `/`
- **`style.css`** gilt nur fuer die einfache UI (index.html der alten Version), nicht fuer das Dashboard
- **Kein `config["key"]`** — immer `config.get("key", "")` verwenden
- **TTS-Chunks** werden parallel gefeuert (`asyncio.gather`) mit einem Retry nach 1s bei Fehler
- **WebSocket-Reconnect** laeuft mit exponentiellem Backoff (3 → 60s) in `index.html` und `main.js`
- **Action-System**: Structured Output (ActionModel via Pydantic) → `_structured_to_legacy_action()` → `execute_action()`. Nicht ohne Phase-7-Plan anfassen.

---

## Starten

```bash
cd "/Users/matthiasschreiber/jarvis-voice-assistant V_2.1"
/opt/homebrew/bin/python3.11 server.py
# oder via Autostart: Cmd+Shift+J
```

Server laeuft auf `http://localhost:8340` — Dashboard oeffnet sich automatisch via `launch-session.sh`.
