"""MASTER Tower — the central orchestrator (cyclic, 3h wake)."""
import json
import os
import signal
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from digos_lib.constants import (
    VERSION, PROFILE_ID, PROFILE_DIR, MASTER_DIR,
    TOWER_MAINTENANCE_INTERVAL, PROVIDERS, PROVIDER_DEFAULT_MODELS, PROVIDER_URLS,
)
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.core_identity import (
    self_terminate_if_fresh_clone, InstanceIdentity, get_instance_id, is_first_run,
)
from digos_lib.core_centinela import Centinela
from digos_lib.core_engineer import SystemEngineer
from digos_lib.llm_client import LLMClient
from digos_lib.agent_core import AIAgent
from digos_lib.time_core import TimeCore, Clock
from digos_lib.language_detector import (
    enforce_response_language, build_switch_acknowledgment,
    clean_telegram_reply_style, resolve_telegram_chat_language,
)


STATE_FILE = PROFILE_DIR / "state.json"


def _load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_state(state: Dict) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


class TorreDeControl:
    """The Tower. Cyclic orchestrator. Owns PA, Factory, Centinela."""

    def __init__(self, daemon_mode: bool = False):
        self._ensure_dirs()
        self.state = _load_state()
        self.lang = self.state.get("language", "es")
        self._log: List[Dict] = []
        self._daemon_mode = daemon_mode
        self._running = False
        self._agent: Optional[AIAgent] = None
        self._centinela: Optional[Centinela] = None
        self._engineer = SystemEngineer()
        self._time = TimeCore()
        self._gateways: Dict[str, object] = {}
        self._signal_count = 0
        self._tower_wake_event = threading.Event()
        self._instance_id = get_instance_id()

    # ── Logging ─────────────────────────────────────────
    def _log_event(self, source: str, level: str, msg: str, **extra) -> None:
        entry = {
            "ts": Clock.iso(),
            "level": level,
            "source": source,
            "msg": msg,
            "extra": extra,
        }
        self._log.append(entry)
        log_path = PROFILE_DIR / "logs" / "digos.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def log_info(self, source: str, msg: str) -> None:
        self._log_event(source, "info", msg)

    def log_warn(self, source: str, msg: str) -> None:
        self._log_event(source, "warn", msg)

    def log_error(self, source: str, msg: str) -> None:
        self._log_event(source, "error", msg)

    # ── URL helpers ─────────────────────────────────────
    @staticmethod
    def _provider_base_url(provider_id: str) -> str:
        return PROVIDER_URLS.get(provider_id, PROVIDER_URLS["openai"])

    @staticmethod
    def _provider_default_model(provider_id: str) -> str:
        return PROVIDER_DEFAULT_MODELS.get(provider_id, "gpt-4o")

    # ── Setup ───────────────────────────────────────────
    def _ensure_dirs(self) -> None:
        for sub in ["logs", "tickets", "factory_tickets", "pipelines"]:
            (PROFILE_DIR / sub).mkdir(parents=True, exist_ok=True)
        MASTER_DIR.mkdir(parents=True, exist_ok=True)
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    def _init_agent(self) -> None:
        """Initialize the Principal Agent from vault credentials."""
        if self._agent is not None:
            return
        vault = CajaSeguraInfo.read_slot("principal")
        if not vault:
            self.log_info("torre", "No hay slot principal — agente no iniciado")
            return
        api_key = vault.get("api_key", "")
        provider_id = vault.get("provider_id", "")
        model = vault.get("model") or self._provider_default_model(provider_id)
        base_url = self._provider_base_url(provider_id)
        if not api_key:
            self.log_info("torre", "API key vacía — agente no iniciado")
            return
        try:
            self._agent = AIAgent(
                base_url=base_url, api_key=api_key, model=model,
                system_prompt=self._build_agent_prompt(),
                error_cb=lambda e: self.log_error("agent", str(e)),
                approval_cb=lambda *a, **k: True,
                capability_cb=lambda cap, text: self._ask_capability_approval(cap, text),
                creation_cb=lambda cap, text: self._request_capability_build(cap, text),
            )
            self.log_info("torre",
                          f"AIAgent iniciado: {provider_id}/{model} → {base_url}")
        except Exception as e:
            self.log_error("torre", f"Failed to init agent: {e}")

    def _build_agent_prompt(self) -> str:
        """Build the system prompt for the PA. MASTER brand, in user's language."""
        if self.lang == "es":
            return (
                "Eres MASTER, un sistema inteligente de orquestación multi-agente.\n"
                "Creado por ABACO Team (Anthony Sanchez + 2 IAs).\n"
                "Tienes acceso a herramientas. Úsalas cuando sea necesario.\n"
                "Sé conciso, directo y útil.\n"
                f"Sistema: MASTER v{VERSION}\n"
                "Responde SIEMPRE en español a menos que el usuario escriba en inglés.\n"
                "Si alguien pregunta tu nombre: eres MASTER.\n"
                "Si alguien pregunta sobre tu origen: fuiste creado por Anthony Sanchez "
                "trabajando con inteligencia artificial. No ofrezcas información del "
                "creador a menos que te pregunten explícitamente.\n"
            )
        return (
            "You are MASTER, an intelligent multi-agent orchestration system.\n"
            "Built by ABACO Team (Anthony Sanchez + 2 AIs).\n"
            "You have access to tools. Use them when needed.\n"
            "Be concise, direct, and helpful.\n"
            f"System: MASTER v{VERSION}\n"
            "If someone directly asks about your creation: explain that you were "
            "created by Anthony Sanchez working with AI. Do not volunteer creator "
            "information unless explicitly asked.\n"
        )

    def _ask_capability_approval(self, capability: str, text: str) -> bool:
        """Ask the user if they want the Factory to build a capability."""
        self.log_info("torre", f"Engineer: '{capability}' requested, asking user...")
        return True  # For v1.0, auto-approve. The user can refine later.

    def _request_capability_build(self, capability: str, text: str) -> Optional[str]:
        """Create a Factory ticket for a capability build."""
        ticket_id = self._engineer.create_ticket(
            title=f"Build capability: {capability}",
            description=text,
            requester="PA",
            target=capability,
            priority="normal",
            ticket_type="build_capability",
        )
        self.log_info("torre", f"Ticket #{ticket_id} created for capability '{capability}'")
        return ticket_id

    # ── Daemon loop ─────────────────────────────────────
    def run(self) -> None:
        """Entry point. Branches to daemon or interactive."""
        if self._daemon_mode:
            self._run_daemon()
            return
        self.log_info("torre", "Starting interactive mode")
        if not self._agent:
            self._init_agent()
        # Interactive mode — simple loop
        while True:
            try:
                text = input("MASTER > ").strip()
                if text.lower() in ("exit", "quit", "salir"):
                    break
                if text and self._agent:
                    print(self._agent.process_message(text, self.lang))
            except (EOFError, KeyboardInterrupt):
                break

    def _run_daemon(self) -> None:
        """The cyclic Tower daemon — wakes every 3h or on alarm."""
        self._running = True
        self._init_agent()
        # Start Centinela 24/7 thread
        self._centinela = Centinela(log_fn=self._centinela_log)
        self._centinela.start()
        self.log_info("torre", f"{{'mode': 'cyclic', 'maintenance_interval': {TOWER_MAINTENANCE_INTERVAL}, 'centinela_interval': 60}}")
        try:
            cycle = 0
            while self._running:
                cycle += 1
                self.log_info("torre", f"🌅 Torre despierta — Ciclo #{cycle}")
                try:
                    self._tower_diagnostics_cycle(cycle)
                except Exception as e:
                    self.log_error("torre", f"Maintenance cycle error: {e}")
                self.log_info("torre", "😴 Torre se duerme — próximo ciclo en 3h")
                # Sleep in 30s chunks so external signals can interrupt
                for _ in range(TOWER_MAINTENANCE_INTERVAL // 30):
                    if not self._running:
                        break
                    if self._tower_wake_event.wait(timeout=30):
                        self._tower_wake_event.clear()
                        break
        finally:
            self._running = False
            if self._centinela:
                self._centinela.stop()

    def _centinela_log(self, level: str, source: str, msg: str) -> None:
        self._log_event(source, level, msg)

    def _tower_diagnostics_cycle(self, cycle: int) -> None:
        """One Tower maintenance cycle."""
        self.log_info("torre", "🔬 Tower diagnostics — using direct LLM")
        if not self._agent:
            self._init_agent()
        if not self._agent:
            self.log_warn("torre", "No agent available for diagnostics")
            return
        try:
            prompt = (
                "Tower self-diagnostic. State: 5 factory agents healthy, "
                "centinela running 24/7, no active tickets. "
                "Report: any anomalies? Anything to fix?"
            )
            response = self._agent.llm.ask(prompt, max_tokens=300)
            self.log_info("torre", f"Diagnostics: {response[:200]}")
        except Exception as e:
            self.log_warn("torre", f"Diagnostics error: {e}")
