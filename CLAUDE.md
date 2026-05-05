# CLAUDE.md

Dieses Workspace ist **Jarvis** — ein persoenlicher KI-Assistent mit Sprachsteuerung, Browser-Kontrolle und Cmd+Shift+J Hotkey (macOS).

---

## Fuer Claude Code: Setup-Modus

Wenn der Nutzer nach dem Setup fragt oder "Richte Jarvis ein" sagt, folge den Anweisungen in `SETUP_macOS.md`. Frage den Nutzer nach seinem Namen, seiner Taetigkeit, und wie er angesprochen werden moechte — diese Infos muessen in den Systemprompt in `server.py` eingetragen werden.

**WICHTIG — Pruefe und installiere zuerst alle Voraussetzungen:**

1. **Python 3.11**: `/opt/homebrew/bin/python3.11 --version`
2. **Google Chrome**: Pruefe ob Chrome installiert ist.
3. **pip Dependencies**: `pip install -r requirements.txt`
4. **Playwright Browser**: `playwright install chromium`

---

## Workspace Structure

```
.
├── CLAUDE.md              # This file
├── SETUP_macOS.md         # Setup-Anleitung fuer Claude Code (macOS)
├── config.json            # Persoenliche Config (gitignored)
├── config.example.json    # Template mit Platzhaltern
├── requirements.txt       # Python Dependencies
├── server.py              # FastAPI Backend (Claude Haiku + ElevenLabs TTS)
├── browser_tools.py       # Playwright Browser-Steuerung
├── screen_capture.py      # Screenshot + Claude Vision
├── frontend/
│   ├── index.html         # Jarvis Web-UI (Chrome App Mode, port 8340)
│   ├── dashboard.html     # Dashboard (/dashboard)
│   ├── config.html        # Config UI (/config)
│   ├── config.js          # Config UI Logik
│   ├── main.js            # Speech Recognition + WebSocket + Audio
│   └── style.css          # Dark Theme
└── scripts/
    ├── launch-session.sh  # Startet Server, Chrome, Mic-Mute Button
    ├── mic-mute-menubar.py # Mic-Mute in der macOS Menuleiste
    └── wake-monitor.py    # Wake-from-Sleep → /api/wake
```
