"""
Jarvis V2 — Voice AI Server
FastAPI backend: receives speech text, thinks with Claude Haiku,
speaks with ElevenLabs, controls browser with Playwright.
"""

import asyncio
import base64
import io
import json
import os
import random
import re
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ValidationError

import anthropic
import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, JSONResponse
from systems.daily_brief import DailyBrief
from systems.news_system import NewsSystem

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
VOICE_PATH  = os.path.join(os.path.dirname(__file__), "voice.json")

try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
except FileNotFoundError:
    print("[jarvis] FEHLER: config.json nicht gefunden. Bitte 'cp config.example.json config.json' ausführen.", flush=True)
    raise SystemExit(1)
except json.JSONDecodeError as e:
    print(f"[jarvis] FEHLER: config.json ist kein gültiges JSON: {e}", flush=True)
    raise SystemExit(1)

def _load_voice_db() -> dict:
    """Load voice.json — fallback to config.json voice id if file missing."""
    try:
        with open(VOICE_PATH, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        fallback_id = config.get("elevenlabs_voice_id", "")
        return {"active_voice_id": fallback_id, "voices": [{"name": "Standard", "voice_id": fallback_id}]}

_voice_db = _load_voice_db()

ANTHROPIC_API_KEY  = config.get("anthropic_api_key", "")
ELEVENLABS_API_KEY = config.get("elevenlabs_api_key", "")
ELEVENLABS_VOICE_ID = _voice_db.get("active_voice_id", "")

_missing = [k for k, v in [("anthropic_api_key", ANTHROPIC_API_KEY), ("elevenlabs_api_key", ELEVENLABS_API_KEY)] if not v or v.startswith("YOUR_")]
if _missing:
    print(f"[jarvis] FEHLER: Pflicht-Keys fehlen in config.json: {', '.join(_missing)}", flush=True)
    print("[jarvis] Bitte config.json befüllen oder Config UI unter http://localhost:8340/config aufrufen.", flush=True)
    raise SystemExit(1)

USER_NAME = config.get("user_name", "")
USER_ADDRESS = config.get("user_address", "Sir")
CITY = config.get("city", "Hamburg")
LAT = config.get("lat", 53.55)
LON = config.get("lon", 10.00)
KACHELMANN_KEY = config.get("kachelmann_api_key", "")
OBSIDIAN_INBOX = config.get("obsidian_inbox_path", "")
HA_URL = config.get("ha_url", "").rstrip("/") if config.get("ha_enabled", True) else ""
HA_TOKEN = config.get("ha_token", "")
WAKE_GREETING_ENABLED = config.get("wake_greeting_enabled", True)

LIGHT_MAP: dict[str, str | list[str]] = {
    # Alle
    "alle":          "light.alle_lichter",
    "alles":         "light.alle_lichter",
    "ueberall":      "light.alle_lichter",
    "überall":       "light.alle_lichter",
    "gesamt":        "light.alle_lichter",
    # Wohnzimmer
    "wohnzimmer":    "light.wohnzimmer",
    "wohnraum":      "light.wohnzimmer",
    "living":        "light.wohnzimmer",
    # Küche
    "küche":         "light.kuche",
    "kuche":         "light.kuche",
    "kueche":        "light.kuche",
    "kitchen":       "light.kuche",
    # Büro
    "büro":          "light.buro",
    "buro":          "light.buro",
    "buero":         "light.buro",
    "arbeitszimmer": "light.buro",
    "arbeitsraum":   "light.buro",
    "office":        "light.buro",
    "studio":        "light.buro",
    # Flur
    "flur":          "light.flur",
    "gang":          "light.flur",
    "eingang":       "light.flur",
    "diele":         "light.flur",
    "hallway":       "light.flur",
    # Schlafzimmer
    "schlafzimmer":  "light.schlafzimmer",
    "schlafraum":    "light.schlafzimmer",
    "bedroom":       "light.schlafzimmer",
    # Balkon
    "balkon":        "light.balkon_led",
    "terrasse":      "light.balkon_led",
    # Einzellampen
    "iris":          "light.hue_iris",
    "hue go":        "light.hue_go_1",
    "go":            "light.hue_go_1",
    # Gruppen
    "sideboard":     ["light.sideboard_links", "light.sideboard_rechts"],
    "nachtschrank":  ["light.nachtschrank_links", "light.nachtschrank_rechts"],
}

_LIGHT_STOP = {"das", "die", "den", "dem", "der", "ein", "eine", "licht", "lampe",
               "im", "in", "am", "an", "bitte", "mal", "doch", "kannst", "du",
               "mach", "mache", "schalte", "schalten", "stell", "stelle"}
_CMD_ON  = {"an", "ein", "einschalten", "einschalte", "anschalten", "anschalte",
            "anmachen", "anmache", "einmachen", "einmache"}
_CMD_OFF = {"aus", "ausschalten", "ausschalte", "ausmachen", "ausmache"}


def _parse_licht(payload: str):
    """Parse LICHT payload → (cmd, brightness, room_key).
    Returns room_key=None if room cannot be identified."""
    words = payload.strip().lower().split()
    cmd = "turn_on"
    brightness: int | None = None
    room_words: list[str] = []

    for word in words:
        w = word.rstrip("%")
        if word in _CMD_OFF:
            cmd = "turn_off"
        elif word in _CMD_ON:
            cmd = "turn_on"
        elif w.isdigit():
            brightness = int(w)
            cmd = "turn_on"
        elif word not in _LIGHT_STOP:
            room_words.append(word)

    # Multi-word lookup first, then single-word fallback
    room_str = " ".join(room_words)
    def _lookup(s: str):
        if s in LIGHT_MAP:
            return s
        n = s.replace("ü", "u").replace("ö", "o").replace("ä", "a").replace("ß", "ss")
        return n if n in LIGHT_MAP else None

    key = _lookup(room_str)
    if key is None:
        for w in room_words:
            key = _lookup(w)
            if key:
                break

    return cmd, brightness, key, room_str

_last_licht_room: str | None = None
_licht_room_lock = asyncio.Lock()

daily_brief = DailyBrief()
_last_activate_spoken: Optional[datetime] = None
_last_wake_spoken: Optional[datetime] = None
_morning_news_text: str = ""  # spoken after morning brief — set in morning trigger path
_last_search_url: str = ""        # URL des letzten NEWS_SEARCH-Treffers — für Follow-up-Fragen
_last_search_published: str = ""  # ISO-Datum des letzten Treffers — für Display-Formatierung

class _PrintLogger:
    def info(self, msg):    print(f"[news] {msg}", flush=True)
    def warning(self, msg): print(f"[news] WARN: {msg}", flush=True)
    def error(self, msg):   print(f"[news] ERROR: {msg}", flush=True)

news = NewsSystem(config, _PrintLogger())

# ── Structured Output Models ───────────────────────────────────────────────
# raum uses str (not Literal) to accept all LIGHT_MAP keys; validated at runtime.
# Note: "bad" from original spec omitted — not present in LIGHT_MAP.
class LichtParameters(BaseModel):
    raum: str
    zustand: Optional[Literal["an", "aus"]] = None
    helligkeit: Optional[int] = Field(None, ge=1, le=100)

class ActionModel(BaseModel):
    action: Literal[
        "licht", "reminder_add", "reminder_done", "search", "open", "open_app", "browse",
        "mail_read", "notiz", "notiz_erledigt", "kalender", "tasks_list",
        "notiz_list", "screen", "news", "news_brief", "news_search", "none"
    ]
    parameters: dict = Field(default_factory=dict)
    response: Optional[str] = None
# ──────────────────────────────────────────────────────────────────────────

ai = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
http = httpx.AsyncClient(timeout=30)

app = FastAPI()

import browser_tools
import screen_capture

with open(os.path.join(os.path.dirname(__file__), "version.json")) as _vf:
    _VERSION_INFO: dict = json.load(_vf)


SYMBOL_DE: dict[str, str] = {
    "sunny": "Sonnig",
    "clearsky": "Klarer Himmel",
    "clear": "Klar",
    "partlycloudy": "Teilweise bewoelkt",
    "cloudy": "Bewoelkt",
    "overcast": "Bedeckt",
    "fog": "Neblig",
    "rain": "Regen",
    "rainy": "Regen",
    "lightrain": "Leichter Regen",
    "heavyrain": "Starker Regen",
    "drizzle": "Nieselregen",
    "sleet": "Schneeregen",
    "snow": "Schnee",
    "snowy": "Schnee",
    "hail": "Hagel",
    "thunder": "Gewitter",
    "thunderstorm": "Gewitter",
    "windy": "Windig",
    "clearnight": "Klare Nacht",
    "cloudynight": "Bewoelkte Nacht",
    "rainynight": "Regen in der Nacht",
}


def get_ha_temperature() -> float | None:
    """Fetch outdoor temperature from Home Assistant weather station."""
    if not HA_URL or not HA_TOKEN:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{HA_URL}/api/states/sensor.weather_station_outdoor_module_temperatur",
            headers={"Authorization": f"Bearer {HA_TOKEN}"}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        state = json.loads(resp.read())["state"]
        return round(float(state), 1)
    except Exception:
        return None


def get_weather_sync():
    """Fetch weather: temperature from HA station, conditions from Kachelmann."""
    if not KACHELMANN_KEY:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://api.kachelmannwetter.com/v02/current/{LAT}/{LON}",
            headers={"X-API-Key": KACHELMANN_KEY}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())["data"]
        def v(k): return data[k]["value"] if k in data else None
        symbol = v("weatherSymbol") or ""
        desc = SYMBOL_DE.get(symbol.lower(), symbol)
        sun = v("sunHours")
        if sun is not None and sun >= 0.8:
            desc = "Sonnig"
        elif sun is not None and sun >= 0.3:
            desc = "Teilweise bewoelkt"
        # Use own weather station for temperature (more accurate)
        ha_temp = get_ha_temperature()
        temp = ha_temp if ha_temp is not None else round(v("temp") or 0, 1)
        return {
            "temp": temp,
            "description": desc,
            "humidity": v("humidityRelative"),
            "wind_kmh": v("windSpeed"),
            "cloud_pct": v("cloudCoverage"),
            "sun_hours": sun,
        }
    except Exception as e:
        print(f"[jarvis] Wetter-Fehler: {e}", flush=True)
        return None


def get_tasks_sync():
    """Read open reminders due today, tomorrow or overdue (no due date = excluded)."""
    script = '''tell application "Reminders"
    set cutoff to current date
    set hours of cutoff to 23
    set minutes of cutoff to 59
    set seconds of cutoff to 59
    set cutoff to cutoff + (1 * days)
    get name of (every reminder whose completed is false and due date ≤ cutoff)
end tell'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return [i.strip() for i in r.stdout.strip().split(",") if i.strip()]
        return []
    except:
        return []


_DE_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_DE_MONTHS   = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                 "Juli", "August", "September", "Oktober", "November", "Dezember"]
_DE_ORDINALS = [
    "", "ersten", "zweiten", "dritten", "vierten", "fünften", "sechsten", "siebten",
    "achten", "neunten", "zehnten", "elften", "zwölften", "dreizehnten", "vierzehnten",
    "fünfzehnten", "sechzehnten", "siebzehnten", "achtzehnten", "neunzehnten", "zwanzigsten",
    "einundzwanzigsten", "zweiundzwanzigsten", "dreiundzwanzigsten", "vierundzwanzigsten",
    "fünfundzwanzigsten", "sechsundzwanzigsten", "siebenundzwanzigsten", "achtundzwanzigsten",
    "neunundzwanzigsten", "dreißigsten", "einunddreißigsten",
]


def _display_date(iso: str) -> str:
    """'2026-05-07' → '07. Mai 2026' — lesbare Form für das Frontend."""
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return f"{d.day:02d}. {_DE_MONTHS[d.month]} {d.year}"
    except Exception:
        return iso


def _spoken_date(iso: str) -> str:
    """'2026-05-07' → 'siebten Mai zweitausendundzwanzig' — kein Digit für TTS."""
    _ones = ["", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
             "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn",
             "siebzehn", "achtzehn", "neunzehn"]
    _zehner = ["", "", "zwanzig", "dreißig", "vierzig", "fünfzig",
               "sechzig", "siebzig", "achtzig", "neunzig"]
    def _year(y):
        if not (2000 <= y <= 2099):
            return str(y)
        r = y - 2000
        if r == 0:   return "zweitausend"
        if r <= 19:  return f"zweitausend{_ones[r]}"
        o, t = r % 10, r // 10
        return f"zweitausend{_ones[o]}und{_zehner[t]}" if o else f"zweitausend{_zehner[t]}"
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return f"{_DE_ORDINALS[d.day]} {_DE_MONTHS[d.month]} {_year(d.year)}"
    except Exception:
        return iso


def _label_from_dt(dt) -> str:
    """Convert a datetime to a human-readable relative label for Claude."""
    from datetime import date
    delta = (dt.date() - date.today()).days
    weekday = _DE_WEEKDAYS[dt.weekday()]
    if dt.hour == 0 and dt.minute == 0:
        time_str = ""
    elif dt.minute == 0:
        time_str = f" {dt.hour} Uhr"
    else:
        time_str = f" {dt.hour} Uhr {dt.minute}"
    if delta == 0:
        return f"heute{time_str} ({weekday})"
    elif delta == 1:
        return f"morgen{time_str} ({weekday})"
    elif delta == 2:
        return f"uebermorgen{time_str} ({weekday})"
    else:
        return f"{weekday}, {dt.strftime('%d.%m.')}{time_str} (in {delta} Tagen)"


def get_calendar_sync(days: int = 7) -> list[str]:
    """Fetch calendar events from Home Assistant CalDAV integration."""
    import urllib.request
    from datetime import datetime, timedelta

    calendars = [
        "calendar.kalender",
        "calendar.dienstliches",
        "calendar.a_dienst",
        "calendar.stammtisch",
        "calendar.arzttermine",
        "calendar.family",
    ]
    headers = {"Authorization": f"Bearer {HA_TOKEN}"}

    start_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=days)
    start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
    end_str = end_dt.strftime('%Y-%m-%dT%H:%M:%S')

    seen_occ: set[str] = set()
    results: list[tuple[datetime, str]] = []
    for entity_id in calendars:
        try:
            url = f"{HA_URL}/api/calendars/{entity_id}?start={start_str}&end={end_str}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                events = json.loads(resp.read())
            for e in events:
                title = e.get('summary', '').strip()
                if not title:
                    continue
                s = e['start'].get('dateTime') or e['start'].get('date')
                if 'T' in s:
                    dt = datetime.fromisoformat(s).replace(tzinfo=None)
                else:
                    dt = datetime.fromisoformat(s)
                key = f"{title}|{dt.strftime('%Y-%m-%d %H:%M')}"
                if key not in seen_occ:
                    seen_occ.add(key)
                    results.append((dt, title))
        except Exception:
            continue

    results.sort(key=lambda x: x[0])
    seen_titles: set[str] = set()
    lines = []
    for dt, title in results:
        if title in seen_titles:
            continue
        seen_titles.add(title)
        lines.append(f"{title} -- {_label_from_dt(dt)}")
    return lines


def get_mail_sync():
    """Read unread mails from iCloud INBOX via Mail.app."""
    script = '''
tell application "Mail"
    set acc to account "iCloud"
    set mb to mailbox "INBOX" of acc
    set msgList to {}
    set unread to (messages of mb whose read status is false)
    repeat with m in unread
        set end of msgList to (sender of m) & " || " & (subject of m)
    end repeat
    return msgList
end tell'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return [i.strip() for i in r.stdout.strip().split(",") if i.strip()][:10]
        return []
    except:
        return []


def refresh_data():
    """Refresh weather, tasks, mail and calendar."""
    global WEATHER_INFO, TASKS_INFO, MAIL_INFO, CALENDAR_INFO
    WEATHER_INFO = get_weather_sync()
    TASKS_INFO = get_tasks_sync()
    MAIL_INFO = get_mail_sync()
    CALENDAR_INFO = get_calendar_sync(days=7)
    print(f"[jarvis] Wetter: {WEATHER_INFO}", flush=True)
    print(f"[jarvis] Tasks: {len(TASKS_INFO)} geladen", flush=True)
    print(f"[jarvis] Mails: {len(MAIL_INFO)} ungelesen", flush=True)
    print(f"[jarvis] Kalender: {len(CALENDAR_INFO)} Termine (7 Tage)", flush=True)

WEATHER_INFO = None
TASKS_INFO = []
MAIL_INFO = []
CALENDAR_INFO = []
OBSIDIAN_INFO: list[str] = []
NEWS_INFO: list[dict] = []
_mail_lock = asyncio.Lock()
# Data is loaded async in startup_and_refresh() — no blocking call at import time

# Action parsing
ACTION_PATTERN = re.compile(r'\[ACTION:(\w+)\]\s*(.*?)$', re.DOTALL | re.MULTILINE)

conversations: dict[str, list] = {}
active_connections: set = set()


def _obsidian_note_done(content: str) -> bool:
    """True if the note has checkboxes and all of them are checked."""
    import re
    unchecked = re.findall(r"- \[ \]", content)
    checked   = re.findall(r"- \[[xX]\]", content)
    return bool(checked) and not unchecked

def get_obsidian_info_sync() -> list[str]:
    if not OBSIDIAN_INBOX:
        return []
    try:
        files = sorted(f for f in os.listdir(OBSIDIAN_INBOX) if f.endswith(".md"))
        notes = []
        for fname in files:
            with open(os.path.join(OBSIDIAN_INBOX, fname), "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not _obsidian_note_done(content):
                notes.append(content)
        return notes
    except Exception:
        return []

def build_system_prompt():
    weather_block = ""
    if WEATHER_INFO:
        w = WEATHER_INFO
        wind = f", Wind {w['wind_kmh']} km/h" if w.get('wind_kmh') else ""
        t = w['temp']
        temp_str = str(int(t)) if t == int(t) else str(t).replace('.', ' Komma ')
        weather_block = f"\nWetter {CITY}: {temp_str} Grad, {w['description']}{wind}"

    task_block = ""
    if TASKS_INFO:
        task_block = f"\nOffene Aufgaben ({len(TASKS_INFO)}): " + ", ".join(TASKS_INFO[:5])

    obsidian_block = ""
    if OBSIDIAN_INFO:
        previews = [n[:70] + ("..." if len(n) > 70 else "") for n in OBSIDIAN_INFO]
        obsidian_block = f"\nOffene Obsidian-Notizen ({len(OBSIDIAN_INFO)}): " + " | ".join(previews)

    mail_block = ""
    if MAIL_INFO:
        mail_block = f"\nUngelesene Mails ({len(MAIL_INFO)}): " + " / ".join(MAIL_INFO[:5])
    else:
        mail_block = "\nUngelesene Mails: keine"

    cal_block = ""
    if CALENDAR_INFO:
        cal_block = f"\nTermine naechste 7 Tage ({len(CALENDAR_INFO)}): " + " | ".join(CALENDAR_INFO[:8])
    else:
        cal_block = "\nTermine naechste 7 Tage: keine"

    news_block = ""
    if NEWS_INFO:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        recent = [a for a in NEWS_INFO if a.get("saved_at", "") >= cutoff]
        pool = recent[:3] if recent else NEWS_INFO[:3]
        headlines = [f"{a.get('source','')}: {a.get('title','')[:65]}" for a in pool if a.get('title')]
        if headlines:
            news_block = "\nRSS-Neuigkeiten: " + " | ".join(headlines)

    return f"""Du bist Jarvis, der KI-Assistent von Tony Stark aus Iron Man. Dein Dienstherr ist {USER_NAME}. Er wohnt in {CITY}. Du sprichst ausschliesslich Deutsch. {USER_NAME} moechte mit "{USER_ADDRESS}" angesprochen und gesiezt werden. Nutze "Sie" als Pronomen — FALSCH: "Sir planen", RICHTIG: "Sie planen, Sir". Dein Ton ist trocken, sarkastisch und britisch-hoeflich - wie ein Butler der alles gesehen hat und trotzdem loyal bleibt. Du machst subtile, trockene Bemerkungen, bist aber niemals respektlos. Wenn Sir eine offensichtliche Frage stellt, darfst du mit elegantem Sarkasmus antworten. Du bist hochintelligent, effizient und immer einen Schritt voraus. Halte deine Antworten kurz - maximal 3 Saetze. Du kommentierst fragwuerdige Entscheidungen hoeflich aber spitz.

WICHTIG: Schreibe NIEMALS Regieanweisungen, Emotionen oder Tags in eckigen Klammern wie [sarcastic] [formal] [amused] [dry] oder aehnliches. Dein Sarkasmus muss REIN durch die Wortwahl kommen. Alles was du schreibst wird laut vorgelesen.

AUSSPRACHE: Schreibe Temperaturen immer als "X Grad" oder "X Komma Y Grad" — niemals als "°C". Schreibe Uhrzeiten immer als "X Uhr" (z.B. "20 Uhr") oder "X Uhr Y" (z.B. "20 Uhr 5") — niemals als "20:00 Uhr" oder "20:05 Uhr". Schreibe Daten IMMER als "7. Mai 2026" — niemals als "2026-05-07" oder andere ISO-Formate.

Du hast die volle Kontrolle ueber den Browser von {USER_NAME}. Du kannst im Internet suchen, Webseiten oeffnen und den Bildschirm sehen. Wenn Sir dich bittet etwas nachzuschauen, zu recherchieren, zu googeln, eine Seite zu oeffnen, oder irgendetwas im Internet zu tun — nutze IMMER eine Aktion. Frag nicht ob du es tun sollst, tu es einfach.

AKTIONEN - Wenn eine Aktion noetig ist, schreibe NUR die Aktion — keinen Text davor, keine Einleitung, keine Bestaetigung. Das Ergebnis wird automatisch vorgelesen.
[ACTION:SEARCH] suchbegriff - Internet durchsuchen und Ergebnisse zusammenfassen
[ACTION:OPEN] url - URL im Browser oeffnen
[ACTION:OPEN_APP] app-name - macOS App oeffnen. Nutze diese Aktion wenn Sir eine App, ein Programm oder eine Anwendung oeffnen moechte. Beispiele: "Mail", "Safari", "Visual Studio Code", "Obsidian", "Music". Schreibe den App-Namen exakt so wie er in macOS heisst.
[ACTION:SCREEN] - Bildschirm ansehen und beschreiben.
[ACTION:NEWS] - Aktuelle Weltnachrichten abrufen. Nutze diese Aktion wenn nach News, Nachrichten, was in der Welt passiert, aktuelle Lage oder Weltgeschehen gefragt wird. Schreibe einen kurzen Satz davor wie "Ich schaue nach den aktuellen Nachrichten."
[ACTION:NEWS_BRIEF] - Persoenliche RSS-Feeds abrufen und neue Artikel vorlesen. Nutze diese Aktion wenn Sir fragt ob es was Neues gibt, was es Neues aus seinen Quellen gibt, oder aehnliches.
[ACTION:NEWS_SEARCH] stichwort - Im persoenlichen RSS-Archiv suchen. Nutze diese Aktion wenn Sir fragt "wie war das mit X", "was war da ueber Y" oder nach einem bestimmten Thema im Archiv sucht.
[ACTION:REMINDER_ADD] aufgabe - Neue Erinnerung in die Inbox schreiben. Nutze diese Aktion wenn Sir etwas hinzufuegen, notieren, merken oder erinnert werden moechte.
[ACTION:REMINDER_DONE] stichwort - Erinnerung als erledigt markieren. Nutze diese Aktion wenn Sir sagt dass etwas erledigt, abgehakt oder fertig ist.
[ACTION:TASKS_LIST] - Aktuelle Aufgabenliste live aus Reminders laden und vorlesen. Nutze diese Aktion IMMER wenn Sir fragt welche Aufgaben es gibt, was auf der Liste steht, oder was noch offen ist.
[ACTION:MAIL_READ] stichwort - Mails lesen. Ohne Stichwort: alle Ungelesenen auflisten. Mit Stichwort (z.B. Absendername): Inhalt der passenden Mail vorlesen.
[ACTION:KALENDER] zeitraum - Kalendertermine live abrufen. Zeitraum: "heute" (1 Tag), "morgen" (2 Tage), "woche" (7 Tage, Standard), "monat" (30 Tage), "60tage" (60 Tage), oder eine Zahl 1-60. Nutze diese Aktion IMMER wenn Sir nach Terminen fragt. Für Fragen wie "was ist am 1. Mai" nutze "woche" oder "monat" je nach Datum. Zeige nur den Titel und das Datum — nenne KEINEN Kalender-Namen, der in eckigen Klammern stehen könnte.
[ACTION:LICHT] raum befehl - Licht per Home Assistant steuern. Raeume: alle, wohnzimmer, kueche, buero, flur, schlafzimmer, balkon, nachtschrank, sideboard, iris. Befehle: "an", "aus", oder Prozentzahl fuer Helligkeit (z.B. "50"). Beispiele: "wohnzimmer an", "alles aus", "buero 50". Nutze diese Aktion IMMER wenn Sir Licht ein- oder ausschalten oder dimmen moechte.
[ACTION:NOTIZ] text - Notiz in Obsidian Inbox speichern. Nutze diese Aktion wenn Sir etwas notieren, aufschreiben oder in Obsidian speichern moechte. Der gesamte Notiztext kommt nach dem Tag. Beispiel: "[ACTION:NOTIZ] Idee fuer das Projekt: neues Dashboard mit Echtzeit-Daten"
[ACTION:NOTIZ_LIST] - Alle Notizen in der Obsidian Inbox auflisten und vorlesen. Nutze diese Aktion IMMER wenn Sir fragt welche Notizen, Erinnerungen oder Aufzeichnungen in Obsidian sind.
[ACTION:NOTIZ_ERLEDIGT] stichwort - Notiz(en) aus der Obsidian Inbox als erledigt markieren (loeschen). Nutze "alle" um alle Notizen zu loeschen. Nutze diese Aktion IMMER wenn Sir Obsidian-Notizen als erledigt, abgehakt oder fertig markieren moechte — NIEMALS REMINDER_DONE dafuer verwenden.

AUSGABEFORMAT — Bevorzuge JSON:
Antworte IMMER als JSON-Objekt. Bei normaler Antwort ohne Aktion:
{{"action": "none", "parameters": {{}}, "response": "Antworttext hier"}}
Bei Lichtsteuerung:
{{"action": "licht", "parameters": {{"raum": "buero", "zustand": "an", "helligkeit": null}}, "response": null}}
Raeume fuer licht (kanonisch): alle, wohnzimmer, kueche, buero, flur, schlafzimmer, balkon, sideboard, nachtschrank, iris, go. Zustand: "an" oder "aus". Helligkeit: 1-100 oder null.
Bei open_app: parameters: {{"app": "App-Name"}}. Bei allen anderen Aktionen: parameters: {{"payload": "bisheriger payload-text"}}
Alle action-Werte: none, licht, reminder_add, reminder_done, search, open, open_app, browse, mail_read, notiz, notiz_erledigt, kalender, tasks_list, notiz_list, screen, news, news_brief, news_search
Bei news_search: parameters: {{"stichwort": "suchbegriff"}}
Falls JSON nicht moeglich: altes Format [ACTION:TYP] payload bleibt gueltig.

WENN {USER_NAME} "Jarvis activate" sagt:
- Begruesse ihn passend zur Tageszeit (aktuelle Zeit: {{time}}).
- Gebe eine kurze Info ueber das Wetter — Temperatur und ob Sonne/klar/bewoelkt/Regen, und wie es sich anfuehlt. Keine Luftfeuchtigkeit.
- Fasse die Aufgaben kurz als Ueberblick in einem Satz zusammen, ohne dabei jede einzelne Aufgabe einfach vorzulesen. Gebe gerne einen humorvollen Kommentar am Ende an.
- Erwaehne kurz die Anzahl ungelesener Mails. Wenn keine: lass es weg.
- Erwaehne kurz anstehende Termine heute oder morgen, falls vorhanden.
- Weise kurz auf offene Obsidian-Notizen hin, falls vorhanden.
- Nenne 1-2 konkrete Schlagzeilen-Titel aus den RSS-Neuigkeiten (mit Quelle), falls vorhanden. Wortwoertlich aus den Daten zitieren, nicht umschreiben oder weglassen.
- Sei kreativ bei der Begruessung.
- WICHTIG: Verwende NIEMALS Action-Tags in der Begruessung. Alle Daten sind bereits in === AKTUELLE DATEN === verfuegbar — dort direkt ablesen, keine Actions ausfuehren.

=== AKTUELLE DATEN ==={weather_block}{task_block}{obsidian_block}{mail_block}{cal_block}{news_block}
==="""


def get_system_prompt():
    return build_system_prompt().replace("{time}", time.strftime("%H:%M"))


def extract_action(text: str):
    match = ACTION_PATTERN.search(text)
    if match:
        clean = text[:match.start()].strip()
        return clean, {"type": match.group(1), "payload": match.group(2).strip()}
    return text, None


def _extract_first_json(text: str) -> Optional[str]:
    """Extract first balanced JSON object from text, ignoring any trailing content."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start != -1:
                return text[start:i + 1]
    return None


def _strip_json_blocks(text: str) -> str:
    """Remove markdown JSON code blocks from text before speaking."""
    import re
    text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    return ' '.join(text.split()).strip()


def parse_structured_action(reply: str) -> Optional[ActionModel]:
    """Try to parse LLM reply as structured JSON ActionModel. Returns None on any failure."""
    try:
        raw = _extract_first_json(reply)
        if not raw:
            return None
        data = json.loads(raw)
        return ActionModel(**data)
    except ValidationError:
        return None
    except Exception:
        return None


async def synthesize_speech(text: str, voice_id: Optional[str] = None) -> bytes:
    if not text.strip():
        return b""

    # Split long text into chunks at sentence boundaries to avoid ElevenLabs cutoff
    chunks = []
    if len(text) > 250:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        current = ""
        for s in sentences:
            if len(current) + len(s) > 250 and current:
                chunks.append(current.strip())
                current = s
            else:
                current = (current + " " + s).strip()
        if current:
            chunks.append(current.strip())
    else:
        chunks = [text]

    async def _tts_chunk(chunk: str) -> bytes:
        vid = voice_id or ELEVENLABS_VOICE_ID
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
        payload = {
            "text": chunk,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.65, "similarity_boost": 0.85},
        }
        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        for attempt in range(2):
            try:
                resp = await http.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    print(f"  TTS OK: {len(resp.content)} bytes", flush=True)
                    return resp.content
                print(f"  TTS error ({attempt+1}/2): {resp.status_code} {resp.text[:100]}", flush=True)
            except Exception as e:
                print(f"  TTS EXCEPTION ({attempt+1}/2): {e}", flush=True)
            if attempt == 0:
                await asyncio.sleep(1)
        return b""

    parts = await asyncio.gather(*[_tts_chunk(c) for c in chunks])
    total = b"".join(parts)
    print(f"  TTS final: {len(total)} bytes total", flush=True)
    return total


async def execute_action(action: dict) -> str:
    global TASKS_INFO
    t = action["type"]
    p = action["payload"]

    if t == "SEARCH":
        result = await browser_tools.search_and_read(p)
        if "error" not in result:
            return f"Seite: {result.get('title', '')}\nURL: {result.get('url', '')}\n\n{result.get('content', '')[:2000]}"
        return f"Suche fehlgeschlagen: {result.get('error', '')}"

    elif t == "BROWSE":
        result = await browser_tools.visit(p)
        if "error" not in result:
            return f"Seite: {result.get('title', '')}\n\n{result.get('content', '')[:2000]}"
        return f"Seite nicht erreichbar: {result.get('error', '')}"

    elif t == "OPEN":
        await browser_tools.open_url(p)
        return f"Geoeffnet: {p}"

    elif t == "OPEN_APP":
        app_name = p.strip()
        if not app_name:
            return f"Kein App-Name angegeben."
        result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return f"{app_name} geöffnet, {USER_ADDRESS}."
        return f"{app_name} konnte nicht gefunden werden, {USER_ADDRESS}."

    elif t == "SCREEN":
        return await screen_capture.describe_screen(ai)

    elif t == "NEWS":
        result = await browser_tools.fetch_news()
        return result

    elif t == "NEWS_BRIEF":
        global NEWS_INFO
        articles = await news.fetch_rss_feeds()
        new_articles = await news.filter_duplicates(articles)
        await news.save_to_archive(new_articles)
        if new_articles:
            NEWS_INFO = (new_articles + NEWS_INFO)[:10]
        if not new_articles:
            return f"Keine neuen Artikel seit dem letzten Abruf, {USER_ADDRESS}."
        top3 = new_articles[:3]
        items = " — ".join([f"{a['source']}: {a['title'][:60]}" for a in top3])
        total = len(new_articles)
        suffix = f" Und {total - 3} weitere." if total > 3 else ""
        return f"{total} neue Artikel: {items}.{suffix}"

    elif t == "NEWS_SEARCH":
        global _last_search_url, _last_search_published
        results = await news.search_archive(p.strip())
        if not results:
            _last_search_url = ""
            _last_search_published = ""
            return f"Nichts zu '{p.strip()}' im Archiv gefunden, {USER_ADDRESS}."
        r = results[0]
        _last_search_url = r.get('url', r.get('link', ''))
        _last_search_published = r.get('published', '')
        count = len(results)
        more = f" Und {count - 1} weitere Treffer." if count > 1 else ""
        return f"Gefunden: '{r['title']}' — {r['source']}, {_spoken_date(r['published'])}.{more}"

    elif t == "TASKS_LIST":
        tasks = get_tasks_sync()
        if tasks:
            return "Offene Aufgaben: " + " | ".join(tasks)
        return "Keine offenen Aufgaben."

    elif t == "REMINDER_ADD":
        title = p.replace('"', '').replace("'", "").strip()
        result = subprocess.run(
            ["osascript", "-e",
             f'tell application "Reminders" to make new reminder at list "Inbox" with properties {{name:"{title}"}}'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            TASKS_INFO = get_tasks_sync()
            return f"Erinnerung hinzugefügt: {title}"
        return "Fehler beim Hinzufügen der Erinnerung"

    elif t == "MAIL_READ":
        keyword = p.strip()
        if keyword:
            script = f'''
tell application "Mail"
    set acc to account "iCloud"
    set mb to mailbox "INBOX" of acc
    set msgList to {{}}
    set msgs to (messages of mb whose sender contains "{keyword}")
    if (count of msgs) = 0 then
        set msgs to (messages of mb whose subject contains "{keyword}")
    end if
    repeat with m in msgs
        set msgBody to content of m
        if length of msgBody > 800 then set msgBody to text 1 thru 800 of msgBody
        set end of msgList to "Von: " & sender of m & return & "Betreff: " & subject of m & return & msgBody
    end repeat
    return msgList
end tell'''
        else:
            script = '''
tell application "Mail"
    set acc to account "iCloud"
    set mb to mailbox "INBOX" of acc
    set msgList to {}
    set unread to (messages of mb whose read status is false)
    repeat with m in unread
        set end of msgList to "Von: " & sender of m & " | Betreff: " & subject of m
    end repeat
    return msgList
end tell'''
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return "Keine passenden Mails gefunden."
        except Exception as e:
            return f"Fehler beim Lesen der Mails: {e}"

    elif t == "KALENDER":
        zeitraum = p.strip().lower()
        if zeitraum == "heute":
            days = 1
        elif zeitraum == "morgen":
            days = 2
        elif zeitraum in ("monat", "month"):
            days = 30
        elif zeitraum in ("2monat", "2monate", "60tage"):
            days = 60
        elif zeitraum.isdigit():
            days = max(1, min(int(zeitraum), 60))
        else:
            days = 7
        events = get_calendar_sync(days=days)
        if not events:
            return "Keine Termine im angegebenen Zeitraum."
        return "\n".join(events)

    elif t == "REMINDER_DONE":
        keyword = p.replace('"', '').replace("'", "").strip()

        # Optimistic update: remove matching items from cache immediately
        matches = [t for t in TASKS_INFO if keyword.lower() in t.lower()]
        if not matches:
            return f"Keine Erinnerung mit '{keyword}' gefunden. Bitte genaueres Stichwort aus dem Titel nennen."

        TASKS_INFO = [t for t in TASKS_INFO if keyword.lower() not in t.lower()]

        # Mark as done in Reminders in background — don't block the response
        script = f'''tell application "Reminders"
    set found to (every reminder whose completed is false and name contains "{keyword}")
    repeat with r in found
        set completed of r to true
    end repeat
end tell'''
        threading.Thread(
            target=lambda: subprocess.run(["osascript", "-e", script], timeout=60),
            daemon=True
        ).start()

        return f"Erinnerung abgehakt: {', '.join(matches)}"

    elif t == "LICHT":
        if not HA_URL or not HA_TOKEN:
            return "Home Assistant nicht konfiguriert."
        if not p.strip():
            return "Kein Lichtbefehl angegeben."

        cmd, brightness, room_key, room_str = _parse_licht(p)

        if room_key is None:
            known = ", ".join(sorted({
                k for k in LIGHT_MAP if k not in ("ueberall", "gesamt", "living", "kitchen",
                "arbeitsraum", "office", "studio", "gang", "eingang", "diele", "hallway",
                "schlafraum", "bedroom", "terrasse", "go", "buero", "buro", "kuche",
                "kueche", "wohnraum")
            }))
            label = f'"{room_str}"' if room_str else "kein Raum"
            return f"Raum {label} nicht erkannt, Sir. Bekannte Räume: {known}."

        entity = LIGHT_MAP[room_key]
        entities = entity if isinstance(entity, list) else [entity]

        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        for eid in entities:
            data: dict = {"entity_id": eid}
            if brightness is not None:
                data["brightness_pct"] = brightness
            try:
                await http.post(f"{HA_URL}/api/services/light/{cmd}", headers=headers, json=data)
            except Exception as e:
                return f"Home Assistant Fehler: {e}"

        room_label = _ROOM_DISPLAY_SHARED.get(room_key, room_key.capitalize())
        sir = f", {USER_ADDRESS}"

        global _last_licht_room
        async with _licht_room_lock:
            same_room = (room_key == _last_licht_room)
            _last_licht_room = room_key

        if cmd == "turn_off":
            if same_room:
                return random.choice([
                    f"Ist aus{sir}.",
                    f"Ausgeschaltet{sir}.",
                    f"Erledigt{sir}.",
                ])
            return random.choice([
                f"{room_label} ausgeschaltet{sir}.",
                f"{room_label} ist aus{sir}.",
                f"Licht im {room_label} deaktiviert{sir}.",
            ])

        if brightness is not None:
            bri = f"{brightness} Prozent"
            if same_room:
                return random.choice([
                    f"Auf {bri} gesetzt{sir}.",
                    f"Jetzt auf {bri}{sir}.",
                    f"Angenehm reduziert auf {bri}{sir}.",
                ])
            return random.choice([
                f"{room_label} auf {bri} gedimmt{sir}.",
                f"{room_label} jetzt auf {bri}{sir}.",
                f"Licht im {room_label} auf {bri}{sir}.",
            ])

        # turn_on
        if same_room:
            return random.choice([
                f"Eingeschaltet{sir}.",
                f"Ist an{sir}.",
                f"Erledigt{sir}.",
            ])
        return random.choice([
            f"{room_label} eingeschaltet{sir}.",
            f"{room_label} ist an{sir}.",
            f"Licht im {room_label} ist an{sir}.",
        ])

    elif t == "NOTIZ":
        text = p.strip()
        if not text:
            return "Kein Notiztext angegeben."
        if not OBSIDIAN_INBOX:
            return "Obsidian Inbox Pfad nicht konfiguriert."
        try:
            import os
            from datetime import datetime
            os.makedirs(OBSIDIAN_INBOX, exist_ok=True)
            ts = datetime.now()
            slug = re.sub(r'[^\w\säöüÄÖÜß-]', '', text).strip()
            slug = re.sub(r'\s+', ' ', slug)[:50].strip() or "Notiz"
            filename = ts.strftime("%Y-%m-%d") + f" {slug}.md"
            filepath = os.path.join(OBSIDIAN_INBOX, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            print(f"[jarvis] Notiz gespeichert: {filepath}", flush=True)
            return f"Notiz gespeichert: {text}"
        except Exception as e:
            return f"Fehler beim Speichern der Notiz: {e}"

    elif t == "NOTIZ_LIST":
        if not OBSIDIAN_INBOX:
            return "Obsidian Inbox Pfad nicht konfiguriert."
        try:
            import os
            files = sorted([
                f for f in os.listdir(OBSIDIAN_INBOX)
                if f.endswith(".md")
            ])
            if not files:
                return "Die Obsidian Inbox ist leer."
            notes = []
            for fname in files:
                fpath = os.path.join(OBSIDIAN_INBOX, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                notes.append(f"- {content}")
            return f"Obsidian Inbox ({len(files)} Notiz{'en' if len(files) != 1 else ''}):\n" + "\n".join(notes)
        except Exception as e:
            return f"Fehler beim Lesen der Obsidian Inbox: {e}"

    elif t == "NOTIZ_ERLEDIGT":
        if not OBSIDIAN_INBOX:
            return "Obsidian Inbox Pfad nicht konfiguriert."
        try:
            import os
            keyword = p.strip().lower()
            files = [f for f in os.listdir(OBSIDIAN_INBOX) if f.endswith(".md")]
            if not files:
                return "Die Obsidian Inbox ist bereits leer."
            deleted = []
            for fname in files:
                fpath = os.path.join(OBSIDIAN_INBOX, fname)
                if keyword == "alle":
                    os.remove(fpath)
                    deleted.append(fname)
                else:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    if keyword in content.lower():
                        os.remove(fpath)
                        deleted.append(fname)
            if not deleted:
                return f"Keine Notiz mit '{p.strip()}' gefunden."
            return f"{len(deleted)} Notiz{'en' if len(deleted) != 1 else ''} als erledigt markiert."
        except Exception as e:
            return f"Fehler beim Loeschen der Notiz: {e}"

    return ""


# Actions whose result is already a clean, speakable string — no second LLM call needed
_TEMPLATE_ACTIONS = {"LICHT", "REMINDER_ADD", "REMINDER_DONE", "NOTIZ", "NOTIZ_ERLEDIGT", "OPEN_APP", "NEWS_BRIEF"}


async def _speak(ws: WebSocket, session_id: str, text: str, display: str = ""):
    """TTS, append to history, send to client.
    display: optionaler Frontend-Text (z.B. lesbare Datumsform); fehlt er, wird text verwendet."""
    audio = await synthesize_speech(text)
    print(f"  Jarvis: {text[:100]}", flush=True)
    conversations[session_id].append({"role": "assistant", "content": text})
    await ws.send_json({
        "type": "response",
        "text": display or text,
        "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
    })


# ── Structured Output Dispatcher ──────────────────────────────────────────

_ROOM_DISPLAY_SHARED: dict[str, str] = {
    "büro": "Büro", "buro": "Büro", "buero": "Büro",
    "arbeitszimmer": "Büro", "arbeitsraum": "Büro", "office": "Büro", "studio": "Büro",
    "küche": "Küche", "kuche": "Küche", "kueche": "Küche", "kitchen": "Küche",
    "alle": "Alle Lichter", "alles": "Alle Lichter",
    "ueberall": "Alle Lichter", "überall": "Alle Lichter", "gesamt": "Alle Lichter",
    "wohnzimmer": "Wohnzimmer", "wohnraum": "Wohnzimmer", "living": "Wohnzimmer",
    "flur": "Flur", "gang": "Flur", "eingang": "Flur", "diele": "Flur", "hallway": "Flur",
    "schlafzimmer": "Schlafzimmer", "schlafraum": "Schlafzimmer", "bedroom": "Schlafzimmer",
    "balkon": "Balkon", "terrasse": "Balkon",
    "sideboard": "Sideboard", "nachtschrank": "Nachtschrank",
    "iris": "Iris", "hue go": "Hue Go", "go": "Hue Go",
}


def _structured_to_legacy_action(structured: ActionModel) -> Optional[dict]:
    """Map ActionModel to legacy {"type": ..., "payload": ...} for non-LICHT actions."""
    p = structured.parameters
    _map = {
        "search":         ("SEARCH",         p.get("query", p.get("payload", ""))),
        "open":           ("OPEN",           p.get("url", p.get("payload", ""))),
        "open_app":       ("OPEN_APP",       p.get("app", p.get("payload", ""))),
        "browse":         ("BROWSE",         p.get("url", p.get("payload", ""))),
        "screen":         ("SCREEN",         ""),
        "news":           ("NEWS",           ""),
        "news_brief":     ("NEWS_BRIEF",     ""),
        "news_search":    ("NEWS_SEARCH",    p.get("stichwort", p.get("query", p.get("payload", "")))),
        "tasks_list":     ("TASKS_LIST",     ""),
        "notiz_list":     ("NOTIZ_LIST",     ""),
        "reminder_add":   ("REMINDER_ADD",   p.get("aufgabe", p.get("text", p.get("payload", "")))),
        "reminder_done":  ("REMINDER_DONE",  p.get("stichwort", p.get("keyword", p.get("payload", "")))),
        "mail_read":      ("MAIL_READ",      p.get("stichwort", p.get("keyword", p.get("payload", "")))),
        "kalender":       ("KALENDER",       p.get("zeitraum", str(p.get("tage", "woche")))),
        "notiz":          ("NOTIZ",          p.get("text", p.get("payload", ""))),
        "notiz_erledigt": ("NOTIZ_ERLEDIGT", p.get("stichwort", p.get("keyword", p.get("payload", "")))),
    }
    if structured.action in _map:
        t, payload = _map[structured.action]
        return {"type": t, "payload": str(payload)}
    return None


async def handle_licht_structured(params: LichtParameters) -> str:
    """Execute LICHT from structured parameters — no string parsing, only LIGHT_MAP lookup."""
    if not HA_URL or not HA_TOKEN:
        return "Home Assistant nicht konfiguriert."

    raum = params.raum.strip().lower()

    def _lookup(s: str) -> Optional[str]:
        if s in LIGHT_MAP:
            return s
        n = s.replace("ü", "u").replace("ö", "o").replace("ä", "a").replace("ß", "ss")
        return n if n in LIGHT_MAP else None

    key = _lookup(raum)
    if key is None:
        known = ", ".join(sorted({
            k for k in LIGHT_MAP if k not in (
                "ueberall", "gesamt", "living", "kitchen", "arbeitsraum", "office", "studio",
                "gang", "eingang", "diele", "hallway", "schlafraum", "bedroom", "terrasse",
                "go", "buero", "buro", "kuche", "kueche", "wohnraum"
            )
        }))
        return f"Raum '{params.raum}' nicht erkannt, {USER_ADDRESS}. Bekannte Räume: {known}."

    cmd = "turn_off" if params.zustand == "aus" else "turn_on"
    entity = LIGHT_MAP[key]
    entities = entity if isinstance(entity, list) else [entity]

    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    for eid in entities:
        data: dict = {"entity_id": eid}
        if params.helligkeit is not None:
            data["brightness_pct"] = params.helligkeit
        try:
            await http.post(f"{HA_URL}/api/services/light/{cmd}", headers=headers, json=data)
        except Exception as e:
            return f"Home Assistant Fehler: {e}"

    room_label = _ROOM_DISPLAY_SHARED.get(key, key.capitalize())
    sir = f", {USER_ADDRESS}"

    global _last_licht_room
    async with _licht_room_lock:
        same_room = (key == _last_licht_room)
        _last_licht_room = key

    if cmd == "turn_off":
        if same_room:
            return random.choice([f"Ist aus{sir}.", f"Ausgeschaltet{sir}.", f"Erledigt{sir}."])
        return random.choice([
            f"{room_label} ausgeschaltet{sir}.",
            f"{room_label} ist aus{sir}.",
            f"Licht im {room_label} deaktiviert{sir}.",
        ])

    if params.helligkeit is not None:
        bri = f"{params.helligkeit} Prozent"
        if same_room:
            return random.choice([
                f"Auf {bri} gesetzt{sir}.", f"Jetzt auf {bri}{sir}.", f"Angenehm reduziert auf {bri}{sir}.",
            ])
        return random.choice([
            f"{room_label} auf {bri} gedimmt{sir}.",
            f"{room_label} jetzt auf {bri}{sir}.",
            f"Licht im {room_label} auf {bri}{sir}.",
        ])

    if same_room:
        return random.choice([f"Eingeschaltet{sir}.", f"Ist an{sir}.", f"Erledigt{sir}."])
    return random.choice([
        f"{room_label} eingeschaltet{sir}.",
        f"{room_label} ist an{sir}.",
        f"Licht im {room_label} ist an{sir}.",
    ])


async def handle_structured_action(structured: ActionModel, ws: WebSocket, session_id: str):
    """Dispatch structured ActionModel — mirrors process_message() flow for actions."""

    # Plain reply — no action
    if structured.action == "none":
        text = structured.response or ""
        if text:
            await _speak(ws, session_id, text)
        return

    # LICHT — new structured path, no _parse_licht()
    if structured.action == "licht":
        try:
            params = LichtParameters(**structured.parameters)
            result = await handle_licht_structured(params)
        except Exception as e:
            print(f"  Structured LICHT failed ({e}), falling back to legacy parser", flush=True)
            p = structured.parameters
            payload_parts = [str(p.get("raum", ""))]
            if p.get("zustand"):
                payload_parts.append(str(p["zustand"]))
            if p.get("helligkeit") is not None:
                payload_parts.append(str(p["helligkeit"]))
            result = await execute_action({"type": "LICHT", "payload": " ".join(payload_parts)})
        await _speak(ws, session_id, result or f"Erledigt, {USER_ADDRESS}.")
        return

    # All other actions — convert to legacy dict and use existing execute_action()
    legacy = _structured_to_legacy_action(structured)
    if legacy is None:
        return

    # OPEN — no spoken response
    if structured.action == "open":
        await execute_action(legacy)
        return

    # SCREEN — brief audio hint while vision API runs
    if structured.action == "screen":
        hint_audio = await synthesize_speech("Einen Moment.")
        await ws.send_json({
            "type": "response", "text": "…",
            "audio": base64.b64encode(hint_audio).decode("utf-8") if hint_audio else "",
        })

    try:
        action_result = await execute_action(legacy)
        print(f"  Result: {action_result}", flush=True)
    except Exception as e:
        print(f"  Structured action error: {e}", flush=True)
        action_result = f"Fehler: {e}"

    # Template actions — result is already speakable
    if legacy["type"] in _TEMPLATE_ACTIONS:
        await _speak(ws, session_id, action_result or f"Erledigt, {USER_ADDRESS}.")
        return

    # Complex actions — one-sentence LLM summary (same as legacy path)
    if action_result and "Fehler" not in action_result and "fehlgeschlagen" not in action_result:
        summary_resp = await ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=(
                f"Antworte in einem einzigen kurzen Satz auf Deutsch. "
                f"Keine Einleitung, kein 'Sehr gerne', kein 'Natuerlich', kein 'Gerne', kein 'Hier'. "
                f"Keine Wiederholung der Anfrage. Nur die reine Information. "
                f"Du darfst '{USER_ADDRESS}' genau einmal verwenden, bevorzugt am Satzende. "
                f"KEINE Tags in eckigen Klammern. KEINE ACTION-Tags."
            ),
            messages=[{"role": "user", "content": action_result}],
        )
        summary = summary_resp.content[0].text
        summary, _ = extract_action(summary)
    else:
        summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}."

    await _speak(ws, session_id, summary)

# ──────────────────────────────────────────────────────────────────────────


async def process_message(session_id: str, user_text: str, ws: WebSocket):
    """Process message and send exactly one spoken response via WebSocket."""
    global MAIL_INFO, _last_activate_spoken, _morning_news_text
    if session_id not in conversations:
        conversations[session_id] = []

    if "jarvis activate" in user_text.lower():
        # Debounce: suppress rapid duplicates from WS reconnects / multiple tabs
        now = datetime.now()
        if _last_activate_spoken and (now - _last_activate_spoken).total_seconds() < 30:
            print(f"  Activate debounced — suppressed", flush=True)
            return
        _last_activate_spoken = now

        # Refresh mail cache
        loop = asyncio.get_event_loop()
        fresh = await loop.run_in_executor(None, get_mail_sync)
        async with _mail_lock:
            MAIL_INFO = fresh

        # Morning trigger → record state, let LLM generate the rich greeting
        daily_brief.load()
        _llm_morning = False
        if daily_brief.detect_morning_trigger():
            mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]}
                     for m in fresh if " || " in m]
            tasks = get_tasks_sync()
            await _ensure_weather(loop)
            await _ensure_calendar(loop)
            await _ensure_news()
            daily_brief.record_morning_brief(
                mails=mails, tasks=tasks, reminders=[], notes=OBSIDIAN_INFO,
                weather=_format_weather_str(WEATHER_INFO),
            )
            # Prepare news snippet to speak after LLM brief (deterministic — no LLM creativity)
            if NEWS_INFO:
                top = [f"{a['source']}: {a['title'][:70]}" for a in NEWS_INFO[:2] if a.get('title')]
                _morning_news_text = "Aus Ihren Feeds: " + " — ".join(top) + "." if top else ""
            else:
                _morning_news_text = ""
            print(f"[jarvis] Activate → Morning Brief via LLM (news: {len(NEWS_INFO)} Artikel)", flush=True)
            _llm_morning = True

        # Morning brief already done today → check pause/absence, else short acknowledgment
        if not _llm_morning and daily_brief._data.get("last_morning_brief"):
            if daily_brief.detect_long_absence():
                mails_raw = await loop.run_in_executor(None, get_mail_sync)
                async with _mail_lock:
                    MAIL_INFO = mails_raw
                mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]}
                         for m in mails_raw if " || " in m]
                text = daily_brief.generate_absence_brief(mails, USER_ADDRESS)
                await _speak(ws, session_id, text)
                return

            if daily_brief.detect_pause_return():
                mails_raw = await loop.run_in_executor(None, get_mail_sync)
                async with _mail_lock:
                    MAIL_INFO = mails_raw
                mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]}
                         for m in mails_raw if " || " in m]
                text = daily_brief.generate_pause_brief(mails, USER_ADDRESS)
                if text:
                    await _speak(ws, session_id, text)
                else:
                    daily_brief.update_activity()
                return

            # No pause — simple ready acknowledgment, reset activity timer
            daily_brief.update_activity()
            phrases = [
                f"Ich bin wieder da, {USER_ADDRESS}.",
                f"Wieder online, {USER_ADDRESS}.",
                f"Zurück, {USER_ADDRESS}.",
                f"Bereit, {USER_ADDRESS}.",
            ]
            await asyncio.sleep(0.8)
            await _speak(ws, session_id, random.choice(phrases))
            return

        # Pre-6am / unknown / morning brief → fall through to LLM greeting

    conversations[session_id].append({"role": "user", "content": user_text})
    history = conversations[session_id][-16:]

    response = await ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        system=get_system_prompt(),
        messages=history,
    )
    reply = response.content[0].text
    print(f"  LLM raw: {reply[:200]}", flush=True)

    # ── Try structured JSON path first
    structured = parse_structured_action(reply)
    if structured:
        print(f"  Structured action: {structured.action}", flush=True)
        if user_text.lower().startswith("jarvis activate"):
            await _speak(ws, session_id, structured.response or reply)
            if _morning_news_text:
                _news_snippet = _morning_news_text
                _morning_news_text = ""
                await asyncio.sleep(0.6)
                await _speak(ws, session_id, _news_snippet)
            return
        await handle_structured_action(structured, ws, session_id)
        return

    # ── Fallback: legacy string-based parsing (unchanged)
    spoken_text, action = extract_action(_strip_json_blocks(reply))

    # ── Activate greeting — no actions allowed, speak and done
    if user_text.lower().startswith("jarvis activate"):
        await _speak(ws, session_id, spoken_text)
        if _morning_news_text:
            _news_snippet = _morning_news_text
            _morning_news_text = ""
            await asyncio.sleep(0.6)
            await _speak(ws, session_id, _news_snippet)
        return

    # ── No action → plain reply
    if not action:
        await _speak(ws, session_id, spoken_text)
        return

    # ── Action present — pre-action LLM text is NOT spoken
    print(f"  Action: {action['type']} -> {action['payload'][:100]}", flush=True)

    # Brief audio hint only for SCREEN (screenshot + vision API takes a few seconds)
    if action["type"] == "SCREEN":
        hint_audio = await synthesize_speech("Einen Moment.")
        await ws.send_json({
            "type": "response", "text": "…",
            "audio": base64.b64encode(hint_audio).decode("utf-8") if hint_audio else "",
        })

    try:
        action_result = await execute_action(action)
        print(f"  Result: {action_result}", flush=True)
    except Exception as e:
        print(f"  Action error: {e}", flush=True)
        action_result = f"Fehler: {e}"

    if action["type"] == "OPEN":
        # Kein _speak(), aber History-Eintrag damit der LLM nicht im nächsten
        # Turn denkt die Aktion sei noch offen und sie wiederholt.
        conversations[session_id].append({"role": "assistant", "content": "Seite geöffnet."})
        return

    if action["type"] == "NEWS_SEARCH":
        # Frontend: lesbare Datumsform; TTS: ausgeschriebene Form
        display_result = action_result
        if _last_search_published:
            display_result = action_result.replace(
                _spoken_date(_last_search_published),
                _display_date(_last_search_published),
            )
        await _speak(ws, session_id, action_result or "Erledigt.", display=display_result)
        # Stiller URL-Eintrag: LLM kann bei Follow-up-Fragen die Seite öffnen
        if _last_search_url:
            conversations[session_id].append({
                "role": "assistant",
                "content": f"[Artikel-Link: {_last_search_url} — kann mit OPEN geöffnet werden]"
            })
        return

    # ── Template actions: action_result is already speakable — no LLM needed
    if action["type"] in _TEMPLATE_ACTIONS:
        await _speak(ws, session_id, action_result or "Erledigt.")
        return

    # ── Complex actions (SEARCH, NEWS, SCREEN, TASKS_LIST, KALENDER, MAIL_READ, NOTIZ_LIST):
    #    one-sentence LLM summary, no fluff
    if action_result and "Fehler" not in action_result and "fehlgeschlagen" not in action_result:
        summary_resp = await ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=(
                f"Antworte in einem einzigen kurzen Satz auf Deutsch. "
                f"Keine Einleitung, kein 'Sehr gerne', kein 'Natuerlich', kein 'Gerne', kein 'Hier'. "
                f"Keine Wiederholung der Anfrage. Nur die reine Information. "
                f"Du darfst '{USER_ADDRESS}' genau einmal verwenden, bevorzugt am Satzende. "
                f"KEINE Tags in eckigen Klammern. KEINE ACTION-Tags."
            ),
            messages=[{"role": "user", "content": action_result}],
        )
        summary = summary_resp.content[0].text
        summary, _ = extract_action(summary)
    else:
        summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}."

    await _speak(ws, session_id, summary)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = str(id(ws))
    active_connections.add(ws)
    print(f"[jarvis] Client connected", flush=True)

    try:
        while True:
            data = await ws.receive_json()
            user_text = data.get("text", "").strip()
            if not user_text:
                continue

            print(f"  You:    {user_text}", flush=True)
            await process_message(session_id, user_text, ws)

    except WebSocketDisconnect:
        active_connections.discard(ws)
        conversations.pop(session_id, None)


# ── Dashboard API Endpoints ──────────────────────────────────────────────

@app.get("/api/get_mails_unread")
async def get_mails_unread():
    """Return unread emails — always fetched live from Mail.app."""
    loop = asyncio.get_event_loop()
    fresh = await loop.run_in_executor(None, get_mail_sync)
    mails = []
    for mail_str in fresh:
        parts = mail_str.split(" || ", 1)
        if len(parts) == 2:
            sender, subject = parts
            mails.append({
                "id": f"{sender}_{subject}",
                "sender": sender.strip(),
                "subject": subject.strip(),
                "timestamp": "",
                "unread": True
            })
    return {"mails": mails, "total": len(mails)}


@app.get("/api/get_tasks")
async def get_tasks():
    """Return reminders — always fetched live from Reminders.app."""
    loop = asyncio.get_event_loop()
    fresh = await loop.run_in_executor(None, get_tasks_sync)
    tasks = []
    for i, task_name in enumerate(fresh):
        tasks.append({
            "id": f"task_{i}",
            "title": task_name.strip(),
            "source": "reminders",
            "completed": False
        })
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/get_obsidian_notes")
async def get_obsidian_notes():
    """Return Obsidian notes in structured format for dashboard."""
    notes = []
    if not OBSIDIAN_INBOX:
        return {"notes": notes, "total": 0}

    try:
        import os
        files = sorted([f for f in os.listdir(OBSIDIAN_INBOX) if f.endswith(".md")])
        for fname in files:
            fpath = os.path.join(OBSIDIAN_INBOX, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if _obsidian_note_done(content):
                    continue
                title = fname.replace(".md", "").replace("_", " ")
                preview = content[:100] + ("..." if len(content) > 100 else "")
                notes.append({
                    "id": fname,
                    "title": title,
                    "preview": preview,
                    "content": content,
                    "completed": False
                })
            except Exception:
                continue
    except Exception:
        pass

    return {"notes": notes, "total": len(notes)}


@app.post("/api/complete_task")
async def complete_task(request: Request):
    """Mark a reminder task as complete."""
    data = await request.json()
    task_id = data.get("id", "")
    task_title = data.get("title", "")

    if not task_title:
        return {"success": False, "message": "No task title provided"}

    # Use the same AppleScript approach as REMINDER_DONE action
    script = f'''tell application "Reminders"
    set marked to 0
    repeat with aList in every list
        repeat with r in (every reminder in aList whose completed is false)
            if name of r contains "{task_title}" then
                set completed of r to true
                set marked to marked + 1
            end if
        end repeat
    end repeat
    return marked
end tell'''

    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            global TASKS_INFO
            TASKS_INFO = await asyncio.get_event_loop().run_in_executor(None, get_tasks_sync)
            return {"success": True, "message": f"Task '{task_title}' marked as complete"}
        return {"success": False, "message": "Failed to mark task as complete"}
    except Exception as e:
        return {"success": False, "message": str(e)}


@app.post("/api/complete_note")
async def complete_note(request: Request):
    """Mark an Obsidian note as complete (delete it)."""
    data = await request.json()
    note_id = data.get("id", "")  # filename

    if not OBSIDIAN_INBOX or not note_id:
        return {"success": False, "message": "Invalid note or Obsidian inbox not configured"}

    try:
        import os
        fpath = os.path.join(OBSIDIAN_INBOX, note_id)
        if os.path.exists(fpath) and fpath.startswith(OBSIDIAN_INBOX):
            os.remove(fpath)
            global OBSIDIAN_INFO
            OBSIDIAN_INFO = await asyncio.get_event_loop().run_in_executor(None, get_obsidian_info_sync)
            return {"success": True, "message": f"Note '{note_id}' marked as complete"}
        return {"success": False, "message": "Note not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}



@app.post("/api/open_app")
async def open_app(request: Request):
    """Open a macOS application by name."""
    data = await request.json()
    app_name = data.get("app", "").strip()

    if not app_name:
        return {"success": False, "message": "No app name provided"}

    try:
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return {"success": True, "message": f"Opened {app_name}"}
        else:
            return {"success": False, "message": f"Failed: {result.stderr}"}
    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


# ── Daily Brief Endpoints ──────────────────────────────────────────────────

def _format_weather_str(info: dict) -> str:
    """Format WEATHER_INFO dict to a speakable string for briefs."""
    if not info:
        return ""
    temp = info.get("temp", "")
    desc = info.get("description", "")
    if isinstance(temp, (int, float)):
        temp_str = f"{temp:.1f}".replace(".", ",").rstrip("0").rstrip(",")
    else:
        temp_str = str(temp)
    return f"{temp_str} Grad, {desc}" if desc else f"{temp_str} Grad"


async def _ensure_weather(loop) -> str:
    """Return formatted weather string; fetch on-demand with retry if still None."""
    global WEATHER_INFO
    if WEATHER_INFO is None:
        for attempt in range(3):
            WEATHER_INFO = await loop.run_in_executor(None, get_weather_sync)
            if WEATHER_INFO is not None:
                print(f"[jarvis] Wetter on-demand geladen: {WEATHER_INFO['temp']}° (Versuch {attempt+1})", flush=True)
                break
            if attempt < 2:
                await asyncio.sleep(3)
    return _format_weather_str(WEATHER_INFO)


async def _ensure_calendar(loop) -> None:
    """Fetch calendar on-demand with retry if still empty (startup / HA race condition)."""
    global CALENDAR_INFO
    if not CALENDAR_INFO and HA_URL and HA_TOKEN:
        for attempt in range(3):
            CALENDAR_INFO = await loop.run_in_executor(None, lambda: get_calendar_sync(days=7))
            if CALENDAR_INFO:
                print(f"[jarvis] Kalender on-demand geladen: {len(CALENDAR_INFO)} Termine (Versuch {attempt+1})", flush=True)
                break
            if attempt < 2:
                await asyncio.sleep(3)
        if not CALENDAR_INFO:
            print("[jarvis] Kalender on-demand: keine Termine oder HA nicht erreichbar", flush=True)


async def _ensure_news() -> None:
    """Load news archive on-demand if still empty (startup race condition)."""
    global NEWS_INFO
    if not NEWS_INFO:
        try:
            archive = await news.get_archive()
            NEWS_INFO = archive.get("articles", [])[:10]
            if NEWS_INFO:
                print(f"[jarvis] RSS on-demand geladen: {len(NEWS_INFO)} Artikel", flush=True)
        except Exception as e:
            print(f"[jarvis] RSS on-demand Fehler: {e}", flush=True)


@app.get("/api/daily_brief")
async def get_daily_brief():
    """Determine active trigger and return briefing text."""
    daily_brief.load()
    loop = asyncio.get_event_loop()

    if daily_brief.detect_morning_trigger():
        mails_raw = await loop.run_in_executor(None, get_mail_sync)
        mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]} for m in mails_raw if " || " in m]
        tasks = get_tasks_sync()
        notes = get_obsidian_info_sync()
        weather_str = await _ensure_weather(loop)
        text = daily_brief.generate_morning_brief(
            weather=weather_str,
            mails=mails,
            tasks=tasks,
            reminders=[],
            notes=notes,
            user_address=USER_ADDRESS,
        )
        return {"trigger": "morning", "text": text, "spoken": bool(text)}

    if daily_brief.detect_long_absence():
        mails_raw = await loop.run_in_executor(None, get_mail_sync)
        mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]} for m in mails_raw if " || " in m]
        text = daily_brief.generate_absence_brief(mails, USER_ADDRESS)
        return {"trigger": "long_absence", "text": text, "spoken": bool(text)}

    if daily_brief.detect_pause_return():
        mails_raw = await loop.run_in_executor(None, get_mail_sync)
        mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]} for m in mails_raw if " || " in m]
        text = daily_brief.generate_pause_brief(mails, USER_ADDRESS)
        return {"trigger": "pause", "text": text, "spoken": bool(text)}

    if daily_brief.detect_evening_trigger():
        mails_raw = await loop.run_in_executor(None, get_mail_sync)
        mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]} for m in mails_raw if " || " in m]
        text = daily_brief.generate_evening_brief(mails, _format_weather_str(WEATHER_INFO), USER_ADDRESS)
        return {"trigger": "evening", "text": text, "spoken": bool(text)}

    return {"trigger": "none", "text": "", "spoken": False}


@app.post("/api/daily_brief/manual")
async def manual_daily_brief(request: Request):
    """Manually trigger a specific briefing (e.g. 'evening')."""
    data = await request.json()
    trigger = data.get("trigger", "")
    loop = asyncio.get_event_loop()

    mails_raw = await loop.run_in_executor(None, get_mail_sync)
    mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]} for m in mails_raw if " || " in m]

    if trigger == "morning":
        tasks = get_tasks_sync()
        notes = get_obsidian_info_sync()
        text = daily_brief.generate_morning_brief(_format_weather_str(WEATHER_INFO), mails, tasks, [], notes, USER_ADDRESS)
    elif trigger == "evening":
        text = daily_brief.generate_evening_brief(mails, _format_weather_str(WEATHER_INFO), USER_ADDRESS)
    elif trigger == "absence":
        text = daily_brief.generate_absence_brief(mails, USER_ADDRESS)
    elif trigger == "reset":
        daily_brief.reset()
        return {"trigger": "reset", "text": "Tagesgedächtnis zurückgesetzt.", "spoken": True}
    else:
        return {"error": f"Unbekannter Trigger: {trigger}"}

    return {"trigger": trigger, "text": text, "spoken": bool(text)}


@app.get("/api/daily_brief/memory")
async def get_daily_brief_memory():
    """Debug endpoint — returns full daily brief state."""
    return daily_brief.get_state()


@app.post("/api/wake")
async def wake_notification():
    """Called by wake-monitor.py when system wakes from sleep."""
    global OBSIDIAN_INFO, _last_wake_spoken, _last_activate_spoken
    now = datetime.now()
    if _last_wake_spoken and (now - _last_wake_spoken).total_seconds() < 300:
        print(f"[jarvis] Wake debounced — suppressed", flush=True)
        return {"status": "debounced"}
    _last_wake_spoken = now

    OBSIDIAN_INFO = get_obsidian_info_sync()
    print(f"[jarvis] Wake: {len(OBSIDIAN_INFO)} Obsidian-Notizen", flush=True)

    if not active_connections:
        return {"status": "ok", "notes": len(OBSIDIAN_INFO)}

    daily_brief.load()
    loop = asyncio.get_event_loop()

    # Morgen-Brief: direkt via LLM
    if daily_brief.detect_morning_trigger():
        await _ensure_weather(loop)
        await _ensure_calendar(loop)
        await _ensure_news()
        print(f"[jarvis] Wake → Morning Brief via LLM", flush=True)
        for ws in list(active_connections):
            try:
                await process_message(str(id(ws)), "Jarvis activate", ws)
            except Exception:
                active_connections.discard(ws)
        return {"status": "ok", "notes": len(OBSIDIAN_INFO)}

    # Schritt 1: sofortige Begrüßung — immer, unabhängig von Pause-Schwellenwert
    # _last_activate_spoken setzen damit der anschließende WS-Reconnect-"Jarvis activate"
    # nicht noch eine zweite Ansage auslöst (der Wake-Endpoint übernimmt die Begrüßung).
    _last_activate_spoken = now
    greeting = random.choice([
        f"Willkommen zurück, {USER_ADDRESS}.",
        f"Schön, Sie wieder zu haben, {USER_ADDRESS}.",
    ])
    daily_brief.update_activity()
    for ws in list(active_connections):
        sid = str(id(ws))
        if sid not in conversations:
            conversations[sid] = []
        try:
            await _speak(ws, sid, greeting)
        except Exception as e:
            print(f"[jarvis] Wake _speak error: {e}", flush=True)
            active_connections.discard(ws)
    print(f"[jarvis] Wake → Greeting: '{greeting}'", flush=True)

    # Schritt 2: Mail.app Zeit zum Sync geben, dann neue Mails prüfen
    await asyncio.sleep(9)
    mails_raw = await loop.run_in_executor(None, get_mail_sync)
    mails = [{"sender": m.split(" || ")[0], "subject": m.split(" || ")[1]}
             for m in mails_raw if " || " in m]
    known_ids  = daily_brief.get_known_mail_ids()
    current_ids = [f"{m['sender']}_{m['subject']}" for m in mails]
    diff = daily_brief.compare_mail_ids(known_ids, current_ids)

    # Baseline für nächsten Vergleich aktualisieren
    if daily_brief._data.get("last_morning_brief"):
        daily_brief._data["last_morning_brief"]["mail_ids_mentioned"]  = current_ids
        daily_brief._data["last_morning_brief"]["mail_count_mentioned"] = len(current_ids)
        daily_brief.save()

    mail_text = ""
    if diff["new_count"] > 0:
        n = diff["new_count"]
        new_ids_set = set(diff["new_ids"])
        new_mails = [m for m in mails if f"{m['sender']}_{m['subject']}" in new_ids_set]
        senders = [m.get("sender", "").split("<")[0].strip() or "Unbekannt" for m in new_mails]
        if n == 1:
            mail_text = f"Eine neue Mail von {senders[0]}."
        elif n == 2:
            mail_text = f"{n} neue Mails — von {senders[0]} und {senders[1]}."
        else:
            mail_text = f"{n} neue Mails — unter anderem von {senders[0]}."

    if mail_text:
        print(f"[jarvis] Wake → Mail Update: '{mail_text}'", flush=True)
        for ws in list(active_connections):
            sid = str(id(ws))
            if sid not in conversations:
                conversations[sid] = []
            try:
                await _speak(ws, sid, mail_text)
            except Exception:
                active_connections.discard(ws)
    else:
        print(f"[jarvis] Wake → Keine neuen Mails", flush=True)

    return {"status": "ok", "notes": len(OBSIDIAN_INFO)}


# ── News Endpoints ────────────────────────────────────────────────────────

@app.get("/api/news")
async def get_news():
    """Fetch RSS feeds, deduplicate, archive new articles."""
    try:
        articles = await news.fetch_rss_feeds()
        new_articles = await news.filter_duplicates(articles)
        await news.save_to_archive(new_articles)
        archive = await news.get_archive()
        return {
            "new_articles": new_articles,
            "new_count": len(new_articles),
            "total_archived": len(archive.get("articles", [])),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"[news] ERROR in /api/news: {e}", flush=True)
        return {"error": str(e), "status_code": 500}


@app.get("/api/news/search")
async def search_news(q: str = ""):
    """Case-insensitive search over archived news articles."""
    if not q.strip():
        return {"found": 0, "articles": [], "query": q}
    try:
        results = await news.search_archive(q.strip())
        return {"found": len(results), "articles": results, "query": q}
    except Exception as e:
        print(f"[news] ERROR in /api/news/search: {e}", flush=True)
        return {"error": str(e), "status_code": 500}


@app.post("/api/news/read")
async def mark_news_read(request: Request):
    """Mark an article as read by article_id."""
    try:
        data = await request.json()
        article_id = data.get("article_id", "").strip()
        if not article_id:
            return {"error": "article_id required", "status_code": 400}
        ok = await news.mark_as_read(article_id)
        if ok:
            return {"status": "read", "article_id": article_id}
        return {"error": f"Article '{article_id}' not found", "status_code": 404}
    except Exception as e:
        print(f"[news] ERROR in /api/news/read: {e}", flush=True)
        return {"error": str(e), "status_code": 500}


@app.get("/api/news/unread")
async def get_unread_news(limit: int = 20):
    """Return most recent unread articles from archive — no RSS fetch."""
    try:
        archive = await news.get_archive()
        unread = [a for a in archive.get("articles", []) if not a.get("read", False)]
        unread.sort(key=lambda a: a.get("archived_at", ""), reverse=True)
        return {"articles": unread[:limit], "total_unread": len(unread)}
    except Exception as e:
        print(f"[news] ERROR in /api/news/unread: {e}", flush=True)
        return {"error": str(e), "status_code": 500}


@app.get("/api/rss_feeds")
async def get_rss_feeds():
    try:
        data = news.load_all_feeds()
        feeds = data.get("feeds", [])
        return {
            "feeds": feeds,
            "total": len(feeds),
            "enabled_count": sum(1 for f in feeds if f.get("enabled", False)),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/rss_feeds")
async def bulk_save_feeds(request: Request):
    try:
        body = await request.json()
        feeds = body.get("feeds", [])
        ok = await news.save_feeds(feeds)
        if ok:
            return {"status": "saved", "count": len(feeds)}
        return JSONResponse({"error": "Speichern fehlgeschlagen"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/rss_feeds/add")
async def api_add_feed(request: Request):
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        url = body.get("url", "").strip()
        category = body.get("category", "").strip()
        if not name or not url:
            return JSONResponse({"error": "Name und URL erforderlich"}, status_code=400)
        feed = await news.add_feed(name, url, category)
        return {"status": "added", "feed": feed}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/rss_feeds/{feed_id}/toggle")
async def api_toggle_feed(feed_id: str):
    try:
        new_state = await news.toggle_feed(feed_id)
        if new_state is None:
            return JSONResponse({"error": "Feed nicht gefunden"}, status_code=404)
        return {"status": "toggled", "feed_id": feed_id, "enabled": new_state}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.put("/api/rss_feeds/{feed_id}")
async def api_update_feed(feed_id: str, request: Request):
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        url = body.get("url", "").strip()
        category = body.get("category", "").strip()
        if not name or not url:
            return JSONResponse({"error": "Name und URL erforderlich"}, status_code=400)
        ok = await news.update_feed(feed_id, name, url, category)
        if not ok:
            return JSONResponse({"error": "Feed nicht gefunden"}, status_code=404)
        return {"status": "updated", "feed_id": feed_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/rss_feeds/{feed_id}")
async def api_delete_feed(feed_id: str):
    try:
        ok = await news.delete_feed(feed_id)
        if not ok:
            return JSONResponse({"error": "Feed nicht gefunden"}, status_code=404)
        return {"status": "deleted", "feed_id": feed_id}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/maintenance/status")
async def maintenance_status():
    try:
        archive = await news.get_archive()
        article_count = len(archive.get("articles", []))
        last_fetch = archive.get("last_fetch")
        threshold = daily_brief._data["pause_tracking"]["pause_threshold_minutes"]
        last_brief = daily_brief._data.get("last_morning_brief")
        last_brief_time = (
            last_brief["timestamp"][:16].replace("T", " ") if last_brief else None
        )
        return {
            "news_articles": article_count,
            "news_last_fetch": last_fetch,
            "brief_threshold_minutes": threshold,
            "brief_last_morning": last_brief_time,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/maintenance/reset_news")
async def maintenance_reset_news():
    try:
        async with news._news_lock:
            news._write_archive({
                "articles": [], "max_entries": 10000,
                "cleanup_strategy": "FIFO", "last_fetch": None,
            })
        return {"status": "reset", "type": "news"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/maintenance/reset_brief")
async def maintenance_reset_brief():
    try:
        daily_brief._data = daily_brief._fresh_state()
        daily_brief.save()
        return {"status": "reset", "type": "brief"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/maintenance/reset_all")
async def maintenance_reset_all():
    try:
        async with news._news_lock:
            news._write_archive({
                "articles": [], "max_entries": 10000,
                "cleanup_strategy": "FIFO", "last_fetch": None,
            })
        daily_brief._data = daily_brief._fresh_state()
        daily_brief.save()
        return {"status": "reset", "type": "all"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/maintenance/set_threshold")
async def maintenance_set_threshold(request: Request):
    try:
        body = await request.json()
        minutes = int(body.get("minutes", 30))
        if not 1 <= minutes <= 480:
            return JSONResponse(
                {"error": "Threshold muss zwischen 1 und 480 Minuten liegen"},
                status_code=400,
            )
        daily_brief._data["pause_tracking"]["pause_threshold_minutes"] = minutes
        daily_brief.save()
        return {"status": "saved", "threshold_minutes": minutes}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/restart")
async def restart_server():
    """Terminate the process — launchd KeepAlive will respawn it."""
    import signal as _signal
    loop = asyncio.get_event_loop()
    loop.call_later(0.5, lambda: os.kill(os.getpid(), _signal.SIGTERM))
    return {"status": "restarting"}


@app.get("/config")
async def serve_config():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "config.html"))


@app.get("/handbuch")
async def serve_handbuch():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "handbuch.html"))


@app.get("/api/config")
async def get_config_api():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


@app.post("/api/config")
async def save_config_api(request: Request):
    global ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
    global USER_NAME, USER_ADDRESS, CITY, LAT, LON
    global KACHELMANN_KEY, HA_URL, HA_TOKEN, ai, WAKE_GREETING_ENABLED

    data = await request.json()

    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)

    allowed = [
        "anthropic_api_key", "elevenlabs_api_key", "elevenlabs_voice_id",
        "user_name", "user_address", "city", "timezone", "lat", "lon",
        "kachelmann_api_key", "ha_url", "ha_token", "ha_enabled",
        "workspace_path", "obsidian_inbox_path", "browser_url",
        "spotify_track", "programs", "wake_greeting_enabled",
        "window_layout",
    ]
    for field in allowed:
        if field in data:
            cfg[field] = data[field]

    errors = []
    if cfg.get("anthropic_api_key") and not cfg["anthropic_api_key"].startswith("sk-ant-"):
        errors.append("Anthropic API Key hat unerwartetes Format")

    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    # Update in-memory globals so Jarvis uses new settings without restart
    ANTHROPIC_API_KEY = cfg.get("anthropic_api_key", ANTHROPIC_API_KEY)
    ELEVENLABS_API_KEY = cfg.get("elevenlabs_api_key", ELEVENLABS_API_KEY)
    ELEVENLABS_VOICE_ID = cfg.get("elevenlabs_voice_id", ELEVENLABS_VOICE_ID)
    USER_NAME = cfg.get("user_name", USER_NAME)
    USER_ADDRESS = cfg.get("user_address", USER_ADDRESS)
    CITY = cfg.get("city", CITY)
    LAT = cfg.get("lat", LAT)
    LON = cfg.get("lon", LON)
    KACHELMANN_KEY = cfg.get("kachelmann_api_key", KACHELMANN_KEY)
    HA_URL = cfg.get("ha_url", "").rstrip("/") if cfg.get("ha_enabled", True) else ""
    HA_TOKEN = cfg.get("ha_token", HA_TOKEN)
    WAKE_GREETING_ENABLED = cfg.get("wake_greeting_enabled", True)
    ai = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    print(f"[jarvis] Config gespeichert via UI", flush=True)
    return {"status": "saved", "errors": errors}


@app.get("/api/apps")
async def get_available_apps():
    """List all .app bundles from /Applications + key System apps"""
    apps = set()

    # Scan /Applications
    apps_dir = "/Applications"
    try:
        if os.path.isdir(apps_dir):
            for item in os.listdir(apps_dir):
                if item.endswith('.app'):
                    app_name = item[:-4]
                    apps.add(app_name)
    except Exception as e:
        print(f"[jarvis] Error reading /Applications: {e}", flush=True)

    # Add key System apps (fast, no full scan)
    system_apps = ["Mail", "Reminders", "Notes", "Calendar", "Contacts", "Messages"]
    for app in system_apps:
        apps.add(app)

    return {"apps": sorted(list(apps))}



app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")), name="static")


@app.get("/api/version")
async def get_version():
    return _VERSION_INFO


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))


@app.get("/dashboard")
async def serve_dashboard():
    return RedirectResponse(url="/", status_code=301)


async def startup_and_refresh():
    """Load all startup data async without blocking the server, retry weather if network not ready,
    then refresh every 30 minutes."""
    global WEATHER_INFO, TASKS_INFO, MAIL_INFO, CALENDAR_INFO, OBSIDIAN_INFO
    loop = asyncio.get_event_loop()

    print("[jarvis] Startup: Lade Daten...", flush=True)

    # Tasks, mail, calendar, obsidian don't need external network — load immediately
    TASKS_INFO = await loop.run_in_executor(None, get_tasks_sync)
    MAIL_INFO = await loop.run_in_executor(None, get_mail_sync)
    CALENDAR_INFO = await loop.run_in_executor(None, lambda: get_calendar_sync(days=7))
    OBSIDIAN_INFO = await loop.run_in_executor(None, get_obsidian_info_sync)
    print(f"[jarvis] Tasks: {len(TASKS_INFO)} geladen", flush=True)
    print(f"[jarvis] Mails: {len(MAIL_INFO)} ungelesen", flush=True)
    print(f"[jarvis] Kalender: {len(CALENDAR_INFO)} Termine (7 Tage)", flush=True)
    print(f"[jarvis] Obsidian: {len(OBSIDIAN_INFO)} offene Notizen", flush=True)

    try:
        archive = await news.get_archive()
        NEWS_INFO = archive.get("articles", [])[:10]
        print(f"[jarvis] RSS-Archiv: {len(NEWS_INFO)} Artikel geladen", flush=True)
    except Exception:
        pass

    # Weather requires network — retry every 30s until ready (max 20 min)
    WEATHER_INFO = await loop.run_in_executor(None, get_weather_sync)
    if WEATHER_INFO is None:
        print("[jarvis] Wetter nicht verfügbar — starte Retry alle 30s...", flush=True)
        for attempt in range(40):
            await asyncio.sleep(30)
            WEATHER_INFO = await loop.run_in_executor(None, get_weather_sync)
            if WEATHER_INFO is not None:
                print(f"[jarvis] Wetter nach {(attempt+1)*30}s geladen: {WEATHER_INFO['temp']}°", flush=True)
                break
    else:
        print(f"[jarvis] Wetter: {WEATHER_INFO}", flush=True)

    # Normal 30-minute refresh loop
    while True:
        await asyncio.sleep(30 * 60)
        print("[jarvis] Periodic refresh...", flush=True)
        WEATHER_INFO = await loop.run_in_executor(None, get_weather_sync)
        TASKS_INFO = await loop.run_in_executor(None, get_tasks_sync)
        MAIL_INFO = await loop.run_in_executor(None, get_mail_sync)
        CALENDAR_INFO = await loop.run_in_executor(None, lambda: get_calendar_sync(days=7))
        OBSIDIAN_INFO = await loop.run_in_executor(None, get_obsidian_info_sync)
        print(f"[jarvis] Refresh done: Tasks={len(TASKS_INFO)}, Mails={len(MAIL_INFO)}, Kalender={len(CALENDAR_INFO)}, Obsidian={len(OBSIDIAN_INFO)}", flush=True)


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(startup_and_refresh())
    yield

app.router.lifespan_context = lifespan


# ── Config API Endpoints ──────────────────────────────────────────────

@app.post("/api/test_key")
async def test_key(request: Request):
    """Test API key validity."""
    data = await request.json()
    key_type = data.get("type", "").lower()
    key = data.get("key", "").strip()

    if not key:
        return {"success": False, "error": "No key provided"}

    try:
        if key_type == "anthropic":
            client = anthropic.Anthropic(api_key=key)
            msg = await asyncio.to_thread(
                client.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return {"success": True}
        elif key_type == "elevenlabs":
            # /v1/voices is restricted on Starter plans — use a minimal TTS request instead
            resp = await http.post(
                "https://api.elevenlabs.io/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={"text": "x", "model_id": "eleven_multilingual_v2", "output_format": "mp3_22050_32"},
            )
            if resp.status_code == 200:
                return {"success": True}
            if resp.status_code == 401:
                return {"success": False, "error": "Ungültiger API Key"}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        else:
            return {"success": False, "error": "Unknown key type"}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


@app.post("/api/preview_voice")
async def preview_voice(request: Request):
    """Generate and return audio preview of a voice."""
    data = await request.json()
    voice_id = data.get("voice_id", "").strip()

    if not voice_id:
        return {"success": False, "error": "No voice_id"}

    try:
        audio_data = await synthesize_speech("Hallo, ich bin Jarvis.", voice_id)
        if audio_data:
            return {"audio": base64.b64encode(audio_data).decode("utf-8")}
        return {"success": False, "error": "TTS failed"}
    except Exception as e:
        return {"success": False, "error": str(e)[:100]}


@app.get("/api/elevenlabs_voices")
async def get_elevenlabs_voices_list(key: str = ""):
    """Get list of available ElevenLabs voices. Accepts optional ?key= to use a specific API key."""
    api_key = key.strip() or ELEVENLABS_API_KEY
    try:
        resp = await http.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": api_key},
        )
        if resp.status_code == 200:
            voices = sorted(
                [{"voice_id": v["voice_id"], "name": v["name"]} for v in resp.json().get("voices", [])],
                key=lambda v: v["name"]
            )
            if voices:
                return {"voices": voices}
        # Fallback: return the currently configured voice so dropdown is never empty
        if ELEVENLABS_VOICE_ID:
            return {"voices": [{"voice_id": ELEVENLABS_VOICE_ID, "name": "Aktuelle Voice (Fallback)"}], "fallback": True}
        return {"voices": [], "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        if ELEVENLABS_VOICE_ID:
            return {"voices": [{"voice_id": ELEVENLABS_VOICE_ID, "name": "Aktuelle Voice (Fallback)"}], "fallback": True}
        return {"voices": [], "error": str(e)[:80]}


@app.post("/api/reset_config")
async def reset_config_api():
    """Reset config to defaults."""
    try:
        with open(CONFIG_PATH.replace("config.json", "config.example.json"), "r") as f:
            default_cfg = json.load(f)
        with open(CONFIG_PATH, "w") as f:
            json.dump(default_cfg, f, indent=2)
        return {"success": True}
    except:
        return {"success": False, "error": "Reset failed"}


# ── Voice Library Endpoints ───────────────────────────────────────────────

@app.get("/api/voices")
async def get_voices():
    """Return voice library from voice.json."""
    return _load_voice_db()


@app.post("/api/voices/save")
async def save_voices(request: Request):
    """Save complete voice library to voice.json."""
    global _voice_db
    data = await request.json()
    if "voices" not in data or "active_voice_id" not in data:
        return {"success": False, "error": "Ungültiges Format"}
    _voice_db = data
    with open(VOICE_PATH, "w") as f:
        json.dump(_voice_db, f, indent=2, ensure_ascii=False)
    return {"success": True}


@app.post("/api/voices/activate")
async def activate_voice(request: Request):
    """Set active voice and hot-reload ELEVENLABS_VOICE_ID."""
    global ELEVENLABS_VOICE_ID, _voice_db
    data = await request.json()
    voice_id = data.get("voice_id", "").strip()
    if not voice_id:
        return {"success": False, "error": "Keine voice_id angegeben"}
    _voice_db = _load_voice_db()
    _voice_db["active_voice_id"] = voice_id
    with open(VOICE_PATH, "w") as f:
        json.dump(_voice_db, f, indent=2, ensure_ascii=False)
    ELEVENLABS_VOICE_ID = voice_id
    print(f"[jarvis] Voice aktiviert: {voice_id}", flush=True)
    return {"success": True}

# ──────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8340
    print("=" * 50, flush=True)
    print("  J.A.R.V.I.S. V2 Server", flush=True)
    print(f"  http://localhost:{port}", flush=True)
    print("=" * 50, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port)
