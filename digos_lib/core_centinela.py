"""Centinela — 24/7 watchdog, no LLM, pure code."""
import threading
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Dict, List

from digos_lib.constants import PROFILE_DIR, CENTINELA_POLL_INTERVAL
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.provider_api import _provider_api_request, test_telegram_token
from digos_lib.time_core import Clock


class Centinela:
    """24/7 watchdog thread. Monitors health, fires alarms, no LLM."""

    def __init__(self, log_fn: Optional[Callable] = None,
                 factory_manager=None, tower=None):
        self.log = log_fn or (lambda *a, **k: None)
        self.factory_manager = factory_manager
        self.tower = tower
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.strikes_file = PROFILE_DIR / "strikes.json"
        self._strike_state: Dict[str, int] = self._load_strikes()
        self._signal_count = 0

    def _load_strikes(self) -> Dict[str, int]:
        if self.strikes_file.exists():
            try:
                with open(self.strikes_file) as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_strikes(self) -> None:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.strikes_file, "w") as f:
            json.dump(self._strike_state, f, indent=2)

    def _key(self, category: str, target: str) -> str:
        return f"{category}:{target}"

    def _strike(self, key: str, reason: str) -> int:
        self._strike_state[key] = self._strike_state.get(key, 0) + 1
        self._save_strikes()
        count = self._strike_state[key]
        self.log("warn", "centinela", f"Strike {count}/3: {key} — {reason}")
        return count

    def _clear(self, key: str) -> None:
        if key in self._strike_state:
            del self._strike_state[key]
            self._save_strikes()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="centinela")
        self._thread.start()
        self.log("info", "centinela", "🔍 Centinela 24/7 watchdog started (no LLM)")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while self._running:
            try:
                self._cycle()
            except Exception as e:
                self.log("error", "centinela", f"Cycle error: {e}")
            for _ in range(CENTINELA_POLL_INTERVAL):
                if not self._running:
                    return
                time.sleep(1)

    def _cycle(self) -> None:
        """One watchdog cycle."""
        # 1. Check API key
        self.check_api_key_from_vault()
        # 2. Check Telegram token
        self.check_telegram_from_vault()
        # 3. Check factory stall
        if self.factory_manager:
            try:
                self.factory_manager.health_check()
            except Exception:
                pass

    def check_api_key(self, provider_id: str, api_key: str) -> bool:
        """Tests an API key. Returns True if OK, False if defective."""
        ok, msg, _ = _provider_api_request(provider_id, api_key)
        k = self._key("api_key", provider_id)
        if ok:
            self._clear(k)
            return True
        self._strike(k, msg)
        return False

    def check_telegram_token(self, token: str) -> bool:
        """Tests a Telegram token."""
        k = self._key("telegram", "bot")
        ok, msg = test_telegram_token(token)
        if ok:
            self._clear(k)
            return True
        self._strike(k, msg)
        return False

    def check_api_key_from_vault(self) -> bool:
        vault = CajaSeguraInfo.read_slot("principal") or {}
        api_key = vault.get("api_key", "")
        provider_id = vault.get("provider_id", "")
        if not api_key or not provider_id:
            return True
        ok, msg, _ = _provider_api_request(provider_id, api_key)
        k = self._key("api_key", provider_id)
        if ok:
            self._clear(k)
            self.log("info", "centinela", f"API key check: OK ({msg})")
            return True
        self._strike(k, msg)
        self.log("info", "centinela", f"API key check: FALLO ({msg})")
        return False

    def check_telegram_from_vault(self) -> bool:
        vault = CajaSeguraInfo.read_slot("principal") or {}
        token = vault.get("gateway_token", "")
        if not token:
            return True
        k = self._key("telegram", "bot")
        ok, msg = test_telegram_token(token)
        if ok:
            self._clear(k)
            self.log("info", "centinela", f"Telegram token: {msg}")
            return True
        self._strike(k, msg)
        return False
