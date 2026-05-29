"""DIGOS Centinela — Defect detection for API keys, tokens, and alarms."""
import json
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import socket
from typing import List

from digos_lib.constants import STRIKES_FILE, STRIKE_LIMIT, DIGOS_DIR
from digos_lib.provider_api import _provider_api_request
from digos_lib.core_log import LogKeeper

class Centinela:
    """Detects defects in API keys, tokens, and internal alarms.
    Does NOT restart gateways. Does NOT diagnose.
    3 consecutive failures → reports to System Engineer.

    Also manages system alarms and reminders.
    Max 10 per second, spaced 5-8s, fire 5-8s early."""

    MAX_ALARMS_PER_TICK = 10
    ALARM_ADVANCE_SECONDS = 6  # 5-8s antes, valor medio
    STAGGER_SECONDS = 6        # 5-8s entre alarmas, valor medio

    def __init__(self, log_keeper: LogKeeper, engineer=None):
        self.log = log_keeper
        self._strikes = self._load_strikes()
        self._reported = set()
        self._alarms: List[dict] = self._load_alarms()
        self._reminders: List[dict] = self._load_reminders()
        self._engineer = engineer  # SystemEngineer para crear tickets

    # ── Alarmas ────────────────────────────

    def schedule_alarm(self, timestamp: float, title: str,
                       description: str = "", task: str = "") -> str:
        """Schedules an alarm. Centinela will execute the task at that time."""
        alarm = {
            "id": f"alarm-{int(time.time())}-{len(self._alarms)}",
            "type": "alarm",
            "scheduled_at": timestamp,
            "fire_at": timestamp - self.ALARM_ADVANCE_SECONDS,
            "title": title,
            "description": description,
            "task": task,
            "status": "pending",
            "ticket_id": "",
            "created_at": time.time(),
        }
        self._alarms.append(alarm)
        self._save_alarms()

        # Crear ticket en el Engineer
        if self._engineer:
            tid = self._engineer.create_ticket(
                "system",
                f"alarm:{title[:30]}",
                f"Alarma programada: {title}",
                "low", source="centinela"
            )
            alarm["ticket_id"] = tid
            self._save_alarms()

        return alarm["id"]

    def schedule_reminder(self, timestamp: float, title: str,
                          description: str = "") -> str:
        """Schedules a reminder. Centinela will notify at that time."""
        reminder = {
            "id": f"reminder-{int(time.time())}-{len(self._reminders)}",
            "type": "reminder",
            "scheduled_at": timestamp,
            "fire_at": timestamp - self.ALARM_ADVANCE_SECONDS,
            "title": title,
            "description": description,
            "status": "pending",
            "ticket_id": "",
            "created_at": time.time(),
        }
        self._reminders.append(reminder)
        self._save_reminders()

        if self._engineer:
            tid = self._engineer.create_ticket(
                "system",
                f"reminder:{title[:30]}",
                f"Recordatorio: {title}",
                "low", source="centinela"
            )
            reminder["ticket_id"] = tid

        return reminder["id"]

    def _check_alarms(self) -> List[str]:
        """Checks pending alarms/reminders and fires the ones that are due.
        Returns list of fired alarm IDs.

        Reglas:
        - Max 10 por tick
        - Separadas 5-8s si caen al mismo tiempo
        - Se disparan 5-8s ANTES de la hora
        """
        now = time.time()
        fired = []

        # Recolectar alarmas pendientes que deben dispararse
        pending = [a for a in self._alarms if a["status"] == "pending"
                   and a["fire_at"] <= now]

        if not pending:
            return fired

        # Limitar a MAX_ALARMS_PER_TICK
        if len(pending) > self.MAX_ALARMS_PER_TICK:
            pending = pending[:self.MAX_ALARMS_PER_TICK]
            self.log.warn("centinela",
                f"Mas de {self.MAX_ALARMS_PER_TICK} alarmas simultaneas — "
                f"{(len(self._alarms) - self.MAX_ALARMS_PER_TICK)} pospuestas")

        # Stagger: separate alarms that fall on the same second
        # Agrupar por segundo
        by_second = {}
        for a in pending:
            sec = int(a["fire_at"])
            by_second.setdefault(sec, []).append(a)

        staggered = []
        for sec, alarms in by_second.items():
            for i, a in enumerate(alarms):
                a["fire_at"] = sec + (i * self.STAGGER_SECONDS)
                staggered.append(a)

        # Disparar alarmas
        for alarm in staggered:
            if alarm["fire_at"] > now:
                continue  # aun no toca (stagger lo movio)

            alarm["status"] = "fired"
            alarm["fired_at"] = now
            fired.append(alarm["id"])

            log_msg = (f"ALARMA: {alarm['title']}" if alarm["type"] == "alarm"
                      else f"RECORDATORIO: {alarm['title']}")
            self.log.info("centinela", log_msg, {"ticket": alarm["ticket_id"]})

        self._save_alarms()
        self._save_reminders()
        return fired

    # ── Persistencia ───────────────────────

    ALARMS_FILE = DIGOS_DIR / "alarms.json"
    REMINDERS_FILE = DIGOS_DIR / "reminders.json"

    def _load_alarms(self) -> List[dict]:
        if self.ALARMS_FILE.exists():
            try:
                return json.loads(self.ALARMS_FILE.read_text(encoding='utf-8'))
            except Exception as e:
                self.log.warn("centinela", f"Error cargando alarmas: {e}")
        return []

    def _save_alarms(self):
        self.ALARMS_FILE.write_text(json.dumps(self._alarms, indent=2))

    def _load_reminders(self) -> List[dict]:
        if self.REMINDERS_FILE.exists():
            try:
                return json.loads(self.REMINDERS_FILE.read_text(encoding='utf-8'))
            except Exception as e:
                self.log.warn("centinela", f"Error cargando recordatorios: {e}")
        return []

    def _save_reminders(self):
        self.REMINDERS_FILE.write_text(json.dumps(self._reminders, indent=2))

    # ── Strikes (original) ──

    def _load_strikes(self) -> dict:
        if STRIKES_FILE.exists():
            try:
                return json.loads(STRIKES_FILE.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                pass
        return {}

    def _save_strikes(self):
        STRIKES_FILE.write_text(json.dumps(self._strikes, indent=2))

    def _key(self, check_type: str, identifier: str) -> str:
        return f"{check_type}:{identifier}"

    def check_api_key(self, provider_id: str, api_key: str) -> bool:
        """Tests an API key. Returns True if OK, False if defective."""
        ok, msg, status = _provider_api_request(provider_id, api_key)
        k = self._key("api_key", provider_id)
        if ok:
            self._clear(k)
            return True
        self._strike(k, msg)
        return False

    def check_telegram_token(self, token: str) -> bool:
        """Tests a Telegram token. Returns True if OK."""
        k = self._key("telegram", "bot")
        try:
            req = Request(f"https://api.telegram.org/bot{token}/getMe")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok"):
                    self._clear(k)
                    return True
                self._strike(k, "token inválido")
                return False
        except (HTTPError, URLError, socket.timeout, json.JSONDecodeError) as e:
            self._strike(k, f"error: {e}")
            return False

    def _strike(self, k: str, reason: str):
        if k not in self._strikes:
            self._strikes[k] = {"count": 0, "reason": "", "last": ""}
        self._strikes[k]["count"] += 1
        self._strikes[k]["reason"] = reason
        self._strikes[k]["last"] = datetime.now(timezone.utc).isoformat()
        self._save_strikes()
        self.log.warn("centinela", f"Strike {self._strikes[k]['count']}/{STRIKE_LIMIT}: {k} — {reason}")

    def _clear(self, k: str):
        if k in self._strikes:
            del self._strikes[k]
            self._save_strikes()

    def get_reports(self) -> List[dict]:
        """Returns defects that reached strike limit and have not been reported."""
        reports = []
        for k, data in self._strikes.items():
            if data["count"] >= STRIKE_LIMIT and k not in self._reported:
                target_parts = k.split(":", 1)
                reports.append({
                    "target": k,
                    "profile": target_parts[1] if len(target_parts) > 1 else "system",
                    "strikes": data["count"],
                    "reason": data["reason"],
                    "last": data["last"]
                })
                self._reported.add(k)
        return reports

    def get_all_strikes(self) -> dict:
        return dict(self._strikes)

    def reset_strikes(self, target: str):
        if target in self._strikes:
            del self._strikes[target]
            self._save_strikes()

