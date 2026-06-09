"""Time core — Clock, Calendar, AlarmSystem (no LLM)."""
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Callable


class Clock:
    """Current time accessor."""

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def timestamp() -> float:
        return time.time()

    @staticmethod
    def iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def formatted() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class Calendar:
    """Date arithmetic."""

    @staticmethod
    def add_hours(dt: datetime, hours: float) -> datetime:
        return dt + timedelta(hours=hours)

    @staticmethod
    def diff_seconds(a: datetime, b: datetime) -> float:
        return (a - b).total_seconds()

    @staticmethod
    def auto_stamp() -> str:
        """Format: 20260609T013658-0000 (year, month, day, hour, minute, second, index)."""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y%m%dT%H%M%S-") + f"{now.microsecond // 1000:04d}"


class AlarmSystem:
    """Schedule one-shot or recurring alarms."""

    def __init__(self):
        self._alarms: Dict[str, Dict] = {}

    def add(self, name: str, fire_at: datetime, callback: Callable,
            recurring_seconds: Optional[int] = None, metadata: Optional[dict] = None) -> str:
        self._alarms[name] = {
            "fire_at": fire_at,
            "callback": callback,
            "recurring_seconds": recurring_seconds,
            "metadata": metadata or {},
            "fired": False,
        }
        return name

    def remove(self, name: str) -> bool:
        return self._alarms.pop(name, None) is not None

    def tick(self) -> List[str]:
        """Check all alarms, fire the ones due, return names of fired alarms."""
        now = Clock.now()
        fired: List[str] = []
        for name, alarm in list(self._alarms.items()):
            if alarm["fired"]:
                continue
            if now >= alarm["fire_at"]:
                try:
                    alarm["callback"](name, alarm["metadata"])
                except Exception:
                    pass
                if alarm["recurring_seconds"]:
                    alarm["fire_at"] = now + timedelta(seconds=alarm["recurring_seconds"])
                else:
                    alarm["fired"] = True
                fired.append(name)
        return fired


class TimeCore:
    """Unified time system used by the Tower."""

    def __init__(self):
        self.clock = Clock()
        self.calendar = Calendar()
        self.alarms = AlarmSystem()

    def setup_defaults(self, tower_callback: Callable, pa_callback: Callable) -> None:
        from digos_lib.constants import TOWER_MAINTENANCE_INTERVAL, PA_REFLECTION_HOUR, FACTORY_HEALTH_HOURS
        now = self.clock.now()
        self.alarms.add("tower_maintenance", now + timedelta(seconds=TOWER_MAINTENANCE_INTERVAL),
                        tower_callback, recurring_seconds=TOWER_MAINTENANCE_INTERVAL)
        next_2am = now.replace(hour=PA_REFLECTION_HOUR, minute=0, second=0, microsecond=0)
        if next_2am <= now:
            next_2am += timedelta(days=1)
        self.alarms.add("pa_reflection", next_2am, pa_callback, recurring_seconds=86400)
        self.alarms.add("factory_health", now + timedelta(hours=FACTORY_HEALTH_HOURS),
                        pa_callback, recurring_seconds=FACTORY_HEALTH_HOURS * 3600)

    def tick(self) -> Dict:
        fired = self.alarms.tick()
        return {"fired_alarms": fired, "now": self.clock.iso()}
