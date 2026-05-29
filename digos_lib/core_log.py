"""DIGOS LogKeeper — Structured JSON logs with rotation."""
import json
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict

from digos_lib.constants import LOG_DIR

class LogKeeper:
    """Structured JSON logs with automatic rotation.
    1 file per day, max 5 files, 1MB each."""

    MAX_SIZE = 1024 * 1024
    MAX_FILES = 5

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._current = LOG_DIR / "digos.log"
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        if not self._current.exists():
            self._current.write_text("")

    def _rotate(self):
        with self._lock:
            size = self._current.stat().st_size
            if size > self.MAX_SIZE:
                for i in range(self.MAX_FILES - 1, 0, -1):
                    src = LOG_DIR / f"digos.{i}.log"
                    dst = LOG_DIR / f"digos.{i+1}.log"
                    if src.exists():
                        if dst.exists():
                            dst.unlink()
                        src.rename(dst)
                self._current.rename(LOG_DIR / "digos.1.log")
                self._current = LOG_DIR / "digos.log"
                self._ensure_file()

    def _log(self, level: str, source: str, message: str, extra: dict = None):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "source": source,
            "msg": message,
        }
        if extra:
            entry["extra"] = extra
        line = json.dumps(entry, default=str)
        try:
            from security import CREDENTIAL_PATTERN
            line = CREDENTIAL_PATTERN.sub("***REDACTED***", line)
        except Exception:
            pass
        try:
            self._rotate()
            with self._lock:
                with open(self._current, "a") as f:
                    f.write(line + "\n")
        except OSError:
            pass

    def info(self, source: str, msg: str, extra: dict = None):
        self._log("INFO", source, msg, extra)

    def warn(self, source: str, msg: str, extra: dict = None):
        self._log("WARN", source, msg, extra)

    def error(self, source: str, msg: str, extra: dict = None):
        self._log("ERROR", source, msg, extra)

    def tail(self, n: int = 20) -> List[dict]:
        if not self._current.exists():
            return []
        with open(self._current) as f:
            lines = f.readlines()
        result = []
        for l in lines[-n:]:
            try:
                result.append(json.loads(l))
            except json.JSONDecodeError:
                continue
        return result

    def get_logs(self, level: str = None, source: str = None, limit: int = 50) -> List[dict]:
        """Filters logs by level and/or source."""
        logs = self.tail(limit * 3)
        result = []
        for entry in logs:
            if level and entry.get("level") != level:
                continue
            if source and entry.get("source") != source:
                continue
            result.append(entry)
            if len(result) >= limit:
                break
        return result
