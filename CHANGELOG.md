# Changelog

All notable changes to Jarvis are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), versioning follows [SemVer](https://semver.org/).

---

## [2.4.2] — 2026-05-08

### Added
- **Kalender im Aufgaben-Panel** — `/api/get_tasks` liefert jetzt auch Termine für heute und morgen aus Home Assistant CalDAV. Kalender-Einträge erscheinen ohne Checkbox (nicht abhakbar), mit dem Zeit-Label als Quelle (blau).

### Fixed
- **Aussprache in Kalender-/Aktions-Antworten** — Summary-Prompts behalten numerische Form ("17 Uhr", "12. Mai"). ElevenLabs German TTS liest diese korrekt aus (z.B. "siebzehn Uhr") ohne dass der Chat-Text Lautschrift zeigt.

---

## [2.4.1] — 2026-05-08

### Fixed
- `UnboundLocalError: 'OBSIDIAN_INBOX'` in `save_config_api` — `OBSIDIAN_INBOX` und `OBSIDIAN_ARCHIVE` wurden in der Funktion zugewiesen ohne `global`-Deklaration. Python behandelte sie dadurch als lokale Variablen, was beim Speichern der Config (insbesondere nach Sprach-Wechsel) zu einem 500-Fehler führte.
- `NEWS_BRIEF` meldete "Keine neuen Artikel" obwohl ungelesene Artikel im Archiv lagen — Action berichtet jetzt alle `read: False` Einträge aus dem Archiv, nicht nur frisch geholte. `NewsSystem.get_unread_articles()` hinzugefügt.

---

## [2.4.0] — 2026-05-08

### Added
- **Language System** — `language: "de"/"en"` config key switches system prompt language, Web Speech API locale (`de-DE`/`en-US`), and TTS phrasing. Live-reload without restart. `/api/language` endpoint.
- **TTS Locale Files** — `locales/de.json` + `locales/en.json` extract all hardcoded TTS strings (greetings, Daily Brief templates, reconnect phrases, news snippets, light responses). `DailyBrief` reads locale via `set_locale()`.
- **UI i18n** — `frontend/i18n/de.json` + `en.json` (28 keys each). `data-i18n` / `data-i18n-placeholder` attributes on all panel titles, status text, placeholders, popup buttons, and dynamic JS strings. Language loaded from `/api/language` on DOMContentLoaded.
- **In-App Update Badge** — Dashboard checks GitHub Releases API (`/repos/.../releases/latest`) on startup. Badge appears if a newer version exists (blue for patch/minor, gold for major). 24h server-side cache. Dismissable per session via sessionStorage.

### Fixed
- `UnboundLocalError: 'os'` in `NOTIZ_ERLEDIGT` action — two misplaced `import os` statements inside `execute_action()` made Python treat `os` as a local variable for the entire function scope. Removed; module-level import is sufficient.

---

## [2.3.1] — 2026-05-08

### Added
- Gender-neutral address system — `user_address` config field replaces all hardcoded "Sir" references. Supports Sir, Chef, Boss, Ms./Mrs./Miss/Madam + surname.
- Configurable Obsidian archive path (`obsidian_archive_path`) — completed notes move to the correct folder instead of a hardcoded fallback.
- Config UI: all panels are now collapsible accordions (▼/▶). Default open: API Keys, Profile, Home Assistant, Behavior. Default closed: Obsidian, Services & Paths, Programs.

### Fixed
- TTS date pronunciation — "7. Mai" → "siebten Mai", "2026" → "zweitausendsechsundzwanzig"
- `_speak()` now separates TTS audio text from frontend display text — date shown correctly in chat.
- `DailyBrief.load()` now updates `self._data` in place — date change at midnight works correctly.
- Morning news snippet phrasing — more natural sentences instead of robotic list format. Once-per-day guard prevents repeat on reconnect.
- `NOTIZ_ERLEDIGT` action now moves notes to archive folder instead of permanently deleting them.
- Config UI: browser cache issue with `toggleObsidian()` — fixed via cache-busting version parameter on `config.js`.

### Removed
- Danger Zone panel — functionality consolidated into the Maintenance modal with per-item confirmation checkbox.
- Duplicate "delete brain" modal — replaced by inline checkbox flow in Maintenance.

---

## [2.3.0] — 2026-05-07

### Added
- **News System** — RSS feed fetching, archiving, deduplication, category support. Feeds manageable via Config UI modal.
- **Wake Brief** — on wake-from-sleep, Jarvis checks how long it was inactive and delivers a contextual morning/absence brief via `_speak()`.
- Daily Brief overhaul — morning brief, evening brief, absence detection, threshold configuration, maintenance API endpoints.
- Maintenance modal in Config UI — clear news archive, reset daily brief, set absence threshold.
- RSS Feeds modal in Config UI — add, edit, delete, enable/disable feeds.

### Fixed
- Wake endpoint sets `_last_activate_spoken` — prevents triple greeting on reconnect.
- `OPEN` action writes history entry — prevents action loop repetition.
- Date pronunciation — ISO format converted to readable German.
- `NEWS_SEARCH` returns URL as silent history entry — enables follow-up questions.

---

## [2.2.0] — 2026-05

### Added
- Daily Brief Memory System — `data/daily_brief_memory.json` tracks morning brief, absence, last activity. Auto-archives at midnight.
- Wake smart unlock — `wake-monitor.py` waits for actual screen unlock before triggering brief.
- WebSocket reconnect polish — exponential backoff (3→60s), activate debounce prevents double greeting.

---

## [2.1.3] — 2026-05

### Changed
- Stabilization Phase 7 — CSS variable consolidation, race condition fixes, technical debt cleanup. `dashboard.html` removed, `/dashboard` redirects to `/`.

---

## [2.1.2] — 2026-05

### Fixed
- Stabilization Phases 1–5: state management fixes, TTS retry logic, dashboard consolidation.
- Config hardening — missing keys no longer crash server, `ha_enabled: false` guard consistent.
- Completed Obsidian notes (all checkboxes checked) excluded from task list.
- Stale mail count in greeting — refreshes live on "Jarvis activate".

---

## [2.1.1] — 2026-04

### Added
- Voice library — multiple ElevenLabs voices manageable via Config UI, activate per-click.
- `OPEN_APP` action — open macOS applications by voice.
- Live data refresh in Config UI.

---

## [2.1.0] — 2026-04

### Added
- User manual — `/handbuch` route, HTML + PDF versions.
- Window layout configurator in Config UI.
- HUD mute button.

### Fixed
- AppleScript stability improvements for Reminders and Mail.
- Autostart via launchd keepalive.

---

## [2.0.0] — 2026-04

### Changed
- Production migration — port changed to **8340**, Chrome app mode, launchd autostart.
- Config UI introduced (`/config`).
- Structured JSON output layer (Pydantic ActionModel) alongside legacy string parser.

---

## [1.0.0] — 2026-03

### Added
- Initial release — FastAPI backend, ElevenLabs TTS, Web Speech API, Playwright browser control.
- Home Assistant light control, Apple Mail, macOS Reminders integration.
- Kachelmann weather API, voice-controlled browser navigation.
