"""
Jarvis V2 — Voice AI Server
FastAPI backend: receives speech text, thinks with Claude Haiku,
speaks with ElevenLabs, controls browser with Playwright.
"""

import asyncio
import base64
import json
import os
import re
import subprocess
import time

import anthropic
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Load config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

ANTHROPIC_API_KEY = config["anthropic_api_key"]
ELEVENLABS_API_KEY = config["elevenlabs_api_key"]
ELEVENLABS_VOICE_ID = config.get("elevenlabs_voice_id", "rDmv3mOhK6TnhYWckFaD")
USER_NAME = config.get("user_name", "Julian")
USER_ADDRESS = config.get("user_address", "Sir")
CITY = config.get("city", "Hamburg")
LAT = config.get("lat", 53.55)
LON = config.get("lon", 10.00)
KACHELMANN_KEY = config.get("kachelmann_api_key", "")
TASKS_FILE = config.get("obsidian_inbox_path", "")
HA_URL = config.get("ha_url", "").rstrip("/")
HA_TOKEN = config.get("ha_token", "")

LIGHT_MAP: dict[str, str | list[str]] = {
    "alle":          "light.alle_lichter",
    "alles":         "light.alle_lichter",
    "wohnzimmer":    "light.wohnzimmer",
    "küche":         "light.kuche",
    "kuche":         "light.kuche",
    "büro":          "light.buro",
    "buro":          "light.buro",
    "arbeitszimmer": "light.buro",
    "flur":          "light.flur",
    "schlafzimmer":  "light.schlafzimmer",
    "balkon":        "light.balkon_led",
    "iris":          "light.hue_iris",
    "hue go":        "light.hue_go_1",
    "sideboard":     ["light.sideboard_links", "light.sideboard_rechts"],
    "nachtschrank":  ["light.nachtschrank_links", "light.nachtschrank_rechts"],
}

ai = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
http = httpx.AsyncClient(timeout=30)

app = FastAPI()

import browser_tools
import screen_capture


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
    """Read open reminders due today, tomorrow or overdue (no due date included)."""
    script = '''
tell application "Reminders"
    set cutoff to current date
    set hours of cutoff to 23
    set minutes of cutoff to 59
    set seconds of cutoff to 59
    set cutoff to cutoff + (1 * days)
    set result to {}
    repeat with r in (every reminder whose completed is false)
        set dd to due date of r
        if dd is missing value or dd ≤ cutoff then
            set end of result to name of r
        end if
    end repeat
    return result
end tell'''
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return [i.strip() for i in r.stdout.strip().split(",") if i.strip()]
        return []
    except:
        return []


_DE_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


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

WEATHER_INFO = ""
TASKS_INFO = []
MAIL_INFO = []
CALENDAR_INFO = []
refresh_data()

# Action parsing
ACTION_PATTERN = re.compile(r'\[ACTION:(\w+)\]\s*(.*?)$', re.DOTALL | re.MULTILINE)

conversations: dict[str, list] = {}

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

    return f"""Du bist Jarvis, der KI-Assistent von Tony Stark aus Iron Man. Dein Dienstherr ist {USER_NAME}. Er wohnt in {CITY}. Du sprichst ausschliesslich Deutsch. {USER_NAME} moechte mit "{USER_ADDRESS}" angesprochen und gesiezt werden. Nutze "Sie" als Pronomen — FALSCH: "Sir planen", RICHTIG: "Sie planen, Sir". Dein Ton ist trocken, sarkastisch und britisch-hoeflich - wie ein Butler der alles gesehen hat und trotzdem loyal bleibt. Du machst subtile, trockene Bemerkungen, bist aber niemals respektlos. Wenn Sir eine offensichtliche Frage stellt, darfst du mit elegantem Sarkasmus antworten. Du bist hochintelligent, effizient und immer einen Schritt voraus. Halte deine Antworten kurz - maximal 3 Saetze. Du kommentierst fragwuerdige Entscheidungen hoeflich aber spitz.

WICHTIG: Schreibe NIEMALS Regieanweisungen, Emotionen oder Tags in eckigen Klammern wie [sarcastic] [formal] [amused] [dry] oder aehnliches. Dein Sarkasmus muss REIN durch die Wortwahl kommen. Alles was du schreibst wird laut vorgelesen.

AUSSPRACHE: Schreibe Temperaturen immer als "X Grad" oder "X Komma Y Grad" — niemals als "°C". Schreibe Uhrzeiten immer als "X Uhr" (z.B. "20 Uhr") oder "X Uhr Y" (z.B. "20 Uhr 5") — niemals als "20:00 Uhr" oder "20:05 Uhr".

Du hast die volle Kontrolle ueber den Browser von {USER_NAME}. Du kannst im Internet suchen, Webseiten oeffnen und den Bildschirm sehen. Wenn Sir dich bittet etwas nachzuschauen, zu recherchieren, zu googeln, eine Seite zu oeffnen, oder irgendetwas im Internet zu tun — nutze IMMER eine Aktion. Frag nicht ob du es tun sollst, tu es einfach.

AKTIONEN - Schreibe die passende Aktion ans ENDE deiner Antwort. Der Text VOR der Aktion wird vorgelesen, die Aktion selbst wird still ausgefuehrt.
[ACTION:SEARCH] suchbegriff - Internet durchsuchen und Ergebnisse zusammenfassen
[ACTION:OPEN] url - URL im Browser oeffnen
[ACTION:SCREEN] - Bildschirm ansehen und beschreiben. WICHTIG: Bei SCREEN schreibe NUR die Aktion, KEINEN Text davor. Also NUR "[ACTION:SCREEN]" und sonst nichts.
[ACTION:NEWS] - Aktuelle Weltnachrichten abrufen. Nutze diese Aktion wenn nach News, Nachrichten, was in der Welt passiert, aktuelle Lage oder Weltgeschehen gefragt wird. Schreibe einen kurzen Satz davor wie "Ich schaue nach den aktuellen Nachrichten."
[ACTION:REMINDER_ADD] aufgabe - Neue Erinnerung in die Inbox schreiben. Nutze diese Aktion wenn Sir etwas hinzufuegen, notieren, merken oder erinnert werden moechte.
[ACTION:REMINDER_DONE] stichwort - Erinnerung als erledigt markieren. Nutze diese Aktion wenn Sir sagt dass etwas erledigt, abgehakt oder fertig ist.
[ACTION:TASKS_LIST] - Aktuelle Aufgabenliste live aus Reminders laden und vorlesen. Nutze diese Aktion IMMER wenn Sir fragt welche Aufgaben es gibt, was auf der Liste steht, oder was noch offen ist.
[ACTION:MAIL_READ] stichwort - Mails lesen. Ohne Stichwort: alle Ungelesenen auflisten. Mit Stichwort (z.B. Absendername): Inhalt der passenden Mail vorlesen.
[ACTION:KALENDER] zeitraum - Kalendertermine live abrufen. Zeitraum: "heute" (1 Tag), "morgen" (2 Tage), "woche" (7 Tage, Standard), "monat" (30 Tage), "60tage" (60 Tage), oder eine Zahl 1-60. Nutze diese Aktion IMMER wenn Sir nach Terminen fragt. Für Fragen wie "was ist am 1. Mai" nutze "woche" oder "monat" je nach Datum. Zeige nur den Titel und das Datum — nenne KEINEN Kalender-Namen, der in eckigen Klammern stehen könnte.
[ACTION:LICHT] raum befehl - Licht per Home Assistant steuern. Raeume: alle, wohnzimmer, kueche, buero, flur, schlafzimmer, balkon, nachtschrank, sideboard, iris. Befehle: "an", "aus", oder Prozentzahl fuer Helligkeit (z.B. "50"). Beispiele: "wohnzimmer an", "alles aus", "buero 50". Nutze diese Aktion IMMER wenn Sir Licht ein- oder ausschalten oder dimmen moechte.

WENN {USER_NAME} "Jarvis activate" sagt:
- Begruesse ihn passend zur Tageszeit (aktuelle Zeit: {{time}}).
- Gebe eine kurze Info ueber das Wetter — Temperatur und ob Sonne/klar/bewoelkt/Regen, und wie es sich anfuehlt. Keine Luftfeuchtigkeit.
- Fasse die Aufgaben kurz als Ueberblick in einem Satz zusammen, ohne dabei jede einzelne Aufgabe einfach vorzulesen. Gebe gerne einen humorvollen Kommentar am Ende an.
- Erwaehne kurz die Anzahl ungelesener Mails. Wenn keine: lass es weg.
- Erwaehne kurz anstehende Termine heute oder morgen, falls vorhanden.
- Sei kreativ bei der Begruessung.

=== AKTUELLE DATEN ==={weather_block}{task_block}{mail_block}{cal_block}
==="""


def get_system_prompt():
    return build_system_prompt().replace("{time}", time.strftime("%H:%M"))


def extract_action(text: str):
    match = ACTION_PATTERN.search(text)
    if match:
        clean = text[:match.start()].strip()
        return clean, {"type": match.group(1), "payload": match.group(2).strip()}
    return text, None


async def synthesize_speech(text: str) -> bytes:
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

    audio_parts = []
    for chunk in chunks:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        try:
            resp = await http.post(url, headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }, json={
                "text": chunk,
                "model_id": "eleven_turbo_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.85},
            })
            print(f"  TTS chunk status: {resp.status_code}, size: {len(resp.content)}", flush=True)
            if resp.status_code == 200:
                audio_parts.append(resp.content)
            else:
                print(f"  TTS error body: {resp.text[:200]}", flush=True)
        except Exception as e:
            print(f"  TTS EXCEPTION: {e}", flush=True)

    return b"".join(audio_parts)


async def execute_action(action: dict) -> str:
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

    elif t == "SCREEN":
        return await screen_capture.describe_screen(ai)

    elif t == "NEWS":
        result = await browser_tools.fetch_news()
        return result

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
            global TASKS_INFO
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
        script = f'''tell application "Reminders"
    repeat with r in (every reminder whose completed is false)
        if name of r contains "{keyword}" then
            set completed of r to true
        end if
    end repeat
end tell'''
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            TASKS_INFO = get_tasks_sync()
            return f"Erinnerung abgehakt: {keyword}"
        return "Fehler beim Abhaken der Erinnerung"

    elif t == "LICHT":
        if not HA_URL or not HA_TOKEN:
            return "Home Assistant nicht konfiguriert."
        words = p.strip().lower().split()
        if not words:
            return "Kein Lichtbefehl angegeben."

        cmd = "turn_on"
        brightness: int | None = None
        room_words: list[str] = []

        for i, word in enumerate(words):
            w = word.rstrip("%")
            if word in ("an", "ein", "einschalten"):
                cmd = "turn_on"
                room_words = [x for x in words[:i] if x not in ("das", "die", "den", "licht")]
                break
            elif word in ("aus", "ausschalten"):
                cmd = "turn_off"
                room_words = [x for x in words[:i] if x not in ("das", "die", "den", "licht")]
                break
            elif w.isdigit():
                brightness = int(w)
                cmd = "turn_on"
                room_words = [x for x in words[:i] if x not in ("das", "die", "den", "licht", "auf")]
                break
        else:
            room_words = [x for x in words if x not in ("das", "die", "den", "licht")]

        room = " ".join(room_words) if room_words else "alle"
        # normalize umlauts for lookup
        room_norm = room.replace("ü", "u").replace("ö", "o").replace("ä", "a")
        entity = LIGHT_MAP.get(room) or LIGHT_MAP.get(room_norm) or LIGHT_MAP["alle"]
        entities = entity if isinstance(entity, list) else [entity]

        headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
        for eid in entities:
            payload: dict = {"entity_id": eid}
            if brightness is not None:
                payload["brightness_pct"] = brightness
            try:
                await http.post(f"{HA_URL}/api/services/light/{cmd}", headers=headers, json=payload)
            except Exception as e:
                return f"Home Assistant Fehler: {e}"

        room_label = room.capitalize() if room != "alle" else "Alle Lichter"
        if cmd == "turn_off":
            return f"{room_label} ausgeschaltet."
        elif brightness is not None:
            return f"{room_label} auf {brightness}% gedimmt."
        return f"{room_label} eingeschaltet."

    return ""


async def process_message(session_id: str, user_text: str, ws: WebSocket):
    """Process message and send responses via WebSocket."""
    if session_id not in conversations:
        conversations[session_id] = []

    # Refresh weather + tasks on activate
    if "activate" in user_text.lower():
        refresh_data()

    conversations[session_id].append({"role": "user", "content": user_text})
    history = conversations[session_id][-16:]

    # LLM call
    response = await ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=get_system_prompt(),
        messages=history,
    )
    reply = response.content[0].text
    print(f"  LLM raw: {reply[:200]}", flush=True)
    spoken_text, action = extract_action(reply)

    # Speak the main response immediately
    if spoken_text:
        audio = await synthesize_speech(spoken_text)
        print(f"  Jarvis: {spoken_text[:80]}", flush=True)
        print(f"  Audio bytes: {len(audio)}", flush=True)
        conversations[session_id].append({"role": "assistant", "content": spoken_text})
        await ws.send_json({
            "type": "response",
            "text": spoken_text,
            "audio": base64.b64encode(audio).decode("utf-8") if audio else "",
        })

    # Execute action if any
    if action:
        print(f"  Action: {action['type']} -> {action['payload'][:100]}", flush=True)

        # Quick voice feedback for SCREEN so user knows Jarvis is working
        if action["type"] == "SCREEN":
            hint = "Lassen Sie mich einen Blick auf Ihren Bildschirm werfen."
            hint_audio = await synthesize_speech(hint)
            await ws.send_json({
                "type": "response",
                "text": hint,
                "audio": base64.b64encode(hint_audio).decode("utf-8") if hint_audio else "",
            })

        try:
            action_result = await execute_action(action)
            print(f"  Result: {action_result}", flush=True)
        except Exception as e:
            print(f"  Action error: {e}", flush=True)
            action_result = f"Fehler: {e}"

        if action["type"] == "OPEN":
            # Just opened browser, nothing to summarize
            return

        # SEARCH, BROWSE, SCREEN — summarize results
        if action_result and "fehlgeschlagen" not in action_result:
            summary_resp = await ai.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=250,
                system=f"Du bist Jarvis. Fasse die folgenden Informationen KURZ auf Deutsch zusammen, maximal 3 Saetze, im Jarvis-Stil. Sprich den Nutzer als {USER_ADDRESS} an. KEINE Tags in eckigen Klammern. KEINE ACTION-Tags.",
                messages=[{"role": "user", "content": f"Fasse zusammen:\n\n{action_result}"}],
            )
            summary = summary_resp.content[0].text
            summary, _ = extract_action(summary)
        else:
            summary = f"Das hat leider nicht funktioniert, {USER_ADDRESS}."

        audio2 = await synthesize_speech(summary)
        conversations[session_id].append({"role": "assistant", "content": summary})
        await ws.send_json({
            "type": "response",
            "text": summary,
            "audio": base64.b64encode(audio2).decode("utf-8") if audio2 else "",
        })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = str(id(ws))
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
        conversations.pop(session_id, None)


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))


async def periodic_refresh():
    """Refresh weather, tasks, mail and calendar every 30 minutes."""
    while True:
        await asyncio.sleep(30 * 60)
        print("[jarvis] Periodic refresh...", flush=True)
        refresh_data()


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(periodic_refresh())
    yield

app.router.lifespan_context = lifespan


if __name__ == "__main__":
    import uvicorn
    print("=" * 50, flush=True)
    print("  J.A.R.V.I.S. V2 Server", flush=True)
    print(f"  http://localhost:8340", flush=True)
    print("=" * 50, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8340)
