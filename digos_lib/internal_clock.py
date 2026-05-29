"""
internal_clock.py — RelojInterno ⏰
══════════════════════════════════════════

Internal clock with persistent timeline for temporal reference.
Used by SelfAwarenessCore to know "what time is it" and by AIAgent
to inject temporal context into the system prompt.

DIFFERENCE FROM TICKETS:
  - Tickets = trabajo del System Engineer (S&D pipeline)
  - Timeline = referencia temporal para conversaciones (sin tickets)

The timeline answers questions like:
  - "Ayer te dije..." → ¿qué pasó ayer?
  - "Hace una hora hablamos de..." → ¿qué conversación fue?
  - "La semana pasada..." → ¿qué pasó hace 7 días?

⏳ HILO TEMPORAL:
  👤 hace 3 horas: pediste implementar tools de voz
    • STT necesita Whisper API key
    • gap detection funciona sin API key
  🤖 hace 2 horas: te expliqué el diseño del Internal Clock
    • timeline.json en ~/.digos/
    • sin tickets, solo referencia temporal
  👤 ayer a las 5:15 PM: tests de clasificación
    • 45 tests, todos verdes
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict

from digos_lib.constants import TIMELINE_FILE, DIGOS_DIR


class InternalClock:
    """RelojInterno — temporal awareness for the agent.

    Provides:
    - now() → current date/time in multiple formats
    - relative_time() → "ayer a las 3pm", "hace 2 horas"
    - record() → save message to timeline (NOT a ticket)
    - get_context() → block to inject into system prompt
    - start_session() / end_session() → session tracking

    Does NOT use tickets — purely temporal reference.
    """

    def __init__(self, log_keeper=None):
        self._log = log_keeper
        self._timeline: List[dict] = []
        self._current_session_id: Optional[str] = None
        self._load()

    # ─── PUBLIC API ───────────────────────────────────────────

    def now(self) -> dict:
        """Returns current time in multiple formats."""
        now = datetime.now()
        local_now = now
        return {
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "time_short": now.strftime("%I:%M %p").lstrip("0").lower(),
            "day_of_week": now.strftime("%A"),
            "day_of_week_es": self._day_spanish(now),
            "unix": time.time(),
            "iso_utc": now.astimezone(timezone.utc).isoformat(),
        }

    def relative_time(self, past_iso: str) -> str:
        """Returns human-readable relative time in Spanish.

        Examples:
          "hace 3 minutos"
          "hace 2 horas"
          "ayer a las 3:15 pm"
          "hace 3 días"
          "la semana pasada"
          "el 15 de mayo"
        """
        try:
            past = datetime.fromisoformat(past_iso)
        except (ValueError, TypeError):
            return "fecha desconocida"

        now = datetime.now()

        # Remove timezone info for comparison
        if past.tzinfo is not None:
            past = past.replace(tzinfo=None)
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        diff = now - past

        seconds = diff.total_seconds()
        if seconds < 0:
            return "en el futuro"

        if seconds < 60:
            return "hace unos segundos"

        minutes = int(seconds / 60)
        if minutes == 1:
            return "hace 1 minuto"
        if minutes < 60:
            return f"hace {minutes} minutos"

        hours = int(minutes / 60)
        if hours == 1:
            return "hace 1 hora"
        if hours < 24:
            return f"hace {hours} horas"

        days = int(hours / 24)
        if days == 1:
            return f"ayer a las {past.strftime('%-I:%M %p').lower()}"
        if days <= 7:
            return f"hace {days} días"
        if days <= 14:
            return "la semana pasada"

        weeks = int(days / 7)
        if weeks <= 4:
            return f"hace {weeks} semanas"

        months = int(days / 30)
        if months == 1:
            return "hace 1 mes"
        if months < 12:
            return f"hace {months} meses"

        years = int(months / 12)
        if years == 1:
            return "hace 1 año"
        return f"hace {years} años"

    def start_session(self, session_id: Optional[str] = None) -> str:
        """Starts a new conversation session. Returns session_id."""
        if session_id is None:
            import uuid
            session_id = uuid.uuid4().hex[:8]
        self._current_session_id = session_id
        entry = {
            "type": "session_start",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        self._timeline.append(entry)
        self._save()
        self._log_info("clock", f"Sesión '{session_id}' iniciada")
        return session_id

    def end_session(self) -> Optional[str]:
        """Ends the current session. Returns session_id or None."""
        if self._current_session_id is None:
            return None
        sid = self._current_session_id
        self._timeline.append({
            "type": "session_end",
            "session_id": sid,
            "timestamp": datetime.now().isoformat(),
        })
        self._save()
        self._log_info("clock", f"Sesión '{sid}' finalizada")
        self._current_session_id = None
        return sid

    def record(self, role: str, summary: str, bullet_points: Optional[list] = None) -> None:
        """Records a message in the timeline. NOT a ticket — temporal reference only.

        Args:
            role: 'user' or 'agent' (or 'system')
            summary: brief description (~120 chars max)
            bullet_points: optional structured notes
        """
        now = datetime.now()
        entry = {
            "type": "message",
            "session_id": self._current_session_id or "unknown",
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "role": role,
            "summary": (summary or "")[:200],
            "bullet_points": bullet_points or [],
        }
        self._timeline.append(entry)
        self._save()

    def get_context(self, max_entries: int = 7) -> str:
        """Returns temporal context block to inject into system prompt.

        Includes:
          - Current date/time
          - Recent timeline entries with relative time
          - Bullet points from each entry
        """
        now = self.now()
        lines = [
            f"📅 [RELOJ INTERNO] — {now['date']} ({now['day_of_week_es']})",
            f"⏰ Son las {now['time']}",
            "",
        ]

        # Get recent entries
        recent = self._get_recent_entries(max_entries)
        if not recent:
            lines.append("⏳ HILO TEMPORAL: (sin actividad reciente)")
        else:
            lines.append("⏳ HILO TEMPORAL (últimos mensajes):")
            for entry in recent:
                rel = self.relative_time(entry["timestamp"])
                role_icon = "👤" if entry.get("role") == "user" else "🤖" if entry.get("role") == "agent" else "⚙️"
                summary = entry.get("summary", "")
                lines.append(f"  {role_icon} {rel}: {summary}")
                for bp in entry.get("bullet_points", []):
                    lines.append(f"    • {bp}")

        lines.append("")
        lines.append("USO: Usa esta información temporal para responder con conciencia de cuándo")
        lines.append("ocurrieron los eventos. Si el usuario dice 'ayer te dije', puedes referenciar")
        lines.append("la entrada de ayer. Si dice 'hace una hora', busca en el timeline.")
        lines.append("")

        return "\n".join(lines)

    def get_timeline(self, days: int = 7) -> List[dict]:
        """Returns timeline entries from the last N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [
            e for e in self._timeline
            if e.get("timestamp", "") >= cutoff and e.get("type") == "message"
        ]

    def get_session_timeline(self, session_id: str) -> List[dict]:
        """Returns all entries for a specific session."""
        return [e for e in self._timeline if e.get("session_id") == session_id]

    def status(self) -> dict:
        """Returns brief clock status for system status display."""
        now = self.now()
        recent = self._get_recent_entries(5)
        session_active = self._current_session_id is not None
        total_entries = len([e for e in self._timeline if e.get("type") == "message"])
        total_sessions = len(set(
            e.get("session_id", "") for e in self._timeline
            if e.get("session_id") and e.get("type") in ("session_start",)
        ))
        return {
            "ok": True,
            "date": now["date"],
            "time": now["time"],
            "day": now["day_of_week_es"],
            "session_active": session_active,
            "session_id": self._current_session_id or "",
            "total_entries": total_entries,
            "total_sessions": total_sessions,
            "recent_summary": [
                f"{self.relative_time(e['timestamp'])}: {e.get('summary', '')[:60]}"
                for e in recent
            ],
        }

    def print_status(self):
        """Prints clock status in CLI-friendly format."""
        s = self.status()
        print()
        print("  🕰️ RELOJ INTERNO")
        print("  ─────────────────")
        print(f"  Fecha: {s['date']} ({s['day']})")
        print(f"  Hora:  {s['time']}")
        print(f"  Sesión: {'✅ Activa' if s['session_active'] else '⏸️ Inactiva'}")
        print(f"  Entradas: {s['total_entries']} en {s['total_sessions']} sesiones")
        if s['recent_summary']:
            print(f"  Últimos:")
            for r in s['recent_summary']:
                print(f"    • {r}")
        print()

    # ─── PERSISTENCE ──────────────────────────────────────────

    def _load(self):
        """Loads timeline from disk."""
        if TIMELINE_FILE.exists():
            try:
                data = json.loads(TIMELINE_FILE.read_text(encoding='utf-8'))
                self._timeline = data.get("timeline", [])
                # Resume last session if active
                last_entry = self._timeline[-1] if self._timeline else {}
                if last_entry.get("type") == "session_start":
                    self._current_session_id = last_entry.get("session_id")
                elif last_entry.get("type") == "message" and last_entry.get("session_id"):
                    self._current_session_id = last_entry.get("session_id")
                self._log_info("clock", f"Timeline cargada: {len(self._timeline)} entradas")
            except (json.JSONDecodeError, ValueError):
                self._timeline = []
                self._current_session_id = None

    def _save(self):
        """Saves timeline to disk. Keeps max 500 entries (auto-prune)."""
        # Prune old sessions — keep last 500 entries
        if len(self._timeline) > 500:
            self._timeline = self._timeline[-500:]

        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "timeline": self._timeline,
        }
        try:
            DIGOS_DIR.mkdir(parents=True, exist_ok=True)
            TIMELINE_FILE.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding='utf-8',
            )
        except Exception as e:
            self._log_info("clock", f"Error guardando timeline: {e}")

    # ─── HELPERS ──────────────────────────────────────────────

    def _get_recent_entries(self, count: int = 5) -> List[dict]:
        """Returns the most recent message entries (not session markers)."""
        messages = [e for e in self._timeline if e.get("type") == "message"]
        return messages[-count:]

    def _day_spanish(self, dt: datetime) -> str:
        """Returns day of week in Spanish."""
        days = {
            0: "lunes", 1: "martes", 2: "miércoles",
            3: "jueves", 4: "viernes", 5: "sábado", 6: "domingo",
        }
        return days.get(dt.weekday(), "?")

    def _log_info(self, source: str, msg: str):
        """Logs if log_keeper is available."""
        if self._log:
            try:
                self._log.info(source, msg)
            except Exception:
                pass

    def _log_warn(self, source: str, msg: str):
        """Warns if log_keeper is available."""
        if self._log:
            try:
                self._log.warn(source, msg)
            except Exception:
                pass
