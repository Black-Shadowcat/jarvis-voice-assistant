import json
import os
import random
import shutil
from datetime import datetime, date
from typing import Optional

DATA_PATH    = os.path.join(os.path.dirname(__file__), "..", "data", "daily_brief_memory.json")
ARCHIVE_DIR  = os.path.join(os.path.dirname(__file__), "..", "data", "daily_brief_archive")

_EMPTY_STATE = {
    "date": "",
    "last_morning_brief": None,
    "pause_tracking": {
        "last_activity": None,
        "pause_threshold_minutes": 30,
        "long_absence_threshold_minutes": 90,
    },
    "status_checks": [],
    "evening_briefing": {
        "done": False,
        "scheduled_after": "17:00",
    },
}


class DailyBrief:
    def __init__(self):
        self._data: dict = self.load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def load(self) -> dict:
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("date") != str(date.today()):
                data = self._fresh_state(preserve_from=data)
                self._save(data)
        except (FileNotFoundError, json.JSONDecodeError):
            data = self._fresh_state()
            self._save(data)
        self._data = data
        return data

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self) -> None:
        self._save(self._data)

    def _fresh_state(self, preserve_from: dict = None) -> dict:
        state = json.loads(json.dumps(_EMPTY_STATE))
        state["date"] = str(date.today())
        if preserve_from:
            pt = preserve_from.get("pause_tracking", {})
            for key in ("pause_threshold_minutes", "long_absence_threshold_minutes"):
                if key in pt:
                    state["pause_tracking"][key] = pt[key]
        return state

    # ── Archive & Reset ───────────────────────────────────────────────────────

    def archive(self) -> None:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        dest = os.path.join(ARCHIVE_DIR, f"{self._data.get('date', 'unknown')}.json")
        shutil.copy2(DATA_PATH, dest)

    def reset(self) -> None:
        self.archive()
        self._data = self._fresh_state(preserve_from=self._data)
        self.save()

    # ── Activity Tracking ─────────────────────────────────────────────────────

    def update_activity(self) -> None:
        self._data["pause_tracking"]["last_activity"] = datetime.now().isoformat()
        self.save()

    def _minutes_since_last_activity(self) -> Optional[float]:
        ts = self._data["pause_tracking"].get("last_activity")
        if not ts:
            return None
        delta = datetime.now() - datetime.fromisoformat(ts)
        return delta.total_seconds() / 60

    # ── Trigger Detection ─────────────────────────────────────────────────────

    def detect_morning_trigger(self) -> bool:
        brief = self._data.get("last_morning_brief")
        if brief:
            return False
        return datetime.now().hour >= 6

    def detect_pause_return(self) -> bool:
        minutes = self._minutes_since_last_activity()
        if minutes is None:
            return False
        threshold = self._data["pause_tracking"]["pause_threshold_minutes"]
        long_threshold = self._data["pause_tracking"]["long_absence_threshold_minutes"]
        return threshold <= minutes < long_threshold

    def detect_long_absence(self) -> bool:
        minutes = self._minutes_since_last_activity()
        if minutes is None:
            return False
        threshold = self._data["pause_tracking"]["long_absence_threshold_minutes"]
        return minutes >= threshold

    def detect_evening_trigger(self) -> bool:
        if self._data["evening_briefing"]["done"]:
            return False
        scheduled = self._data["evening_briefing"]["scheduled_after"]
        hour, minute = map(int, scheduled.split(":"))
        now = datetime.now()
        return now.hour > hour or (now.hour == hour and now.minute >= minute)

    # ── Mail ID Tracking ──────────────────────────────────────────────────────

    def compare_mail_ids(self, previous_ids: list, current_ids: list) -> dict:
        prev = set(previous_ids)
        curr = set(current_ids)
        return {
            "new_ids":     list(curr - prev),
            "deleted_ids": list(prev - curr),
            "unchanged_ids": list(prev & curr),
            "new_count":   len(curr - prev),
            "deleted_count": len(prev - curr),
            "current_count": len(curr),
        }

    def get_known_mail_ids(self) -> list:
        brief = self._data.get("last_morning_brief")
        if not brief:
            return []
        return brief.get("mail_ids_mentioned", [])

    # ── Briefing Generators ───────────────────────────────────────────────────

    def record_morning_brief(self, mails: list, tasks: list, reminders: list,
                              notes: list, weather: str = "") -> None:
        """Record morning brief state without generating text (LLM handles the greeting)."""
        mail_ids = [f"{m.get('sender','')}_{m.get('subject','')}" for m in mails]
        self._data["last_morning_brief"] = {
            "timestamp": datetime.now().isoformat(),
            "trigger": "first_activation",
            "mail_ids_mentioned": mail_ids,
            "mail_count_mentioned": len(mails),
            "task_count_mentioned": len(tasks),
            "reminder_count_mentioned": len(reminders),
            "note_pending_mentioned": len(notes) > 0,
            "weather_mentioned": weather,
        }
        self.update_activity()

    def generate_morning_brief(self, weather: str, mails: list, tasks: list,
                                reminders: list, notes: list, user_address: str) -> str:
        mail_ids = [f"{m.get('sender','')}_{m.get('subject','')}" for m in mails]

        self._data["last_morning_brief"] = {
            "timestamp": datetime.now().isoformat(),
            "trigger": "first_activation",
            "mail_ids_mentioned": mail_ids,
            "mail_count_mentioned": len(mails),
            "task_count_mentioned": len(tasks),
            "reminder_count_mentioned": len(reminders),
            "note_pending_mentioned": len(notes) > 0,
            "weather_mentioned": weather,
        }
        self.update_activity()

        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=Mon, 6=Sun
        day_names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

        if hour < 11:
            greeting = "Guten Morgen"
        elif hour < 14:
            greeting = "Guten Tag"
        elif hour < 18:
            greeting = "Guten Nachmittag"
        else:
            greeting = "Guten Abend"

        parts = [f"{greeting}, {user_address}."]

        # Day context (morning only)
        if hour < 13:
            day = day_names[weekday]
            if weekday >= 5:
                parts.append(f"Genießen Sie Ihren {day}.")
            else:
                parts.append(f"Es ist {day}.")

        # Weather + advisory
        if weather:
            parts.append(weather.rstrip(".") + ".")
            w = weather.lower()
            if any(x in w for x in ["regen", "schauer", "niesel", "sprühregen"]):
                parts.append("Vergessen Sie Ihren Schirm nicht.")
            elif any(x in w for x in ["schnee", "eis", "frost", "glätte"]):
                parts.append("Die Straßen könnten glatt sein — bitte vorsichtig.")
            elif any(x in w for x in ["sturm", "gewitter", "böen", "orkan"]):
                parts.append("Starker Wind heute — passen Sie auf sich auf.")
            elif any(x in w for x in ["sonnig", "klar", "heiter", "wolkenlos"]):
                parts.append("Ein schöner Tag draußen.")

        # Mail
        if mails:
            n = len(mails)
            if n == 1:
                parts.append("Eine neue Mail wartet auf Sie.")
            elif n <= 4:
                parts.append(f"{n} ungelesene Mails.")
            else:
                parts.append(f"{n} ungelesene Mails in Ihrem Postfach.")

        # Tasks and reminders (split for nuance)
        if tasks and reminders:
            t, r = len(tasks), len(reminders)
            parts.append(
                f"{t} {'Aufgabe' if t == 1 else 'Aufgaben'} und "
                f"{r} {'Erinnerung' if r == 1 else 'Erinnerungen'} stehen noch aus."
            )
        elif tasks:
            t = len(tasks)
            parts.append(f"{t} {'Aufgabe' if t == 1 else 'Aufgaben'} auf der Liste.")
        elif reminders:
            r = len(reminders)
            parts.append(f"{r} {'Erinnerung' if r == 1 else 'Erinnerungen'} für heute.")

        # Notes
        if notes:
            n = len(notes)
            parts.append(f"{n} offene {'Notiz' if n == 1 else 'Notizen'} in Obsidian.")

        # Closing
        if not mails and not tasks and not reminders and not notes:
            parts.append(random.choice([
                "Alles erledigt — ein ruhiger Start.",
                "Keine offenen Punkte. Der Tag gehört Ihnen.",
                "Postfach und Aufgaben: leer. Ein entspannter Beginn.",
            ]))
        else:
            parts.append(random.choice([
                "Ich stehe bereit.",
                "Wie kann ich Ihnen behilflich sein?",
                "Was darf ich für Sie tun?",
                "Womit soll ich beginnen?",
            ]))

        return " ".join(parts)

    def generate_pause_brief(self, current_mails: list, user_address: str) -> str:
        known_ids = self.get_known_mail_ids()
        current_ids = [f"{m.get('sender','')}_{m.get('subject','')}" for m in current_mails]
        diff = self.compare_mail_ids(known_ids, current_ids)

        self._data["status_checks"].append({
            "timestamp": datetime.now().isoformat(),
            "trigger": "pause_return",
            "new_count": diff["new_count"],
            "deleted_count": diff["deleted_count"],
            "current_count": diff["current_count"],
        })
        # Baseline aktualisieren — nächster Vergleich gegen aktuellen Stand, nicht Morgen
        if self._data.get("last_morning_brief"):
            self._data["last_morning_brief"]["mail_ids_mentioned"] = current_ids
            self._data["last_morning_brief"]["mail_count_mentioned"] = len(current_ids)
        self.update_activity()

        if diff["new_count"] > 0:
            n = diff["new_count"]
            new_ids_set = set(diff["new_ids"])
            new_mails = [m for m in current_mails
                         if f"{m.get('sender','')}_{m.get('subject','')}" in new_ids_set]
            senders = [m.get("sender", "").split("<")[0].strip() or m.get("sender", "Unbekannt")
                       for m in new_mails]
            if n == 1:
                return random.choice([
                    f"Willkommen zurück, {user_address}. Eine neue Mail von {senders[0]}.",
                    f"Eine neue Mail von {senders[0]} ist eingegangen, {user_address}.",
                ])
            elif n == 2:
                return f"Willkommen zurück, {user_address}. {n} neue Mails — von {senders[0]} und {senders[1]}."
            else:
                return f"Willkommen zurück, {user_address}. {n} neue Mails — unter anderem von {senders[0]}."
        return random.choice([
            f"Willkommen zurück, {user_address}.",
            f"Alles ruhig, {user_address}. Keine neuen Mails.",
        ])

    def generate_absence_brief(self, current_mails: list, user_address: str) -> str:
        known_ids = self.get_known_mail_ids()
        current_ids = [f"{m.get('sender','')}_{m.get('subject','')}" for m in current_mails]
        diff = self.compare_mail_ids(known_ids, current_ids)

        self._data["status_checks"].append({
            "timestamp": datetime.now().isoformat(),
            "trigger": "long_absence_return",
            "new_count": diff["new_count"],
            "deleted_count": diff["deleted_count"],
            "current_count": diff["current_count"],
        })
        if self._data.get("last_morning_brief"):
            self._data["last_morning_brief"]["mail_ids_mentioned"] = current_ids
            self._data["last_morning_brief"]["mail_count_mentioned"] = len(current_ids)
        self.update_activity()

        if diff["new_count"] > 0:
            n = diff["new_count"]
            new_ids_set = set(diff["new_ids"])
            new_mails = [m for m in current_mails
                         if f"{m.get('sender','')}_{m.get('subject','')}" in new_ids_set]
            senders = [m.get("sender", "").split("<")[0].strip() or m.get("sender", "Unbekannt")
                       for m in new_mails]
            if n == 1:
                return random.choice([
                    f"Schön, Sie wieder zu haben, {user_address}. Eine neue Mail von {senders[0]}.",
                    f"Willkommen zurück. Während Ihrer Abwesenheit schrieb {senders[0]}.",
                ])
            elif n == 2:
                return f"Schön, Sie wieder zu haben, {user_address}. {n} neue Mails — von {senders[0]} und {senders[1]}."
            else:
                return f"Willkommen zurück, {user_address}. {n} neue Mails in Ihrer Abwesenheit — unter anderem von {senders[0]}."
        return random.choice([
            f"Schön, Sie wieder zu haben, {user_address}. Das Postfach war ruhig.",
            f"Willkommen zurück, {user_address}. Keine neuen Mails.",
        ])

    def generate_evening_brief(self, mails: list, weather: str, user_address: str) -> str:
        self._data["evening_briefing"]["done"] = True
        self.update_activity()

        parts = [f"Feierabend, {user_address}."]
        if mails:
            n = len(mails)
            parts.append(f"Im Postfach: {n} ungelesene {'Mail' if n == 1 else 'Mails'}.")
        else:
            parts.append("Postfach ist leer.")
        if weather:
            parts.append(weather)

        return " ".join(parts)

    # ── State Accessors ───────────────────────────────────────────────────────

    def mark_evening_done(self) -> None:
        self._data["evening_briefing"]["done"] = True
        self.save()

    def get_state(self) -> dict:
        return self._data
