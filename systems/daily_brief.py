import json
import os
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
                data = self._fresh_state()
                self._save(data)
            return data
        except (FileNotFoundError, json.JSONDecodeError):
            data = self._fresh_state()
            self._save(data)
            return data

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def save(self) -> None:
        self._save(self._data)

    def _fresh_state(self) -> dict:
        state = json.loads(json.dumps(_EMPTY_STATE))
        state["date"] = str(date.today())
        return state

    # ── Archive & Reset ───────────────────────────────────────────────────────

    def archive(self) -> None:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        dest = os.path.join(ARCHIVE_DIR, f"{self._data.get('date', 'unknown')}.json")
        shutil.copy2(DATA_PATH, dest)

    def reset(self) -> None:
        self.archive()
        self._data = self._fresh_state()
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

        parts = [f"Guten Morgen, {user_address}."]
        if weather:
            parts.append(weather.rstrip(".") + ".")
        if mails:
            parts.append(f"Sie haben {len(mails)} ungelesene {'Mail' if len(mails) == 1 else 'Mails'}.")
        if tasks or reminders:
            total = len(tasks) + len(reminders)
            parts.append(f"{total} ausstehende {'Aufgabe' if total == 1 else 'Aufgaben'}.")
        if notes:
            parts.append(f"{len(notes)} offene {'Notiz' if len(notes) == 1 else 'Notizen'} in Obsidian.")
        if not mails and not tasks and not reminders and not notes:
            parts.append("Alles erledigt — ein ruhiger Start.")

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
        self.update_activity()

        if diff["new_count"] > 0:
            n = diff["new_count"]
            return f"{n} neue {'Mail' if n == 1 else 'Mails'}, {user_address}."
        if diff["deleted_count"] > 0 and diff["current_count"] > 0:
            return f"{diff['deleted_count']} {'Mail' if diff['deleted_count'] == 1 else 'Mails'} gelesen."
        if diff["current_count"] == 0 and diff["deleted_count"] > 0:
            return f"Postfach leer, {user_address}."
        return ""

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
        self.update_activity()

        if diff["new_count"] > 0:
            n = diff["new_count"]
            return f"Während Sie weg waren: {n} neue {'Mail' if n == 1 else 'Mails'}, {user_address}."
        return f"Stille im Postfach während Ihrer Abwesenheit, {user_address}."

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
