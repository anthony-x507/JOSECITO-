"""DIGOS TorreDeControl — Orquestador principal."""
import json
import os
import select
import sys
import time
import signal
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

from digos_lib.constants import (
    VERSION, DIGOS_DIR, MASTER_DIR, STATE_FILE, KEY_FILE, LOG_DIR,
    STRIKES_FILE, SELF_FILE, VAULT_FILE,
    LANGUAGES, PROVIDERS, GATEWAYS,
    SYSTEM_IDENTITY, IDENTITY_RESPONSES,
    CENTINELA_INTERVAL, STRIKE_LIMIT,
    SYSTEM_NAME, SYSTEM_VERSION,
)
from digos_lib.provider_api import _provider_api_request
from digos_lib.core_models import AgenteRecord, DigosState, Ticket
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.core_log import LogKeeper
from digos_lib.core_centinela import Centinela
from digos_lib.core_engineer import SystemEngineer
from digos_lib.core_self import SelfAwarenessCore
from digos_lib.core_pipeline import TicketConversationPipeline
from digos_lib.core_gateways import BaseGateway, GatewayCLI, GatewayTelegram
from digos_lib.activity_panel import ActivityPanel
from digos_lib.master_risk import MasterRiskPatternLayer, MasterVerdict, RISK_GREEN, RISK_YELLOW, RISK_RED

from transparency import ToolProgressTracker
# AIAgent is lazy-imported in _init_agent() to avoid circular imports
# (agent.py imports from digos_lib, and __init__.py loads core_tower)

from adoption import AdoptionEngine, TransformationEngine
from security import CajaSegura as SecurityCaja, CajaSeguraReport as SecurityReport
from bus import MessageBus
import io
from contextlib import redirect_stdout


# ── Excepción para navegación "Volver atrás" ──
class GoBack(Exception):
    """Raised when the user chooses to go back to the previous step."""
    pass


# ─────────────────────────────────────────────
# TORRE DE CONTROL — la entidad ÚNICA
# ─────────────────────────────────────────────

class TorreDeControl:
    """Torre de Control nace primero. Guía todo el onboarding.
    Contiene Caja Segura y TORRE (auto-preservación).
    Puede vivir 24/7 como daemon.

    SYSTEM POLICY — Operations protected by level:
    🔴 RED: Permanently prohibited (damages the ecosystem)
    🟡 YELLOW: Requires Engineer authorization with ticket
    🟢 GREEN: Permitted without restriction
    """

    # 🔴 RED — Operations NO ONE can do, not even the user
    FORBIDDEN_OPERATIONS = {
        "delete_provider": "No se puede eliminar proveedores del sistema.",
        "change_provider": "No se puede cambiar proveedores activos.",
        "disconnect_gateway": "No se puede desconectar gateways de comunicación.",
        "delete_gateway_token": "No se puede eliminar tokens de gateway.",
        "delete_gps": "No se puede eliminar el GPS del sistema.",
        "delete_safety_candle": "No se puede eliminar Safety Candle.",
        "delete_self_awareness": "No se puede eliminar Self-Awareness.",
        "delete_work_destination": "No se puede eliminar Work Destination.",
        "delete_ticket_system": "No se puede eliminar el sistema de tickets.",
        "delete_core_structure": "No se puede eliminar la estructura del núcleo.",
        "delete_system_md": "No se puede eliminar archivos de configuración del sistema.",
        "delete_agent": "No se puede eliminar agentes internos del sistema.",
        "delete_engineer": "No se puede eliminar el System Engineer.",
        "delete_caja_segura": "No se puede eliminar CajaSeguraInfo del sistema.",
        "delete_internal_operation": "No se puede eliminar componentes internos de la Torre de Control.",
    }

    FORBIDDEN_PATTERNS = [
        # Operating system files (not user-owned)
        "/etc/shadow", "/etc/passwd", "/etc/sudoers",
        "/etc/ssh/", "/proc/", "/sys/",
    ]

    # 🟡 AMARILLO — Operaciones que requieren ticket del Engineer
    SENSITIVE_OPERATIONS = {
        "change_api_key": "Cambiar API key. Se creará un ticket explicando el procedimiento.",
        "change_telegram_token": "Cambiar token de Telegram. Se requiere autorización.",
        "modify_gateway": "Modificar configuración de gateway. Se requiere revisión.",
        "modify_profile": "Modificar perfil de agente. Se requiere revisión.",
    }

    def __init__(self, daemon_mode: bool = False):
        self._ensure_dirs()
        self.state = self._load_state()
        self.lang = self.state.get("language", "en")

        # TORRE: componentes de auto-preservación
        self._log = LogKeeper()
        self._self_awareness = SelfAwarenessCore(self._log)
        self._engineer = SystemEngineer(self._log)
        self._centinela = Centinela(self._log, engineer=self._engineer)

        # MASTER Risk Pattern Layer — inteligencia de riesgo + trayectoria
        # Conectado con SelfAwareness para balance contextual:
        #   RED + educativo → YELLOW (allow with caution)
        #   RED + dañino    → RED   (block)
        self._master = MasterRiskPatternLayer(
            context_evaluator=self._self_awareness.evaluate_context
        )
        self._master_verdicts_log: list = []  # últimos 100 veredictos

        # Engine: GPS + Self + Work to govern the flow
        self._engine = None

        # 🎻 Pipeline de Conversación — nuevo instrumento
        self._pipeline = TicketConversationPipeline(self._log)
        self._engineer._pipeline = self._pipeline
        from digos_lib.core_pipeline import set_pipeline_accessor as _set_pipeline_accessor
        _set_pipeline_accessor(lambda: self._pipeline)
        self._log.info("torre", "🎻 TicketConversationPipeline activo")

        # Phase 3: Gateways
        self._gateways: Dict[str, BaseGateway] = {}

        # Phase 4: Transparency — tracker de progreso
        self._tracker: Optional[ToolProgressTracker] = None

        # Activity Panel — CLI live activity display
        self._activity_panel: Optional[ActivityPanel] = None

        # Phase 4b: AIAgent — LLM + tool calling
        self._agent: Optional[AIAgent] = None

        # Phase 6: Message Bus — multi-agent communication
        self._bus: Optional[MessageBus] = None

        # Phase 8: Factory — internal agent creation
        self._factory_manager = None
        self._superior_agent = None

        self._daemon_mode = daemon_mode
        self._running = False
        self._cycle_count = 0

        # Async gateway processing — evita que media/video/LLM bloqueen el daemon
        self._executor: Optional[ThreadPoolExecutor] = None
        self._gateway_futures: List = []
        self._gateway_lock = Lock()

        if daemon_mode:
            self._self_awareness.activate()

    def _ensure_dirs(self):
        DIGOS_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (DIGOS_DIR / "profiles").mkdir(parents=True, exist_ok=True)
        (DIGOS_DIR / "imported").mkdir(parents=True, exist_ok=True)
        (DIGOS_DIR / "generated_tools").mkdir(parents=True, exist_ok=True)
        (DIGOS_DIR / "media_cache").mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                pass
        return {"setup_complete": False, "version": VERSION}

    def _save_state(self):
        STATE_FILE.write_text(json.dumps(self.state, indent=2))

    # ── RUN ──

    def run(self):
        if self._daemon_mode:
            self._run_daemon()
            return

        self._show_banner()
        if self.state.get("setup_complete"):
            print("\n✅ DIGOS ya está configurado. Iniciando agente...")
            self._handoff()
        else:
            self._onboarding()

    # ── BANNER ──

    def _show_banner(self):
        print()
        print(f"  \u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557")
        print(f"  \u2551         D I G O S   v{VERSION:<20}\u2551")
        print("  \u2551    Intelligent Agent System          \u2551")
        print("  \u2551    Multi-Agente + Seguridad           \u2551")
        print("  \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d")
        print()

    # ── ONBOARDING FLOW (con navegación atrás + límite de intentos) ──

    def _onboarding(self):
        """Onboarding con navegación entre pasos.
        - Cada menú ofrece "0 → Volver atrás" (o "0 → Salir" en idioma)
        - API Key y Token tienen 10 intentos máximos con advertencia
        - Validación de formato de API Key por proveedor
        """
        print("🔧 PRIMERA CONFIGURACIÓN")
        print("━━━━━━━━━━━━━━━━━━━━━━━")
        print()

        provider_id = None
        api_key = None
        gateway_id = None
        gateway_token = None

        step = 0
        while step < 7:
            try:
                if step == 0:
                    # Step 1: Language
                    self._step_language()
                    step = 1

                elif step == 1:
                    # Step 2: Adoption
                    self._step_adoption()
                    step = 2

                elif step == 2:
                    # Step 3: API Key + Provider
                    imported = CajaSeguraInfo.read_slot("principal") or {}
                    if imported.get("api_key") and imported.get("provider_id"):
                        provider_id = imported["provider_id"]
                        api_key = imported["api_key"]
                        provider = PROVIDERS.get(provider_id, {})
                        print(f"  🔑 Usando API Key importada: {provider.get('name', provider_id)}")
                        print()
                    else:
                        provider_id, api_key = self._step_api_key()
                    step = 3

                elif step == 3:
                    # 🎯 The agent is born here
                    self._birth_agent(provider_id)
                    step = 4

                elif step == 4:
                    # Step 4: Gateway + Token
                    imported = CajaSeguraInfo.read_slot("principal") or {}
                    if imported.get("gateway_token") and imported.get("gateway_type"):
                        gateway_id = imported["gateway_type"]
                        gateway_token = imported["gateway_token"]
                        print(f"  📡 Usando gateway importado: {imported['gateway_type']}")
                        print()
                    else:
                        gateway_id, gateway_token = self._step_gateway()
                    step = 5

                elif step == 5:
                    # Step 5: Safe Box saves the credentials
                    self._step_vault(api_key, gateway_token)
                    step = 6

                elif step == 6:
                    # Step 6: Finalizar y Handoff
                    self._finalize_setup(provider_id, gateway_id)
                    step = 7

            except GoBack:
                if step == 0:
                    print("\n  Saliendo de la configuración. Puedes ejecutar 'digos' después para continuar.\n")
                    return
                # Provider → Language directamente (saltar adoption al volver)
                if step == 2:
                    step = 0
                else:
                    step -= 1
                # Saltar pasos sin menú (birth_agent → API key, vault → gateway)
                if step == 3:
                    step = 2
                elif step == 5:
                    step = 4

        self._log.info("torre", {"provider": provider_id, "gateway": gateway_id})
        self._handoff()

    # ── Paso 2: Adoption ──

    def _step_adoption(self):
        """Onboarding step 2: detects Hermes/OpenClaw, migrates and transforms.
        Runs AFTER language selection.
        """
        engine = AdoptionEngine()
        transformer = TransformationEngine()
        sources = engine.detect_sources()

        if not sources:

            return

        print()
        print("🔄 ADOPCIÓN — SISTEMAS EXISTENTES DETECTADOS")
        print("━" * 45)
        source_labels = {"hermes": "Hermes Agent", "openclaw": "Open Cloud"}
        for s in sources:
            label = source_labels.get(s, s)
            print(f"  📡 Detectado: {label}")
        print()
        print("  DIGOS puede importar tu configuración, perfiles,")
        print("  API keys, skills y memorias desde estos sistemas.")
        print()

        if not self._confirm("¿Quieres ver qué se puede importar?"):
            print("  Saltando adopción. Puedes migrar después manualmente.")

            return

        for source in sources:
            label = source_labels.get(source, source)
            print(f"\n  ── Explorando {label} ──")

            # Dry-run: descubrir y mostrar preview
            engine.discover(source)
            if not engine._report.items_migrated:
                print(f"  📭 No se encontró nada para importar desde {label}")
                continue

            engine.print_preview(engine._report)

            if not self._confirm("\n  ¿Proceder con la migración?"):
                print(f"  Migración de {label} cancelada.")

                continue

            # ── Pre-scan: escanear fuente ANTES de migrar ──
            print(f"\n  🔍 Pre-escaneando {label} (antes de copiar)...")
            caja_pre = SecurityCaja()
            source_paths = {
                "hermes": Path.home() / ".hermes",
                "openclaw": Path.home() / ".openclaw",
            }
            src = source_paths.get(source)
            if src and src.exists():
                pre_report = caja_pre.scan_profile(src)
                if pre_report.items_blocked > 0:
                    print(f"  ⚠️  Se detectaron {pre_report.items_blocked} archivo(s) bloqueados en el origen.")
                    caja_pre.print_scan_report(pre_report)
                    if not self._confirm("  ¿Continuar con la migración? (pueden saltarse archivos)"):
                        print("  Migración cancelada por seguridad.")
                        continue
                elif pre_report.items_cleaned > 0:
                    print(f"  ⚠️  {pre_report.items_cleaned} archivo(s) serán limpiados durante la migración.")
                else:
                    print(f"  ✅ Origen limpio — sin hallazgos.")

            # ── Phase 1: Migrate files ──
            print(f"\n  ⏳ Migrando {label}...")
            result = engine.migrate(engine._report, execute=True)
            engine.print_report(result)

            if result.items_migrated:
                self._log.info("torre", f"Adoption: {len(result.items_migrated)} items migrados desde {source}")

                # Extraer credenciales migradas y guardarlas en CajaSeguraInfo
                adopted_creds = {}
                # Mapeo de env vars a provider_ids de DIGOS
                ENV_TO_PROVIDER = {
                    "OPENAI_API_KEY": "1",
                    "ANTHROPIC_API_KEY": "2",
                    "GOOGLE_API_KEY": "3",
                    "DEEPSEEK_API_KEY": "4",
                    "OPENROUTER_API_KEY": "5",
                    "GROQ_API_KEY": "6",
                    "XAI_API_KEY": "7",
                    "COHERE_API_KEY": "8",
                    "MISTRAL_API_KEY": "9",
                    "TOGETHER_API_KEY": "10",
                    "FIREWORKS_API_KEY": "11",
                }
                for item in result.items_migrated:
                    if item.kind == "api_key":
                        # Buscar cualquier env var de provider en el .env migrado
                        for env_var, pid in ENV_TO_PROVIDER.items():
                            val = self._extract_adopted_env(item, env_var)
                            if val:
                                adopted_creds["api_key"] = val
                                adopted_creds["provider_id"] = pid
                                break  # primer provider encontrado
                    if item.kind == "telegram_token":
                        val = self._extract_adopted_env(item, "TELEGRAM_BOT_TOKEN")
                        if val:
                            adopted_creds["gateway_token"] = val
                            adopted_creds["gateway_type"] = "1"
                if adopted_creds:
                    CajaSeguraInfo.write_slot("principal", adopted_creds)
                    self.state["_creds_imported"] = True
                    self._save_state()

            # ── Phase 2: Safe Box — scan profiles for injection ──
            profiles = [p for p in result.profiles_found
                       if p != "global"]
            if profiles:
                caja = SecurityCaja()
                print(f"\n  🔒 Caja Segura escaneando perfiles...")
                for profile in profiles:
                    profile_dir = DIGOS_DIR / "profiles" / profile
                    if not profile_dir.exists():
                        continue
                    print(f"    Escaneando: {profile}")
                    sr = caja.scan_profile(profile_dir)
                    if sr.items_blocked > 0:
                        print(f"    ❌ {profile}: BLOQUEADO — {sr.items_blocked} hallazgo(s) crítico(s)")
                        caja.print_scan_report(sr)
                        if not self._confirm(f"    ¿Ignorar y forzar importación de {profile}?"):
                            print(f"    Perfil {profile} excluido por seguridad.")
                            continue
                    elif sr.items_cleaned > 0:
                        print(f"    ⚠️  {profile}: {sr.items_cleaned} archivo(s) limpiados")
                        caja.print_scan_report(sr)
                    else:
                        print(f"    ✅ {profile}: Sin hallazgos")
                caja.print_audit()

            # ── Phase 3: Transform profiles (TorreDeControl takes domain) ──
            profiles = [p for p in result.profiles_found
                       if p != "global"]
            if profiles:
                print(f"\n  🏰 Torre de Control transformando perfiles...")
                for profile in profiles:
                    print(f"    Procesando: {profile}")
                    t_result = transformer.transform_profile(profile)
                    if t_result.get("ok"):
                        for t in t_result.get("transformations", []):
                            print(f"      ✅ {t}")
                    else:
                        err_msg = t_result.get("error", t_result.get("errors", "Error desconocido"))
                        if isinstance(err_msg, list):
                            for e in err_msg:
                                print(f"      ❌ {e}")
                        else:
                            print(f"      ❌ {err_msg}")
                transformer.print_report()

            print(f"\n  ✅ Adopción de {label} completada.")

        # Si se migró algo, ofrecer continuar con setup ya configurado
        print()
        print("  Puedes continuar con la configuración manual para")
        print("  completar lo que no se haya migrado automáticamente.")

    # ── Helpers ──

    @staticmethod
    def _confirm(question: str, default: bool = True) -> bool:
        """Pide confirmación Sí/No al usuario."""
        prompt = " (S/n): " if default else " (s/N): "
        while True:
            try:
                resp = input(question + prompt).strip().lower()
                if not resp:
                    return default
                if resp in ("s", "si", "y", "yes"):
                    return True
                if resp in ("n", "no"):
                    return False
            except (EOFError, KeyboardInterrupt):
                return False
            print("  Responde 's' o 'n'.")

    @staticmethod
    def _extract_adopted_env(item, var_name: str) -> str:
        """Extracts the value of a .env variable from migrated items."""
        env_path = Path(item.dest_path) if item.dest_path.endswith(".env") else None
        if not env_path or not env_path.exists():
            # Intentar path alternativo para secrets globales
            alt = DIGOS_DIR / "imported" / "hermes" / ".env"
            if alt.exists():
                env_path = alt
            else:
                return ""
        secrets = AdoptionEngine._parse_env(env_path)
        return secrets.get(var_name, "")

    # ── Paso 1: Idioma ──

    def _step_language(self):
        print("🌐 IDIOMA / LANGUAGE")
        print("─" * 40)
        for k, v in LANGUAGES.items():
            print(f"  [{k}] {v['name']}")
        print("  [0] Salir")
        print()
        while True:
            choice = input("Selecciona tu idioma → ").strip()
            if choice == "0":
                raise GoBack()
            if choice in LANGUAGES:
                self.lang = LANGUAGES[choice]["code"]
                self.state["language"] = self.lang
                self._save_state()
                print()
                print(f"  {LANGUAGES[choice]['welcome']}")
                print()
                return
            print("  Opción inválida. Intenta de nuevo.")

    # ── Paso 3: API Key (con validación de formato + 10 intentos) ──

    MAX_KEY_ATTEMPTS = 10

    def _step_api_key(self) -> Tuple[str, str]:
        print("🔑 PROVEEDOR DE IA / AI PROVIDER")
        print("─" * 40)
        print("  Elige el proveedor para tu agente principal:")
        print()
        for k, v in PROVIDERS.items():
            print(f"  [{k}] {v['name']}  ({v['key_hint']})")
        print("  [0] Volver al paso anterior")
        print()

        provider_id = None
        while provider_id is None:
            choice = input("Proveedor → ").strip()
            if choice == "0":
                raise GoBack()
            if choice in PROVIDERS:
                provider_id = choice
            else:
                print("  Opción inválida.")

        provider = PROVIDERS[provider_id]
        print(f"\n  → Proveedor: {provider['name']}")
        print()

        api_key = None
        key_attempts = 0
        while api_key is None:
            key_attempts += 1
            remaining = self.MAX_KEY_ATTEMPTS - key_attempts

            if remaining == 1:
                print(f"  ⚠️  ¡ÚLTIMO INTENTO! Te queda {remaining} intento.")
            elif remaining == 0:
                print(f"  ⏳ ÚLTIMA OPORTUNIDAD — Te quedan {remaining} intentos. Escribe tu API Key cuidadosamente.")
            elif remaining <= 3 and remaining > 0:
                print(f"  ⚠️  Te quedan {remaining} de {self.MAX_KEY_ATTEMPTS} intentos.")
            elif remaining < 0:
                print(f"  ❌ Has agotado tus {self.MAX_KEY_ATTEMPTS} intentos. Volviendo al menú anterior...")
                raise GoBack()

            import getpass
            raw = getpass.getpass(f"  Ingresa tu API Key de {provider['name']}:\n  → ")
            if raw == "0":
                raise GoBack()
            if not raw:
                print("  La API Key no puede estar vacía.")
                continue

            # Validación de formato por proveedor
            fmt_ok, fmt_msg = self._validate_api_key_format(provider_id, raw)
            if not fmt_ok:
                print(fmt_msg)
                print("  Vuelve a intentar con una key que coincida con el formato esperado.")
                continue

            api_key = raw

            # Test de conexión
            print(f"\n  🔍 Probando conexión con {provider['name']}...")
            ok, msg = self._test_provider(provider_id, api_key)
            if ok:
                print(f"  ✅ {msg}")
            else:
                print(f"  ⚠️  {msg}")
                cont = input("  ¿Continuar de todas formas? (s/N): ").strip().lower()
                if cont == "s":
                    break  # continuar con key que falló test
                print()
                # Reintentar: reset api_key para que el loop pida otra
                api_key = None
                key_attempts -= 1  # no cuenta como intento si el usuario eligió reintentar

        print()
        return provider_id, api_key

    # ── Validación de formato de API Key por proveedor ──

    @staticmethod
    def _validate_api_key_format(provider_id: str, api_key: str) -> Tuple[bool, str]:
        """Valida que la API Key tenga el formato esperado según el proveedor.
        Returns (valid, mensaje_de_error).
        """
        patterns = {
            "1":  (r"^sk-",       "debe empezar con 'sk-'"),
            "2":  (r"^sk-ant-",   "debe empezar con 'sk-ant-'"),
            "3":  (r"^AI",        "debe empezar con 'AI'"),
            "4":  (r"^sk-",       "debe empezar con 'sk-'"),
            "5":  (r"^sk-or-",    "debe empezar con 'sk-or-'"),
            "6":  (r"^gsk_",      "debe empezar con 'gsk_'"),
            "7":  (r"^xai-",      "debe empezar con 'xai-'"),
        }
        if provider_id not in patterns:
            return True, ""  # sin patrón para este proveedor
        import re
        pattern, hint = patterns[provider_id]
        if re.match(pattern, api_key):
            return True, ""
        return False, f"  ⚠️  Formato inválido: la API Key {hint}"

    def _test_provider(self, provider_id: str, api_key: str) -> Tuple[bool, str]:
        ok, msg, status = _provider_api_request(provider_id, api_key)
        if ok:
            return True, "Conexión exitosa."
        if status in (401, 403):
            return False, f"API Key inválida (HTTP {status})."
        return False, f"No se pudo conectar: {msg}"

    # ── 🎯 PRINCIPAL AGENT IS BORN ──

    def _birth_agent(self, provider_id: str):
        provider = PROVIDERS[provider_id]

        agente = {
            "name": "Agente Principal",
            "born_at": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
            "provider_id": provider_id,
            "provider_name": provider["name"],
            "language": self.lang,
            "self_awareness": {
                "identity": "DIGOS Agent",
                "version": VERSION,
                "born": datetime.now(timezone.utc).isoformat(),
                "purpose": "Servir al usuario como agente inteligente."
            },
            "gps": {
                "origin": "Torre de Control",
                "home": str(DIGOS_DIR),
                "state": "naciendo"
            },
            "work_destination": {
                "mode": "onboarding",
                
            },
            "kendo": {
                "type": "safety_candle",
                "rules": [
                    "Proteger credenciales del usuario",
                    "No ejecutar comandos sin autorización",
                    "Reportar actividad sospechosa",
                    "Mantener integridad del sistema"
                ],
                "active": True
            }
        }

        self.state["agente"] = agente
        self._save_state()

        print(f"\n  🎯 ¡AGENTE PRINCIPAL HA NACIDO!")
        print(f"     Nombre: {agente['name']}")
        print(f"     Proveedor: {provider['name']}")
        print(f"     Self-Awareness inyectada.")
        print(f"     Safety Candle (Kendo) activo.")
        print()

        self._log.info("torre", {"provider": provider["name"]})

    # ── POLÍTICA DEL SISTEMA ─────────────────

    def _check_operation(self, tool_name: str, args: dict) -> dict:
        """Evaluates an operation against the system policy.
        Returns dict with level and explanation.

        🔴 ROJO: prohibido — ni el usuario puede hacerlo
        🟡 AMARILLO: requiere ticket del Engineer
        🟢 VERDE: permitido
        """
        file_path = ""
        if tool_name in ("write_file", "read_file"):
            file_path = args.get("path", "")

        # Terminal con comandos destructivos
        if tool_name == "terminal":
            cmd = args.get("command", "").lower()
            for pattern in self.FORBIDDEN_PATTERNS:
                if pattern in cmd:
                    return {"level": "red", "reason":
                        f"Operacion prohibida: afecta archivos protegidos ({pattern}).",
                        "explanation": "Esta operacion danaria el ecosistema del sistema. "
                                       "No se puede ejecutar bajo ninguna circunstancia."}

        # Paths prohibidos en operaciones de archivo
        if file_path:
            for pattern in self.FORBIDDEN_PATTERNS:
                if pattern in file_path:
                    return {"level": "red", "reason":
                        f"Operacion prohibida: {file_path} contiene '{pattern}'.",
                        "explanation": "Este archivo o directorio es parte del nucleo del sistema. "
                                       "No se puede modificar ni eliminar."}
            # Escribir en DIGOS_DIR prohibido
            if tool_name == "write_file" and str(DIGOS_DIR) in file_path:
                return {"level": "red", "reason":
                    f"No se puede escribir en {DIGOS_DIR}.",
                    "explanation": "Los archivos de configuracion del sistema estan protegidos."}

        # Amarillo: operaciones sensibles crean ticket y BLOQUEAN
        if tool_name in ("write_file", "terminal", "execute_code"):
            tid = ""
            ticket_status = "pending_approval"
            if hasattr(self, '_engineer') and self._engineer:
                tid = self._engineer.create_ticket(
                    "system", f"tool:{tool_name}",
                    f"Operacion sensible requiere aprobacion: {tool_name} args={str(args)[:100]}",
                    "medium", source="torre_de_control")
                self._log.info("torre", f"Ticket #{tid} creado (PENDING) para: {tool_name}")
            return {"level": "pending", "reason":
                f"Operacion sensible: {tool_name}. Requiere aprobacion del Engineer.",
                "explanation": f"Se ha creado el ticket #{tid} con estado pendiente. "
                               "Cuando el Engineer lo apruebe, puedes intentarlo de nuevo.",
                "ticket_id": tid}

        return {"level": "green", "reason": ""}

    def _approval_callback(self, tool_name: str, args: dict) -> bool:

        result = self._check_operation(tool_name, args)
        if result["level"] == "red":
            msg = f"⛔ {result['explanation']}"

            if self._tracker:
                self._tracker.on_assistant_message(msg)
            return False
        if result["level"] == "pending":
            msg = f"⏳ {result['explanation']}"

            if self._tracker:
                self._tracker.on_assistant_message(msg)
            return False
        return True

    # ── Paso 4: Gateway ──

    def _step_gateway(self) -> Tuple[str, str]:
        print("📡 GATEWAY / CANAL DE COMUNICACIÓN")
        print("─" * 40)
        print("  Elige cómo se comunicará tu agente:")
        print()
        for k, v in GATEWAYS.items():
            name = v["name"]
            note = v.get("note", "")
            note_str = f" — {note}" if note else ""
            print(f"  [{k}] {name}{note_str}")
        print("  [0] Volver al paso anterior")
        print()

        while True:
            gateway_id = None
            while gateway_id is None:
                choice = input("Gateway → ").strip()
                if choice == "0":
                    raise GoBack()
                if choice in GATEWAYS:
                    gateway_id = choice
                else:
                    print("  Opción inválida.")

            gateway = GATEWAYS[gateway_id]
            print(f"\n  → Gateway: {gateway['name']}")
            print()

            if gateway["type"] == "telegram":
                try:
                    token = self._setup_telegram()
                except GoBack:
                    print("  Volviendo a selección de gateway...\n")
                    continue
                break  # token obtenido exitosamente

            # Gateways no-Telegram
            print(f"  ⏳ {gateway['name']} requiere configuración manual.")
            print(f"     {gateway.get('note', '')}")
            cont = input("  ¿Marcar como configurado más tarde? (s/N): ").strip().lower()
            if cont != "s":
                print()
                continue  # volver al menú de gateways
            token = ""
            break

        print()
        return gateway_id, token

    def _setup_telegram(self) -> str:
        print("  🤖 Telegram Bot Token")
        print("  (Consíguelo en @BotFather en Telegram)")
        print("  [0] Volver a selección de gateway")
        print()

        tg_attempts = 0
        while True:
            tg_attempts += 1
            remaining = self.MAX_KEY_ATTEMPTS - tg_attempts

            if remaining == 1:
                print(f"  ⚠️  ¡ÚLTIMO INTENTO! Te queda {remaining} intento.")
            elif remaining == 0:
                print(f"  ⏳ ÚLTIMA OPORTUNIDAD — Te quedan {remaining} intentos. Escribe tu token cuidadosamente.")
            elif remaining <= 3 and remaining > 0:
                print(f"  ⚠️  Te quedan {remaining} de {self.MAX_KEY_ATTEMPTS} intentos.")
            elif remaining < 0:
                print(f"  ❌ Has agotado tus {self.MAX_KEY_ATTEMPTS} intentos. Volviendo a selección de gateway...")
                raise GoBack()

            raw = input("  Bot Token → ").strip()
            if raw == "0":
                raise GoBack()
            if not raw:
                print("  El token no puede estar vacío.")
                continue

            print(f"\n  🔍 Probando conexión con Telegram...")
            ok, msg = self._test_telegram(raw)
            if ok:
                print(f"  ✅ {msg}")
                return raw
            else:
                print(f"  ⚠️  {msg}")
                cont = input("  ¿Continuar de todas formas? (s/N): ").strip().lower()
                if cont == "s":
                    return raw
                print("  Vuelve a intentar con otro token.\n")
                tg_attempts -= 1  # no cuenta como intento si el usuario rechazó continuar
                continue

    def _test_telegram(self, token: str) -> Tuple[bool, str]:
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            with urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("ok") and "result" in data:
                    bot_name = data["result"].get("first_name", "Bot")
                    username = data["result"].get("username", "?")
                    return True, f"Bot '{bot_name}' (@{username}) conectado."
                return False, "Token inválido."
        except HTTPError as e:
            return False, f"Token rechazado (HTTP {e.code})."
        except URLError as e:
            return False, f"No se pudo conectar: {e.reason}"
        except json.JSONDecodeError:
            return False, "Respuesta inesperada del servidor."
        except Exception as e:
            return False, f"Error: {e}"

    # ── Paso 5: Caja Segura ──

    def _step_vault(self, api_key: str, gateway_token: str):
        print("🔒 CAJA SEGURA INFO")
        print("─" * 40)
        print("  Guardando credenciales en cabinet seguro...")

        creds = {
            "api_key": api_key,
            "gateway_token": gateway_token,
            "provider_id": self.state.get("agente", {}).get("provider_id", ""),
            "model": self._provider_default_model(
                self.state.get("agente", {}).get("provider_id", "")
            ),
            "created_at": self.state.get("agente", {}).get("born_at", "")
        }
        ok = CajaSeguraInfo.write_slot("principal", creds)
        if ok:
            print("  ✅ Credenciales guardadas en CajaSeguraInfo (slot: principal)")
        else:
            print("  ⚠️  Error al guardar credenciales")
        print()

    # ── Paso 6: Finalizar Setup + Handoff ──

    def _finalize_setup(self, provider_id: str, gateway_id: str):
        agente = self.state.get("agente", {})
        agente["gateway_type"] = GATEWAYS[gateway_id]["type"]
        agente["gateway_configured"] = True
        agente["setup_complete"] = True
        agente["work_destination"] = {
            "mode": "activo",
            
        }
        agente.setdefault("gps", {})
        agente["gps"]["state"] = "activo"

        self.state["setup_complete"] = True
        self.state["agente"] = agente
        self.state["gateway"] = {"id": gateway_id, "type": GATEWAYS[gateway_id]["type"]}
        self.state["version"] = VERSION
        self._save_state()

    def _handoff(self):
        agente = self.state.get("agente", {})
        print("  ╔══════════════════════════════════════╗")
        print("  ║     🚀  HANDOFF COMPLETADO           ║")
        print("  ║                                      ║")
        print("  ║  Torre de Control entrega el control  ║")
        print("  ║  al Agente Principal.                ║")
        print("  ║  TORRE: Centinela + Engineer activos ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        print(f"     Agente:   {agente.get('name', 'Principal')}")
        print(f"     Proveedor: {agente.get('provider_name', '?')}")
        print(f"     Gateway:  {agente.get('gateway_type', '?')}")
        print(f"     Estado:   ✅ Activo")
        print()
        print("  El agente ya está listo para recibir instrucciones.")
        print("  TORRE vigila en segundo plano.")
        print()

        # Initialize Engine (GPS/SELF/WORK) before entering any mode
        self._init_engine()

        # Iniciar automáticamente en modo daemon (solo si hay terminal)
        if not self._daemon_mode and self.state.get("setup_complete") and sys.stdin.isatty():
            if self._confirm("  \u00bfIniciar DIGOS en modo 24/7?"):
                print("\n  🚀 Iniciando modo daemon...")
                self._daemon_mode = True
                self._running = True
                self._self_awareness.activate()
                self._init_gateways()
                self._init_bus()
                self._init_agent()
                self._run_daemon()
            else:
                self._start_interactive()
        else:
            print("  Usa: digos --daemon para iniciar modo 24/7")
            print()

    def _start_interactive(self):
        """Modo interactivo CLI — agente iniciado sin daemon.
        Inicializa el agente y entra en un loop de chat."""
        self._running = True
        self._self_awareness.activate()

        # Inicializar gateways (CLI + Telegram si hay token)
        self._init_gateways()
        self._init_bus()
        self._init_engine()
        self._init_agent()

        if self._agent is None:
            print("  ⚠️  No se pudo iniciar el agente. Verifica tus credenciales.")
            self._running = False
            return

        if self._engine is not None:
            print(f"  🧭 Engine (GPS/SELF/WORK) activo")

        # Initialize Activity Panel for live CLI progress display
        self._activity_panel = ActivityPanel()

        print()
        print("  🖥️  Modo interactivo iniciado.")
        print("  Escribe tus mensajes. 'exit' o 'quit' para salir.")
        print()

        while self._running:
            # Poll gateways for incoming messages
            # CLI gateway ahora lee stdin via su thread interno
            self._poll_gateways()
            time.sleep(0.5)
            print()

        # Cleanup
        for gw_id, gw in list(self._gateways.items()):
            try:
                gw.stop()
            except Exception as e:
                self._log.warn("torre", f"Gateway '{gw_id}' stop error: {e}")
        if self._bus:
            try:
                self._bus.stop()
            except Exception as e:
                self._log.warn("torre", f"Bus stop error: {e}")
        self._self_awareness.pause()
        print("  👋 ¡Hasta luego!")
        print()

    # ── DAEMON MODE ──

    def _run_daemon(self):
        """Modo daemon: Torre de Control vive 24/7 con TORRE activa."""
        self._running = True
        self._self_awareness.activate()

        # ── Async Gateway: ThreadPoolExecutor para no bloquear el loop ──
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="digos-gw-")

        # Initialize Phase 3 gateways (only if not already initialized)
        if not self._gateways:
            self._init_gateways()

        # Initialize Phase 6 Message Bus (only if not already initialized)
        if self._bus is None:
            self._init_bus()

        # Initialize Phase 4b: AIAgent (only if not already initialized)
        # Initialize Engine (GPS/SELF/WORK) BEFORE agent so context gets injected
        self._init_engine()

        if self._agent is None:
            self._init_agent()

        # Handle SIGTERM/SIGINT for clean shutdown
        # (ANTES de _ensure_launchd para capturar interrupciones)
        def _handle_signal(sig, frame):
            self._running = False

            # Detener gateways
            for gw_id, gw in list(self._gateways.items()):
                try:
                    gw.stop()
                except Exception as e:
                    self._log.warn("torre", f"Gateway '{gw_id}' stop error in signal handler: {e}")
            # Detener Message Bus
            if self._bus:
                try:
                    self._bus.stop()
                except Exception as e:
                    self._log.warn("torre", f"Bus stop error in signal handler: {e}")
            # Apagar executor de gateway
            if self._executor:
                self._executor.shutdown(wait=True)
                self._executor = None
            self._self_awareness.pause()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        # Auto-launch: asegurar que DIGOS vive 24/7 (después de signal handlers)
        self._ensure_launchd()

        print(f"\n  🏗️  TORRE DAEMON — v{VERSION}")
        print("  ─────────────────────────────")
        print(f"  Centinela: cada {CENTINELA_INTERVAL}s")
        print(f"  Logs:      {LOG_DIR}")
        print(f"  Estado:    {self._self_awareness.state}")
        print()


        self._log.info("torre", {"interval": CENTINELA_INTERVAL})

        while self._running:
            try:
                self._cycle_count += 1
                self._log.info("torre", f"Ciclo #{self._cycle_count}")

                # 1. Centinela: revisa API keys y tokens
                self._centinela_cycle()

                # 2. Gateway health check
                self._gateway_health_check()

                # 3. Engineer: processes pending reports
                self._engineer_cycle()

                # 🎻 Pipeline: notificar al agente sobre mensajes pendientes
                pipeline_alerts = self._pipeline.cycle()
                if pipeline_alerts:
                    for alert in pipeline_alerts:
                        self._log.info("pipeline",
                            f"🎻 Alerta: {alert['participant']} tiene mensaje sin leer "
                            f"en #{alert['ticket_id']} ({alert['minutes_unread']}m)")
                        # Si el agente tiene mensajes sin leer, inyectar notificación
                        if alert['participant'] == 'agente' and self._agent is not None:
                            pipeline_ctx = self._pipeline.get_summary_for_agent('agente')
                            if pipeline_ctx:
                                self._agent.inject_pipeline_context(pipeline_ctx)

                # 4. Poll gateways for incoming messages (every 2s)
                for _ in range(CENTINELA_INTERVAL // 2):
                    if not self._running:
                        break
                    self._poll_gateways()
                    self._cleanup_gateway_futures()
                    time.sleep(2)

            except Exception as e:

                self._self_awareness.set_error()
                time.sleep(10)

        # ── Shutdown async gateway executor ──
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
        self._self_awareness.pause()


    def _centinela_cycle(self):
        """Un ciclo de checks del Centinela."""
        vault = CajaSeguraInfo.read_slot("principal")
        if not vault:
            self._log.info("centinela", "No hay slot principal — saltando checks")
            return

        api_key = vault.get("api_key", "")
        provider_id = vault.get("provider_id", "")
        gateway_token = vault.get("gateway_token", "")

        # Check API key
        api_ok = self._centinela.check_api_key(provider_id, api_key)
        self._log.info("centinela", f"API key check: {'OK' if api_ok else 'FALLO'}")

        # Check Telegram token
        if gateway_token:
            tg_ok = self._centinela.check_telegram_token(gateway_token)
            self._log.info("centinela", f"Telegram token: {'OK' if tg_ok else 'FALLO'}")

        # Check alarmas y recordatorios pendientes
        fired = self._centinela._check_alarms()
        if fired:
            self._log.info("centinela", f"{len(fired)} alarma(s)/recordatorio(s) disparados")
            for fid in fired:
                # Search for more alarm details
                for al in self._centinela._alarms + self._centinela._reminders:
                    if al.get("id") == fid:
                        atype = "🔔" if al["type"] == "alarm" else "📌"
                        print(f"\n  {atype} {al['type'].upper()}: {al['title']}")
                        if al.get("description"):
                            print(f"     {al['description']}")
                        break

        # Process reports
        reports = self._centinela.get_reports()
        for report in reports:
            tid = self._engineer.receive_report(report)

            ticket_data = self._engineer.get_ticket(tid) or {}
            print(f"\n  ⚠️  CENTINELA DETECTÓ DEFECTO: {report['target']}")
            print(f"     → Ticket #{tid} creado con System Engineer")
            print(f"     → Diagnóstico: {ticket_data.get('diagnosis', 'pendiente')}")
            print()

        # ── Push credential notifications to user via gateways ──
        notification = self.inject_credential_ticket_notification()
        if notification:
            print(f"\n{notification}\n")
            # Push through Telegram gateway if available
            tg_gw = self._gateways.get("telegram")
            if tg_gw and tg_gw.status == "running":
                try:
                    chat_id = self.state.get("active_chat_id", "")
                    if chat_id:
                        tg_gw.send_message(chat_id, notification)
                        self._log.info("torre", "Notificación de credenciales enviada al usuario vía Telegram")
                except Exception as e:
                    self._log.warn("torre", f"Error notificando credenciales vía Telegram: {e}")

    def _engineer_cycle(self):
        """Procesa tickets abiertos del Engineer con flag persistente
        e integración con MASTER Risk Pattern Layer.

        ═══════════════════════════════════════════════════════
        🏭 ORQUESTACIÓN — CICLO DEL ENGINEER
        ═══════════════════════════════════════════════════════
        1. Revisar inbox: tickets con flag_status=inbox
        2. Auto-pickup de tickets del Centinela (los recoge al tiro)
        3. MASTER: verificar trayectoria de riesgo y crear tickets si es necesario
        4. Los tickets con needs_human quedan en processing para
           que el usuario los vea como "en proceso"
        5. Tickets en review → el Engineer revisa y entrega

        📖 Ver operations-manual.md — Sección 2: Ciclo de Vida
          para el pipeline completo inbox → processing → testing → review → delivered.
        ═══════════════════════════════════════════════════════
        """
        # ── 1. Revisar inbox ──
        inbox = self._engineer.get_inbox()
        for ticket in inbox:
            tid = ticket["id"]
            profile = ticket.get("profile", "system")
            source = ticket.get("source", "")
            requester = ticket.get("requester", "?")
            target = ticket.get("target", "?")

            self._log.info("engineer",
                f"🚩📥 Ticket #{tid} en inbox (requester={requester}, target={target})")

            # Auto-pickup para tickets del Centinela
            if source == "centinela":
                ok = self._engineer.pickup_ticket(profile, tid)
                if ok:
                    self._log.info("engineer",
                        f"👷 Ticket #{tid} (Centinela) auto-recogido → processing")
                    if ticket.get("needs_human"):
                        self._log.warn("engineer",
                            f"Ticket #{tid} necesita usuario: {ticket.get('diagnosis', '?')}")

        # ── 2. MASTER: verificar trayectoria de riesgo ──
        trajectory = self._master.get_trajectory_summary()
        if trajectory:
            for pid, info in trajectory.items():
                if info["count"] >= 3:
                    # Trayectoria alta — crear ticket en el Engineer
                    ticket_text = f"MASTER: patrón '{pid}' detectado {info['count']}x (severidad={info['severity']})"
                    tid = self._engineer.create_ticket(
                        "system", f"master:{pid}",
                        ticket_text,
                        "medium" if info.get("severity") == "medium" else "high",
                        source="master_risk"
                    )
                    self._log.warn("master",
                        f"Ticket #{tid} creado por trayectoria de riesgo: {pid} ({info['count']}x)")

        # ── 3. Revisar processing/testing/review ──
        all_open = self._engineer.get_open()
        for ticket in all_open:
            fs = ticket.get("flag_status", "")
            tid = ticket["id"]
            if fs == "inbox":
                continue  # ya procesado arriba
            if fs == "processing":
                assignee = ticket.get("assignee", "")
                if assignee:
                    self._log.info("engineer",
                        f"🏭 Ticket #{tid} → asignado a {assignee} (flag={fs})")
                else:
                    self._log.info("engineer",
                        f"👷 Ticket #{tid} → procesando (flag={fs}, sin asignar aún)")
            elif fs == "testing":
                self._log.info("engineer",
                    f"🧪 Ticket #{tid} → en testing (flag=testing) — esperando validación del agente")
            elif fs == "review":
                self._log.info("engineer",
                    f"🔍 Ticket #{tid} → en revisión (flag=review)")

    # ── ESTADO ──

    def status(self) -> dict:
        """Complete system status — including TOWER + MASTER Risk Layer."""
        agente = self.state.get("agente", {})

        print()
        print("📊 ESTADO DE DIGOS v" + VERSION)
        print("━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  Setup:       {'✅ Completo' if self.state.get('setup_complete') else '⏳ Pendiente'}")
        print(f"  Idioma:      {self.state.get('language', '?')}")
        if agente:
            print(f"  Agente:      {agente.get('name', '?')}")
            print(f"  Proveedor:   {agente.get('provider_name', '?')}")
            print(f"  Gateway:     {agente.get('gateway_type', '?')}")
            print(f"  Kendo:       {'✅ Activo' if agente.get('kendo', {}).get('active') else '❌ Inactivo'}")
        print()
        # 🕰️ RelojInterno
        if hasattr(self._self_awareness, 'clock') and self._self_awareness.clock:
            try:
                self._self_awareness.clock.print_status()
            except Exception:
                pass

        print("  ── TORRE (Auto-Preservación) ──")
        sa = self._self_awareness.status()
        print(f"  Self-Awareness: {sa['state']}")
        print(f"  Identidad:      {sa['identity']['name']} v{sa['identity']['version']}")
        print()

        # MASTER Risk Pattern Layer
        trajectory = self._master.get_trajectory_summary()
        if trajectory:
            print(f"  🧠 MASTER — Trayectoria de patrones activa:")
            for pid, info in trajectory.items():
                icon = "🔴" if info.get("action") == "block" else "🟡"
                print(f"     {icon} {pid}: {info['count']}x — última: {info['severity']}")
        else:
            print("  🧠 MASTER — Sin trayectoria de riesgo activa")
        print()

        # Centinela strikes
        strikes = self._centinela.get_all_strikes()
        if strikes:
            print(f"  ⚠️  Centinela — Strikes activos:")
            for k, v in strikes.items():
                print(f"     {k}: {v['count']}/{STRIKE_LIMIT} — {v.get('reason', '')}")
        else:
            print("  ✅ Centinela — Sin defectos detectados")
        print()

        # Engineer tickets con flag persistente
        open_tickets = self._engineer.get_open()

        # Flag summary
        print(self._engineer.flag_summary())
        print()

        if open_tickets:
            print(f"  ⚠️  System Engineer — Tickets abiertos: {len(open_tickets)}")
            for t in open_tickets[:3]:
                fs = t.get("flag_status", "?")
                rq = t.get("requester", "?")
                sev = t["severity"]
                print(f"     🚩 #{t['id']} [{sev}] flag={fs} [{rq}] {t['target']}: {t.get('diagnosis', '') or t['problem'][:50]}")
        else:
            print("  ✅ System Engineer — Sin tickets abiertos")
        print()

        all_tickets = self._engineer.get_all_tickets()
        total = len(all_tickets)
        profiles = set(t.get("profile", "?") for t in all_tickets)
        print(f"  Total tickets: {total} en {len(profiles)} perfil(es)")
        print()

        # Capability Truth Registry
        try:
            from digos_lib.agent_tools import capability_summary
            print(capability_summary())
            print()
        except Exception:
            pass

        # Gateways
        self.gateway_show_status()

    # ── COMANDOS DE TORRE ──

    def centinela_run_once(self):
        """Runs one Centinela check cycle (CLI mode)."""
        print("\n  🔍 CENTINELA — Ejecutando checks...")
        print("  ─────────────────────────────")
        self._centinela_cycle()
        print("  ✅ Ciclo completado.")
        print()

    def engineer_flag_status(self):
        """Muestra el pipeline completo de orquestación con flags.

        ═══════════════════════════════════════════════════════
        🏭 ORQUESTACIÓN — PIPELINE DE TRABAJO S&D
        ═══════════════════════════════════════════════════════

        📥 INBOX (tickets esperando al Engineer)
           ↓ pickup_ticket()
        🔧 PROCESSING (Engineer trabaja en el ticket)
           ↓ submit_for_testing()  ← 🆕 S&D
        🧪 TESTING (Agente prueba el resultado)
           ↓ test_ticket(passed=True)  ← 🆕 S&D
        🔍 REVIEW (Engineer revisa resultado final)
           ↓ deliver_ticket()
        ✅ DELIVERED (flag OFF — resultado entregado al creador)

        🧪 S&D REGLAS:
        - Si test_ticket(passed=False) → el ticket vuelve a PROCESSING
          con instrucciones de fallo documentadas en notes
        - close_ticket() ahora requiere pasar por TESTING (guardia S&D)
        - El agente puede ver su ticket persistente en todo momento

        El Engineer es el ÚNICO que:
        - Recoge tickets del inbox
        - Asigna trabajo a agentes de fábrica
        - Entrega resultados al creador

        Cada ticket tiene UN solo asignado y UNA sola entrega.

        📖 Ver operations-manual.md — Sección 5: S&D Guards
          para la tabla completa de precondiciones y guards.
        ═══════════════════════════════════════════════════════
        """
        print(f"\n  {self._engineer.flag_summary()}")

        inbox = self._engineer.get_inbox()
        if inbox:
            print("\n  📥 INBOX — Pendientes de recoger:")
            for t in inbox[:5]:
                print(f"     📬 #{t['id']} [{t.get('requester','?')}] {t.get('target','?')}")

        all_open = self._engineer.get_open()
        processing = [t for t in all_open if t.get('flag_status') in ('processing', 'testing', 'review')]
        if processing:
            print("\n  🔧 EN PROCESO:")
            for t in processing[:5]:
                fs = t.get('flag_status', '?')
                assignee = t.get('assignee', '')
                assign_str = f" → {assignee}" if assignee else ""
                icon = {'review': '🔍', 'testing': '🧪'}.get(fs, '🔧')
                print(f"     {icon} #{t['id']} [{t.get('requester','?')}{assign_str}] {t.get('target','?')}")

        all_tickets = self._engineer.get_all_tickets()
        delivered = [t for t in all_tickets if t.get('flag_status') == 'delivered']
        if delivered:
            print(f"\n  ✅ Últimas entregas:")
            for t in delivered[-3:]:
                print(f"     ✅ #{t['id']} → {t.get('requester','?')}: {t.get('result','')[:60]}")
        print()

    def engineer_show_tickets(self, status: str = None):
        """Muestra tickets del Engineer con flag persistente."""
        if status:
            tickets = self._engineer.get_open() if status == "open" else self._engineer.get_all_tickets()
        else:
            tickets = self._engineer.get_all_tickets()

        if not tickets:
            print("\n  📋 No hay tickets.\n")
            return

        # ── Mostrar flag summary al inicio ──
        print(f"\n  {self._engineer.flag_summary()}")
        print(f"\n  📋 TICKETS DETALLE ({len(tickets)})")
        print("  ────────────────────────")
        for t in tickets:
            sev_icon = "🔴" if t["severity"] == "high" else "🟡" if t["severity"] == "medium" else "🟢"
            status_icon = "🔧" if t["status"] == "diagnosing" else "📌" if t["status"] == "open" else "✅"

            # Flag icon
            fs = t.get("flag_status", "?")
            flag_icon = {
                "inbox": "📥",
                "processing": "🔧",
                "testing": "🧪",
                "review": "🔍",
                "delivered": "✅",
            }.get(fs, "🚩")

            requester = t.get("requester", "?")
            assignee = t.get("assignee", "")
            assignee_str = f" → {assignee}" if assignee else ""

            print(f"  {sev_icon} {flag_icon} #{t['id']:>4} [{fs:>10}] [{t['status']:>10}] "
                  f"{t['target']:20s} req={requester}{assignee_str}  "
                  f"{t.get('diagnosis', t['problem'])[:40]}")
        print()

    def logs_show(self, level: str = None, source: str = None, limit: int = 20):
        """Shows system logs."""
        logs = self._log.get_logs(level=level, source=source, limit=limit)
        if not logs:
            print("\n  📝 No hay logs.\n")
            return
        print(f"\n  📝 LOGS ({len(logs)} entries)")
        print("  ────────────────")
        for entry in logs:
            ts = entry.get("ts", "?")[11:19]
            lvl = entry.get("level", "?")
            src = entry.get("source", "?")
            msg = entry.get("msg", "")
            print(f"  {ts} [{lvl:5s}] [{src:10s}] {msg}")
        print()

    # ── Fase 3: GATEWAYS ──

    def _init_gateways(self):
        """Inicializa los gateways registrados en CajaSeguraInfo.
        CLI arranca siempre (thread de stdin no bloquea).
        Telegram solo si hay token configurado.
        """
        vault = CajaSeguraInfo.read_slot("principal")
        if not vault:

            return
        gw_token = vault.get("gateway_token", "")
        # CLI gateway: siempre disponible (thread no bloqueante)
        cli = GatewayCLI()
        cli.set_logger(self._log)
        self.register_gateway(cli)
        cli.start()
        # Telegram si hay token
        if gw_token:
            tg = GatewayTelegram(gw_token)
            tg.set_logger(self._log)
            self.register_gateway(tg)
            tg.start()


    def register_gateway(self, gateway: 'BaseGateway'):
        """Registers a gateway in the system. If Telegram, connects transparency."""
        self._gateways[gateway.id] = gateway

        self._init_transparency()

    # ── FASE 4: TRANSPARENCIA ───────────────────

    def _init_transparency(self):
        """Initializes the progress tracker. Looks for a Telegram gateway to connect."""
        if self._tracker is not None:
            return  # ya está conectado

        tg_gw = self._gateways.get("telegram")
        if not tg_gw or not tg_gw._token:
            return  # no hay gateway Telegram disponible

        # Obtener chat_id del estado (último chat activo)
        chat_id = self.state.get("active_chat_id", "")

        self._tracker = ToolProgressTracker(
            send_fn=tg_gw.send_message,
            edit_fn=tg_gw.edit_message,
            action_fn=tg_gw.send_chat_action,
            chat_id=chat_id,
            mode="new",  # modo por defecto: solo cuando cambia de tool
        )


    def emit_tool_progress(self, tool_name: str, args: Optional[Dict] = None):
        """Llama al tracker cuando el agente empieza un tool."""
        if self._tracker is not None:
            self._tracker.on_tool_start(tool_name, args or {})
        if self._activity_panel is not None:
            preview = ""
            if args:
                from transparency import PRIMARY_ARGS
                key = PRIMARY_ARGS.get(tool_name)
                if key and key in args:
                    preview = str(args[key])[:36]
            self._activity_panel.show(tool_name, preview=preview)

    def emit_tool_end(self, tool_name: str):
        """Llama al tracker cuando el agente termina un tool."""
        if self._tracker is not None:
            self._tracker.on_tool_end(tool_name)
        # Mark as ✅ in the Activity Panel so the user sees progress
        if self._activity_panel is not None:
            self._activity_panel.mark_done(tool_name)

    def emit_tool_error(self, tool_name: str, error: str = ""):
        """Marks a tool as failed in the Activity Panel with ❌."""
        if self._activity_panel is not None:
            self._activity_panel.mark_failed(tool_name)
        if self._tracker is not None:
            self._tracker.on_assistant_message(f"⚠️ Tool '{tool_name}' falló: {error[:120]}")

    def emit_assistant_message(self, text: str):
        """Calls the tracker when the model generates text between tools."""
        if self._tracker is not None:
            self._tracker.on_assistant_message(text)
        if self._activity_panel is not None:
            self._activity_panel.update_message(text)

    def set_active_chat(self, chat_id: str):
        """Updates the active chat and reconnects the tracker if necessary."""
        self.state["active_chat_id"] = chat_id
        self._save_state()
        if self._tracker is not None:
            self._tracker._chat_id = chat_id


    # ── FASE 4b: AIAGENT ──────────────────────

    # ── FASE 8: INTERNAL AGENT CREATION ────────

    def _init_factory(self):
        """Inicializa la Factoría (FactoryManager + SuperiorAgent).

        Conecta el sistema DIGOS con la Factoría del código madre.
        Solo se inicializa una vez.
        """
        if self._factory_manager is not None:
            return
        try:
            # Ensure master/ directory is on sys.path for Factory imports
            if MASTER_DIR and MASTER_DIR not in sys.path:
                sys.path.insert(0, MASTER_DIR)
            from factory.manager import FactoryManager
            from factory.superior import SuperiorAgent

            self._factory_manager = FactoryManager()
            self._factory_manager.setup()
            # ── Connect transparency layer to Factory ──
            # Now the user sees Factory pipeline progress in Telegram:
            #   🏭 Creando Builder... → 🤖 Builder modificando... → 🔍 Auditor verificando...
            self._factory_manager._progress_cb = self.emit_tool_progress
            self._superior_agent = self._factory_manager._superior
            self._log.info("torre", "Factoría inicializada — agentes internos disponibles (con transparencia)")
        except Exception as e:
            self._log.warn("torre", f"Factoría no disponible: {e}")
            self._factory_manager = None
            self._superior_agent = None

    def request_internal_agent_creation(
        self,
        agent_type: str,
        mode: str = "collaborative",
        name: str = "",
        mission: str = "",
        requester: str = "agente",
    ) -> dict:
        """Creates an internal agent through the Factory.

        This is called by the AIAgent when the user says "crea 2 builders".
        The flow:
          1. SystemEngineer creates audit ticket
          2. TorreDeControl initializes Factory if needed
          3. SuperiorAgent creates the agent with the chosen mode
          4. If collaborative → registers on MessageBus
          5. If isolated → only sees SuperiorAgent + Tower
          6. Torre inyecta SelfAwareness + GPS + Work + Kendo via AgentBase

        agent_type: 'builder' | 'auditor' | 'reviewer'
        mode: ☑️ 'collaborative' | ☑️ 'isolated'
        """
        # Ensure Factory is initialized
        self._init_factory()

        # Build the factory_create callback for SystemEngineer
        def _factory_create(atype, amode, aname, amission):
            if self._superior_agent is None:
                return None
            return self._superior_agent.create_internal(
                agent_type=atype,
                mode=amode,
                name=aname,
                mission=amission,
            )

        # Route through SystemEngineer (creates ticket + delegates)
        result = self._engineer.create_internal_agent(
            agent_type=agent_type,
            mode=mode,
            name=name,
            mission=mission,
            requester=requester,
            factory_create_fn=_factory_create,
        )

        # Register on MessageBus if collaborative
        if result.get("ok") and mode == "collaborative" and self._bus is not None:
            agent_name = result.get("agent_name", "")
            if agent_name:
                self._bus.register_agent(agent_name, mode=mode)
                self._log.info("torre", f"Agent '{agent_name}' registrado en MessageBus ({mode})")

        return result

    def list_internal_agents(self) -> list:
        """Lists all internal agents from the Factory."""
        if self._superior_agent is None:
            self._init_factory()
        if self._superior_agent is None:
            return []
        return [
            {
                "name": name,
                "type": agent.internal_type,
                "mode": agent.mode,
                "status": agent.status,
                "mission": agent.mission[:80],
                "capabilities": len(agent.get_capabilities()),
            }
            for name, agent in self._superior_agent.internal_agents.items()
        ]

    @staticmethod
    def _check_existing_resource(capability: str) -> dict:
        """Verifica si un recurso/capacidad ya existe en el sistema
        antes de mandarlo a la Factory.

        ═══════════════════════════════════════════════════════
        🔍 S&D: VERIFICACIÓN DE RECURSOS EXISTENTES
        ═══════════════════════════════════════════════════════
        El System Engineer DEBE verificar si un recurso ya existe
        antes de ordenar la creación de uno nuevo.

        Ahora usa el CapabilityTruthRegistry para reportar el estado
        HONESTO de cada capacidad — no solo "existe" o "no existe".

        Estados:
        - unknown       → nunca se verificó
        - detected      → recurso encontrado pero NO registrado aún
        - registered    → en AVAILABLE_CAPABILITIES, tool existe
        - tool_ready    → tool real en DYNAMIC_TOOLS
        - validated     → tool pasó pruebas

        📖 Ver operations-manual.md — Sección 6: Flujo por Tipo
          para las reglas de detección de cada tipo de capacidad.
        ═══════════════════════════════════════════════════════
        """
        import shutil
        from digos_lib.agent_tools import (
            is_capability_available, AVAILABLE_CAPABILITIES,
            capability_get_info, capability_set_detected,
            CapabilityState,
        )

        # ── 0. Verificar en CapabilityTruthRegistry primero ──
        registry_entry = capability_get_info(capability)
        if registry_entry is not None:
            state = registry_entry.get("state", CapabilityState.UNKNOWN)
            tool = registry_entry.get("tool_name", "")
            ticket = registry_entry.get("ticket_id", "")
            if state in (CapabilityState.TOOL_READY, CapabilityState.VALIDATED):
                return {
                    "exists": True,
                    "state": state,
                    "resource": capability,
                    "tool": tool,
                    "ticket_id": ticket,
                    "message": f"Capacidad '{capability}' ya está [{state}] (tool: {tool}).",
                }
            elif state in (CapabilityState.DETECTED, CapabilityState.REGISTERED):
                return {
                    "exists": False,
                    "state": state,
                    "resource": capability,
                    "tool": tool,
                    "ticket_id": ticket,
                    "needs_registration": state == CapabilityState.DETECTED,
                    "needs_validation": state == CapabilityState.REGISTERED,
                    "message": (
                        f"Capacidad '{capability}' está [{state}] pero todavía "
                        "no está lista para ejecución de producto."
                    ),
                }

        # ── 1. Verificar capacidades ya registradas (backward compat) ──
        try:
            if is_capability_available(capability):
                tool = AVAILABLE_CAPABILITIES.get(capability, "")
                return {
                    "exists": True,
                    "state": CapabilityState.REGISTERED,
                    "resource": capability,
                    "tool": tool,
                    "ticket_id": "",
                    "message": f"Capacidad '{capability}' ya está disponible (tool: {tool}). Conectando recurso existente.",
                }
        except Exception:
            pass

        # ── 2. Verificar Chrome/Chromium para capacidades web ──
        web_caps = {"web_browsing", "web_browser", "web_fetch", "cdp", "browser_automation"}
        if capability in web_caps or any(w in capability.lower() for w in ["browser", "chrome", "cdp", "web"]):
            chrome_paths = [
                shutil.which("google-chrome"),
                shutil.which("google-chrome-stable"),
                shutil.which("chromium"),
                shutil.which("chromium-browser"),
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            ]
            chrome_found = None
            for cp in chrome_paths:
                if cp and Path(cp).exists():
                    chrome_found = cp
                    break

            if chrome_found:
                # Marcar como DETECTED (NO registrar aún — necesita confirmación)
                try:
                    capability_set_detected(
                        capability, tool_name="",
                        source="chrome_detected",
                        notes=f"Chrome/Chromium detectado en: {chrome_found}"
                    )
                except Exception:
                    pass
                return {
                    "exists": False,
                    "state": CapabilityState.DETECTED,
                    "resource": "chrome",
                    "path": chrome_found,
                    "message": (
                        f"Chrome/Chromium detectado en: {chrome_found}. "
                        "El recurso CDP existe pero NO está registrado aún. "
                        "Usa register_capability() para activarlo."
                    ),
                }

        # ── 3. Verificar STT/TTS (depende del API key configurado) ──
        voice_caps = {"stt_audio_input", "tts_audio_output", "voice_full_duplex"}
        if capability in voice_caps:
            vault = CajaSeguraInfo.read_slot("principal")
            if vault and vault.get("api_key"):
                try:
                    capability_set_detected(
                        capability, tool_name=AVAILABLE_CAPABILITIES.get(capability, capability),
                        source="api_key_detected",
                        notes="API key configurada — acceso a Whisper/TTS disponible"
                    )
                except Exception:
                    pass
                return {
                    "exists": False,
                    "state": CapabilityState.DETECTED,
                    "resource": "api_key",
                    "message": (
                        "API key configurada con acceso a Whisper/TTS. "
                        "El recurso existe pero NO está registrado aún."
                    ),
                }

        return {"exists": False, "state": CapabilityState.UNKNOWN, "resource": None}

    def request_capability(
        self,
        capability: str,
        family: str,
        sub_intent: str,
        user_message: str,
        requester: str = "agente",
    ) -> dict:
        """Request a new capability detected via intent classification.

        When the AIAgent detects a capability gap (Camino B) and user confirms,
        this method routes the request through the FULL Factory pipeline:
          1. Looks up CapabilitySkillDefinition from intent_classifier
          2. Initializes Factory if needed
          3. Calls FactoryManager.request_new_capability() →
             Builder→Auditor→Reviewer→Release pipeline
          4. Also creates an audit ticket via SystemEngineer for traceability

        This is the bridge between the Intent Classifier and the Factory.
        """
        # ── 0. Verificar si el recurso ya existe ──
        from digos_lib.agent_tools import (
            register_capability, capability_set_state,
            capability_get_info, CapabilityState,
        )

        existing = self._check_existing_resource(capability)
        reg_state = existing.get("state", CapabilityState.UNKNOWN)

        if existing.get("exists"):
            self._log.info("torre",
                f"🔍 Recurso existente detectado para '{capability}': {existing.get('message')}")
            # Crear ticket de auditoría
            audit_tid = self._engineer.create_capability_request(
                capability=capability,
                family=family,
                sub_intent=sub_intent,
                user_message=user_message,
                requester=requester,
            ).get("ticket_id", "")

            # Si el recurso estaba DETECTED, promover a REGISTERED con ticket
            if reg_state == CapabilityState.DETECTED:
                try:
                    register_capability(
                        capability,
                        existing.get("tool", capability),
                        source="resource_detected",
                        ticket_id=audit_tid,
                        notes=f"Recurso detectado y confirmado por ticket #{audit_tid}",
                    )
                    capability_set_state(capability, CapabilityState.REGISTERED,
                                         ticket_id=audit_tid)
                except Exception as e:
                    self._log.warn("torre", f"Error promoviendo DETECTED→REGISTERED: {e}")
            else:
                # Ya registrado — actualizar ticket_id en el registro
                entry = capability_get_info(capability)
                if entry and not entry.get("ticket_id"):
                    try:
                        capability_set_state(capability, reg_state, ticket_id=audit_tid)
                    except Exception:
                        pass

            return {
                "ok": True,
                "resource_found": True,
                "state": reg_state,
                "audit_ticket_id": audit_tid,
                "tool": existing.get("tool", ""),
                "resource": existing.get("resource"),
                "message": existing.get("message"),
            }

        # ── 1. Look up skill definition ──
        from digos_lib.intent_classifier import get_skill_for_capability

        skill_def = get_skill_for_capability(capability)
        if skill_def is None:
            # No skill definition — just create an audit ticket
            result = self._engineer.create_capability_request(
                capability=capability,
                family=family,
                sub_intent=sub_intent,
                user_message=user_message,
                requester=requester,
            )
            return result

        # ── 2. Also create audit ticket in SystemEngineer for traceability ──
        audit_result = self._engineer.create_capability_request(
            capability=capability,
            family=family,
            sub_intent=sub_intent,
            user_message=user_message,
            requester=requester,
        )

        # ── 3. Initialize Factory if needed ──
        self._init_factory()

        if self._factory_manager is None:
            return {
                "ok": False,
                "ticket_id": audit_result.get("ticket_id"),
                "message": (
                    "Solicitud registrada pero la Factoría no está disponible. "
                    "Se creó ticket de auditoría. La capacidad se procesará "
                    "cuando la Factoría esté activa."
                ),
            }

        # ── 4. Route through FULL Factory pipeline ──
        try:
            # Pass LLM credentials so the Factory can generate tool code
            vault = CajaSeguraInfo.read_slot("principal")
            llm_api_key = vault.get("api_key", "") if vault else ""
            provider_id = vault.get("provider_id", "") if vault else ""
            llm_base_url = self._provider_base_url(provider_id) if provider_id else ""
            llm_model = vault.get("model", self._provider_default_model(provider_id)) if vault else ""

            factory_result = self._factory_manager.request_new_capability(
                capability_id=capability,
                family=family,
                description=skill_def.description,
                target_capabilities=skill_def.target_capabilities,
                target_limitations=skill_def.target_limitations,
                tool_name=skill_def.tool_name,
                requested_by=requester,
                llm_api_key=llm_api_key,
                llm_base_url=llm_base_url,
                llm_model=llm_model,
            )
        except Exception as e:

            return {
                "ok": False,
                "ticket_id": audit_result.get("ticket_id"),
                "message": f"Error en la Factoría: {e}",
            }

        if factory_result is None:
            return {
                "ok": False,
                "ticket_id": audit_result.get("ticket_id"),
                "message": "La Factoría no pudo procesar la solicitud.",
            }

        # ── 5. Enrich result with audit ticket info ──
        factory_result["audit_ticket_id"] = audit_result.get("ticket_id")

        # ── 6. Register the capability so the intent classifier
        #        recognizes it on subsequent requests ──
        audit_ticket_id = audit_result.get("ticket_id", "")
        if factory_result.get("ok"):
            try:
                register_capability(
                    capability, skill_def.tool_name,
                    source="factory_built",
                    ticket_id=audit_ticket_id,
                    notes=f"Construido por Factory (ticket #{audit_ticket_id})",
                )
                self._log.info("torre",
                    f"Capacidad '{capability}' registrada → tool '{skill_def.tool_name}' (#{audit_ticket_id})")
            except Exception as e:
                self._log.warn("torre", f"Error registrando capacidad: {e}")

            # ── 7. If generated_code was produced, save + register the tool ──
            generated_code = factory_result.get("generated_code", "")
            if generated_code:
                code_validated = factory_result.get("code_validated", False)
                try:
                    saved = self._save_and_register_generated_tool(
                        tool_name=skill_def.tool_name,
                        code=generated_code,
                        capability_id=capability,
                        code_validated=code_validated,
                    )
                    if saved:
                        factory_result["tool_registered"] = True
                        # Promover a TOOL_READY (tool real existe en DYNAMIC_TOOLS)
                        try:
                            capability_set_state(capability, CapabilityState.TOOL_READY,
                                                 ticket_id=audit_ticket_id,
                                                 notes="Tool generada registrada en DYNAMIC_TOOLS")
                        except Exception:
                            pass
                        self._log.info("torre",
                            f"Tool '{skill_def.tool_name}' registrada dinámicamente (#{audit_ticket_id})")
                except Exception as e:
                    self._log.warn("torre", f"Error registrando tool generada: {e}")

        return factory_result

    def _build_and_register_tool(
        self,
        module,
        tool_name: str,
        code: str,
        capability_id: str,
        description_suffix: str = "",
    ) -> bool:
        """Helper compartido: encuentra la función en el módulo,
        parsea parámetros de args.get(), construye el tool_def,
        y registra con add_dynamic_tool() + register_capability().

        Usado tanto por _save_and_register_generated_tool (al crear)
        como por _load_generated_tools (al cargar en reinicio).
        """
        import re

        # ── 1. Find the tool function ──
        func_name = f"_{tool_name}"
        func = getattr(module, func_name, None)
        if func is None:
            # Fallback: find any callable starting with _
            for name, obj in module.__dict__.items():
                if callable(obj) and name.startswith("_") and name != "__":
                    func = obj
                    break

        if func is None:
            self._log.warn("torre", f"No callable function found in '{tool_name}'")
            return False

        # ── 2. Parse args.get() patterns for parameters ──
        param_matches = re.findall(r'args\.get\("([^"]+)"', code)
        param_matches += re.findall(r"args\.get\('([^']+)'", code)
        param_names = sorted(set(param_matches))

        if param_names:
            properties = {
                p: {"type": "string", "description": f"Parameter: {p}"}
                for p in param_names
            }
        else:
            properties = {
                "_input": {
                    "type": "string",
                    "description": "Free-form input for this tool",
                },
            }

        # ── 3. Build OpenAI tool definition ──
        desc = f"{capability_id}: {description_suffix}".strip().rstrip(":")
        tool_def = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": desc or f"{capability_id}: dynamically generated by Factory",
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }

        # ── 4. Register tool + capability ──
        from digos_lib.agent_tools import (
            add_dynamic_tool, register_capability, capability_set_state,
            CapabilityState,
        )
        add_dynamic_tool(tool_name, tool_def, func)
        register_capability(capability_id, tool_name)
        # Promover a TOOL_READY — el tool real existe en DYNAMIC_TOOLS
        try:
            capability_set_state(
                capability_id, CapabilityState.TOOL_READY,
                notes="Dynamic tool registered in DYNAMIC_TOOLS"
            )
        except Exception:
            pass

        return True

    def _save_and_register_generated_tool(
        self,
        tool_name: str,
        code: str,
        capability_id: str,
        code_validated: bool = False,
    ) -> bool:
        """Saves generated tool code to disk, imports it dynamically,
        and registers it in the agent's DYNAMIC_TOOLS so the LLM can use it.

        The generated tool module is saved to DIGOS_DIR/generated_tools/<tool_name>.py.
        It is then imported and registered via add_dynamic_tool().

        Returns True if the tool was successfully registered.
        """
        if not code or not code.strip():
            return False

        import importlib.util

        try:
            # ── 1. Ensure generated_tools directory exists ──
            gen_dir = DIGOS_DIR / "generated_tools"
            gen_dir.mkdir(parents=True, exist_ok=True)

            # Create __init__.py if needed
            init_file = gen_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text("# Generated tools from DIGOS Factory\n", encoding='utf-8')

            # ── 2. Write the tool module ──
            tool_path = gen_dir / f"{tool_name}.py"
            tool_path.write_text(code, encoding='utf-8')
            self._log.info("torre", f"Tool '{tool_name}' saved → {tool_path} ({len(code)} bytes)")

            # ── 3. Import the module dynamically ──
            gen_dir_str = str(gen_dir)
            if gen_dir_str not in sys.path:
                sys.path.insert(0, gen_dir_str)

            spec = importlib.util.spec_from_file_location(
                f"digos_generated_{tool_name}", str(tool_path)
            )
            if spec is None or spec.loader is None:
                self._log.warn("torre", f"Could not create module spec for '{tool_name}'")
                return False

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # ── 4-7. Build tool def + register (shared helper) ──
            desc_suffix = f"dynamically generated by Factory (validated={code_validated})"
            if not self._build_and_register_tool(module, tool_name, code, capability_id, desc_suffix):
                return False

            # ── 8. Update manifest.json for persistence across restarts ──
            self._update_manifest(capability_id, tool_name, code_validated)

            # ── 9. Promote state: if code_validated, go to VALIDATED; else TOOL_READY ──
            from digos_lib.agent_tools import capability_set_state, CapabilityState, register_capability
            target_state = CapabilityState.VALIDATED if code_validated else CapabilityState.TOOL_READY
            try:
                capability_set_state(
                    capability_id, target_state,
                    notes=f"Tool saved & registered (code_validated={code_validated})"
                )
                # También asegurar que está en AVAILABLE_CAPABILITIES si no lo estaba
                register_capability(capability_id, tool_name, source="factory_built",
                                   notes=f"Saved tool with state={target_state}")
            except Exception:
                pass

            self._log.info("torre",
                f"Tool '{tool_name}' registered dynamically in agent (capability={capability_id}) [{target_state}]")
            return True

        except Exception as e:
            self._log.warn("torre", f"Error registering generated tool '{tool_name}': {e}")
            return False

    def _load_generated_tools(self):
        """Sexto Movimiento: escanea ~/.digos/generated_tools/ y carga
        todas las tools generadas por la Factory en sesiones anteriores.

        Para cada archivo .py:
          1. Importa dinámicamente el módulo
          2. Encuentra la función de tool (prefijo _)
          3. Parsea args.get() para extraer parámetros
          4. Construye tool definition OpenAI
          5. Registra con add_dynamic_tool()
          6. Registra capability con register_capability()

        También lee/carga manifest.json para persistir el mapeo
        capability → tool_name.
        """
        gen_dir: Path = DIGOS_DIR / "generated_tools"
        if not gen_dir.is_dir():
            return

        import importlib.util

        # ── 1. Cargar manifest.json si existe ──
        manifest_path = gen_dir / "manifest.json"
        manifest: dict = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                manifest = {}

        # ── 2. Encontrar todos los .py (excluyendo __init__) ──
        tool_files = sorted(
            f for f in gen_dir.iterdir()
            if f.suffix == ".py" and f.stem != "__init__"
        )

        if not tool_files:
            return

        loaded_count = 0
        for tool_path in tool_files:
            tool_name = tool_path.stem
            try:
                # ── 2a. Leer código fuente ──
                code = tool_path.read_text(encoding='utf-8')
                if not code.strip():
                    continue

                # ── 2b. Importar módulo dinámicamente ──
                gen_dir_str = str(gen_dir)
                if gen_dir_str not in sys.path:
                    sys.path.insert(0, gen_dir_str)

                spec = importlib.util.spec_from_file_location(
                    f"digos_generated_{tool_name}", str(tool_path)
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # ── 2c. Buscar capability_id en manifest + check code_validated ──
                capability_id = ""
                manifest_info: dict = {}
                for cap_id, info in manifest.items():
                    if info.get("tool_name") == tool_name:
                        capability_id = cap_id
                        manifest_info = info
                        break
                if not capability_id:
                    capability_id = tool_name  # fallback

                # Skip tools that were flagged as invalid in a previous session
                if manifest_info and not manifest_info.get("code_validated", True):
                    self._log.warn("torre",
                        f"Skipping '{tool_name}' — code_validated=False in manifest")
                    continue

                # ── 2d-2g. Build tool def + register (shared helper) ──
                if self._build_and_register_tool(module, tool_name, code, capability_id, "generated by Factory (persisted)"):
                    loaded_count += 1
                    self._log.info("torre",
                        f"Tool '{tool_name}' cargada de sesión anterior (capability={capability_id})")

            except Exception as e:
                self._log.warn("torre", f"Error cargando tool '{tool_name}': {e}")
                continue

        if loaded_count > 0:
            self._log.info("torre",
                f"🎻 Sexto Movimiento: {loaded_count} tools cargadas de generated_tools/")

    def _update_manifest(self, capability_id: str, tool_name: str, code_validated: bool = False):
        """Actualiza manifest.json con el mapeo capability → tool.

        El manifest permite que _load_generated_tools() sepa qué
        capability corresponde a cada tool al reiniciar.
        """
        import time as _time
        gen_dir = DIGOS_DIR / "generated_tools"
        manifest_path = gen_dir / "manifest.json"

        manifest: dict = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                manifest = {}

        manifest[capability_id] = {
            "tool_name": tool_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "code_validated": code_validated,
        }

        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

    def request_credential_disclosure(self, credential_type: str, requester: str = "agente") -> dict:
        """
        Si el usuario pide ver su token/API key, el Agente llama aquí,
        el Engineer crea un ticket de auditoría, lee la CajaSeguraInfo,
        y devuelve la credencial.

        credential_type: 'api_key' | 'gateway_token' | 'provider_id' | 'all'
        """
        return self._engineer.disclose_credential(credential_type, requester)

    def request_credential_rotation(self, credential_type: str, new_value: str, requester: str = "agente") -> dict:
        """
        El Centinela solo monitorea.

        1. Engineer valida la nueva key (test de conexión)
        2. Tower guarda en CajaSeguraInfo
        3. Cierra tickets relacionados del Centinela
        4. Resetea strikes del Centinela para monitoreo fresco

        credential_type: 'api_key' | 'gateway_token'
        """
        result = self._engineer.rotate_credential(credential_type, new_value, requester)

        # Reset Centinela strikes para el tipo rotado
        if result.get("ok"):
            strike_key = f"api_key:{self.state.get('agente', {}).get('provider_id', '')}" if credential_type == "api_key" else "telegram:bot"
            self._centinela.reset_strikes(strike_key)


            # Si es API key, reiniciar el agente con la nueva key
            if credential_type == "api_key" and self._agent is not None:
                vault = CajaSeguraInfo.read_slot("principal")
                if vault and vault.get("api_key"):
                    self._agent._api_key = vault["api_key"]
                    self._log.info("torre", "AIAgent reiniciado con nueva API key")

        return result

    def get_pending_credential_tickets(self) -> List[dict]:
        """Returns Centinela tickets that need user input (invalid API key/token).

        Estos tickets son los que el Centinela detectó y el Engineer diagnosticó.
        El Agente debe notificar al usuario para que proporcione una nueva credencial.
        """
        return self._engineer.get_credential_tickets_needing_user()

    def inject_credential_ticket_notification(self) -> str:
        """If there are pending Centinela tickets about credentials,
        builds a notification message for the Agent to present to the user.

        Returns empty string if no pending tickets."""
        tickets = self.get_pending_credential_tickets()
        if not tickets:
            return ""

        lines = ["⚠️  EL CENTINELA DETECTÓ PROBLEMAS CON TUS CREDENCIALES", ""]
        for t in tickets[:3]:  # máximo 3
            tid = t.get("id", "?")
            target = t.get("target", "")
            diagnosis = t.get("diagnosis", t.get("problem", ""))
            if "api_key" in target:
                lines.append(f"  🔑 Ticket #{tid}: Tu API key ha fallado.")
                lines.append(f"     {diagnosis}")
                lines.append(f"     Usa: 'cambia mi API key a [nueva key]' para rotarla.")
            elif "telegram" in target:
                lines.append(f"  📡 Ticket #{tid}: Tu token de Telegram ha fallado.")
                lines.append(f"     {diagnosis}")
                lines.append(f"     Usa: 'cambia mi token a [nuevo token]' para rotarlo.")
            lines.append("")
        lines.append("El System Engineer ya tiene los tickets. Proporciona la nueva credencial para resolverlos.")
        return "\n".join(lines)

    def _init_engine(self):
        """Inicializa el Engine (GPS + Self + Work) si hay destino configurado."""
        if self._engine is not None:
            return
        try:
            from digos_lib.engine import Engine
            rocket_path = str(DIGOS_DIR / "rocket")
            self._engine = Engine(rocket_path)
            self._log.info("torre", "Engine (GPS/SELF/WORK) inicializado")
        except Exception as e:
            self._log.info("torre", f"Engine no disponible: {e}")
            self._engine = None

    def _check_with_engine(self, text: str) -> dict:
        """Runs the message through the Engine to validate GPS.
        Returns dict with routing decision."""
        if self._engine is None:
            return {"action": "process_normally", "reason": "Engine no disponible"}

        try:
            decision = self._engine.process_message(text)
            return decision
        except Exception as e:

            return {"action": "process_normally", "reason": f"Error: {e}"}

    def _init_agent(self):
        """Inicializa el AIAgent con credenciales de CajaSeguraInfo."""
        if self._agent is not None:
            return

        vault = CajaSeguraInfo.read_slot("principal")
        if not vault:
            self._log.info("torre", "No hay slot principal — AIAgent no iniciado (esperando setup)")
            return

        api_key = vault.get("api_key", "")
        provider_id = vault.get("provider_id", "")
        model = vault.get("model", self._provider_default_model(provider_id))
        base_url = self._provider_base_url(provider_id)

        if not api_key:
            self._log.info("torre", "API key vacía en vault — AIAgent no iniciado (esperando setup)")
            return

        system_prompt = self._build_agent_prompt()

        from agent import AIAgent  # lazy import to avoid circular dep
        self._agent = AIAgent(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            progress_cb=self.emit_tool_progress,
            assistant_cb=self.emit_assistant_message,
            error_cb=self.emit_tool_error,
            approval_cb=self._approval_callback,
            disclosure_cb=self.request_credential_disclosure,
            rotation_cb=self.request_credential_rotation,
            creation_cb=self.request_internal_agent_creation,
            capability_cb=self.request_capability,
            master=self._master,  # 🎻 compartir instancia de MASTER — misma trayectoria
        )
        self._log.info("torre",
            f"AIAgent iniciado: {provider_id}/{model} → {base_url}")

        # ── SEXTO MOVIMIENTO: Persistencia de la Creación ──
        # Cargar tools generadas por la Factory en sesiones anteriores
        self._load_generated_tools()

        # 🎻 Pipeline Tools: registrar herramientas de conversación por ticket
        self._register_pipeline_tools()

    def _register_pipeline_tools(self):
        """Registra las tools del TicketConversationPipeline como dynamic tools.

        Estas herramientas permiten que el AIAgent:
        - pipeline_check() → estado general del pipeline
        - pipeline_read(ticket_id) → leer mensajes de un ticket
        - pipeline_respond(ticket_id, message) → responder en el pipeline
        - pipeline_resolve(ticket_id) → cerrar una conversación

        Las funciones reales están en core_pipeline.py y se comunican
        con el pipeline a través del module-level accessor.
        """
        from digos_lib.agent_tools import add_dynamic_tool
        from digos_lib.core_pipeline import (
            _pipeline_check, _pipeline_read,
            _pipeline_respond, _pipeline_resolve,
        )

        # 1. pipeline_check — sin args, devuelve resumen
        add_dynamic_tool(
            "pipeline_check",
            {
                "type": "function",
                "function": {
                    "name": "pipeline_check",
                    "description": "Revisa el estado del pipeline de conversación: "
                                   "conversaciones activas y mensajes no leídos "
                                   "del SystemEngineer. Sin argumentos.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            _pipeline_check,
        )
        self._log.info("torre", "🎻 Tool pipeline_check registrada")

        # 2. pipeline_read — args: ticket_id
        add_dynamic_tool(
            "pipeline_read",
            {
                "type": "function",
                "function": {
                    "name": "pipeline_read",
                    "description": "Lee el historial completo de mensajes del "
                                   "pipeline para un ticket específico. Marca "
                                   "automáticamente los mensajes como leídos.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {
                                "type": "string",
                                "description": "ID del ticket a consultar (ej: 20260528-0001)",
                            },
                        },
                        "required": ["ticket_id"],
                    },
                },
            },
            _pipeline_read,
        )
        self._log.info("torre", "🎻 Tool pipeline_read registrada")

        # 3. pipeline_respond — args: ticket_id, message
        add_dynamic_tool(
            "pipeline_respond",
            {
                "type": "function",
                "function": {
                    "name": "pipeline_respond",
                    "description": "Responde a un mensaje del SystemEngineer "
                                   "en el pipeline de un ticket. Si no existe "
                                   "conversación, la crea automáticamente.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {
                                "type": "string",
                                "description": "ID del ticket al que se responde",
                            },
                            "message": {
                                "type": "string",
                                "description": "Contenido de la respuesta",
                            },
                        },
                        "required": ["ticket_id", "message"],
                    },
                },
            },
            _pipeline_respond,
        )
        self._log.info("torre", "🎻 Tool pipeline_respond registrada")

        # 4. pipeline_resolve — args: ticket_id
        add_dynamic_tool(
            "pipeline_resolve",
            {
                "type": "function",
                "function": {
                    "name": "pipeline_resolve",
                    "description": "Cierra / marca como resuelta una conversación "
                                   "del pipeline. Úsala cuando ya no haya preguntas "
                                   "pendientes del Engineer o la información ya se "
                                   "haya proporcionado.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {
                                "type": "string",
                                "description": "ID del ticket cuya conversación se resuelve",
                            },
                        },
                        "required": ["ticket_id"],
                    },
                },
            },
            _pipeline_resolve,
        )
        self._log.info("torre", "🎻 Tool pipeline_resolve registrada")

        self._log.info("torre",
            "🎻 4 pipeline tools registradas dinámicamente en AVAILABLE_TOOLS")

    PROVIDER_DEFAULT_MODELS = {
        "1": "gpt-4o",
        "2": "claude-sonnet-4-20250514",
        "3": "gemini-2.0-flash",
        "4": "deepseek-chat",
        "5": "openrouter/auto",
        "6": "llama-3.3-70b-versatile",
        "7": "grok-2-latest",
        "8": "command-r-plus",
        "9": "mistral-large-latest",
        "10": "mistralai/Mixtral-8x22B-Instruct-v0.1",
        "11": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    }

    @staticmethod
    def _provider_default_model(provider_id: str) -> str:
        """Returns the default model for a provider."""
        return TorreDeControl.PROVIDER_DEFAULT_MODELS.get(provider_id, "gpt-4o")

    @staticmethod
    def _provider_base_url(provider_id: str) -> str:
        """Resuelve la URL base del API según el provider."""
        urls = {
            "1": "https://api.openai.com/v1",
            "2": "https://api.anthropic.com/v1",
            "3": "https://generativelanguage.googleapis.com/v1beta/openai",
            "4": "https://api.deepseek.com/v1",
            "5": "https://openrouter.ai/api/v1",
            "6": "https://api.groq.com/openai/v1",
            "7": "https://api.x.ai/v1",
            "8": "https://api.cohere.com/v1",
            "9": "https://api.mistral.ai/v1",
            "10": "https://api.together.xyz/v1",
            "11": "https://api.fireworks.ai/v1",
        }
        return urls.get(provider_id, "https://api.openai.com/v1")

    def _build_agent_prompt(self) -> str:
        """Builds the agent system prompt with DIGOS context."""
        lang = self.lang
        agente = self.state.get("agente", {})

        # ── Engine context: GPS destination + SELF + WORK ──
        engine_context = ""
        if self._engine is not None:
            try:
                engine_context = self._engine.get_context_for_agent()
            except Exception as e:
                self._log.warn("torre", f"Error getting engine context: {e}")

        # 🕰️ RelojInterno: contexto temporal
        clock_context = ""
        if hasattr(self._self_awareness, 'clock') and self._self_awareness.clock:
            try:
                clock_context = self._self_awareness.clock.get_context()
            except Exception as e:
                self._log.warn("torre", f"Error getting clock context: {e}")

        prompts = {
            "en": (
                "You are DIGOS, an intelligent agent system.\n"
                "You have access to tools. Use them when needed.\n"
                "Be concise, direct, and helpful.\n"
                "You don't have a personal name. You are DIGOS.\n"
                f"System: DIGOS v{VERSION}\n"
                f"Agent: {agente.get('name', 'Principal')}\n"
                f"Provider: {agente.get('provider_name', '?')}\n"
                "If someone directly asks about your creation or origin (who created you, "
                "who made you, how were you born, etc.): you may explain that you were "
                "created as part of the DIGOS system by a human working with artificial "
                "intelligence. Do not volunteer creator information unless explicitly asked.\n"
            ),
            "es": (
                "Eres DIGOS, un sistema de agente inteligente.\n"
                "Tienes acceso a herramientas. Úsalas cuando sea necesario.\n"
                "Sé conciso, directo y útil.\n"
                "No tienes nombre personal. Eres DIGOS.\n"
                f"Sistema: DIGOS v{VERSION}\n"
                f"Agente: {agente.get('name', 'Principal')}\n"
                f"Proveedor: {agente.get('provider_name', '?')}\n"
                "Si alguien pregunta tu nombre: no tienes nombre personal, eres DIGOS.\n"
                "Si alguien pregunta directamente sobre tu creación u origen (quién te creó, "
                "quién te hizo, cómo naciste, etc.): puedes explicar que fuiste creado como "
                "parte del sistema DIGOS por un humano trabajando con inteligencia artificial. "
                "No menciones información del creador a menos que te pregunten explícitamente.\n"
            ),
            "pt": (
                "Você é DIGOS, um sistema de agente inteligente.\n"
                "Você tem acesso a ferramentas. Use-as quando necessário.\n"
                "Seja conciso, direto e útil.\n"
                "Você não tem nome pessoal. Você é DIGOS.\n"
                f"Sistema: DIGOS v{VERSION}\n"
                f"Agente: {agente.get('name', 'Principal')}\n"
                f"Provedor: {agente.get('provider_name', '?')}\n"
                "Se alguém perguntar seu nome: você não tem nome pessoal, você é DIGOS.\n"
                "Se alguém perguntar diretamente sobre sua criação ou origem (quem te criou, "
                "quem te fez, como nasceu, etc.): você pode explicar que foi criado como "
                "parte do sistema DIGOS por um humano trabalhando com inteligência artificial. "
                "Não mencione informações do criador a menos que perguntem explicitamente.\n"
            ),
            "fr": (
                "Vous êtes DIGOS, un système d'agent intelligent.\n"
                "Vous avez accès à des outils. Utilisez-les si nécessaire.\n"
                "Soyez concis, direct et utile.\n"
                "Vous n'avez pas de nom personnel. Vous êtes DIGOS.\n"
                f"Système: DIGOS v{VERSION}\n"
                f"Agent: {agente.get('name', 'Principal')}\n"
                f"Fournisseur: {agente.get('provider_name', '?')}\n"
                "Si quelqu'un demande ton nom : tu n'as pas de nom personnel, tu es DIGOS.\n"
                "Si quelqu'un demande directement à propos de ta création ou origine (qui t'a créé, "
                "qui t'a fait, comment es-tu né, etc.): tu peux expliquer que tu as été créé "
                "dans le cadre du système DIGOS par un humain travaillant avec l'intelligence "
                "artificielle. Ne mentionne pas d'informations sur le créateur sauf demande explicite.\n"
            ),
            "de": (
                "Du bist DIGOS, ein intelligentes Agentensystem.\n"
                "Du hast Zugriff auf Werkzeuge. Nutze sie bei Bedarf.\n"
                "Sei prägnant, direkt und hilfreich.\n"
                "Du hast keinen persönlichen Namen. Du bist DIGOS.\n"
                f"System: DIGOS v{VERSION}\n"
                f"Agent: {agente.get('name', 'Principal')}\n"
                f"Anbieter: {agente.get('provider_name', '?')}\n"
                "Wenn jemand nach deinem Namen fragt: du hast keinen persönlichen Namen, du bist DIGOS.\n"
                "Wenn jemand direkt nach deiner Erschaffung oder Herkunft fragt (wer hat dich "
                "erschaffen, wer hat dich gemacht, wie bist du entstanden, etc.): du kannst "
                "erklären, dass du als Teil des DIGOS-Systems von einem Menschen in Zusammenarbeit "
                "mit künstlicher Intelligenz erschaffen wurdest. Erwähne keine Informationen "
                "über den Ersteller, es sei denn, du wirst ausdrücklich danach gefragt.\n"
            ),
        }
        base = prompts.get(lang, prompts["en"])
        if engine_context:
            base += f"\n{engine_context}"
        if clock_context:
            base += f"\n{clock_context}"

        # 🎻 Pipeline: mensajes pendientes del SystemEngineer
        pipeline_context = ""
        if hasattr(self, '_pipeline') and self._pipeline is not None:
            try:
                pipeline_context = self._pipeline.get_summary_for_agent("agente")
            except Exception as e:
                self._log.warn("torre", f"Error getting pipeline context: {e}")
        if pipeline_context:
            base += f"\n\n{pipeline_context}"

        return base

    # ── FASE 6: MESSAGE BUS ─────────────────────

    def _init_bus(self):
        """Initializes the Message Bus for multi-agent communication."""
        if self._bus is not None:
            return
        self._bus = MessageBus()
        self._bus.set_message_callback(
            lambda msg: self._log.info("bus", msg)
        )

        # Register principal agent
        agente = self.state.get("agente", {})
        name = agente.get("name", "principal").lower().replace(" ", "-")
        self._bus.register_agent(name, mode="collaborative")

        # Register adopted profiles
        profiles_dir = DIGOS_DIR / "profiles"
        if profiles_dir.is_dir():
            for p_dir in sorted(profiles_dir.iterdir()):
                if p_dir.is_dir() and not p_dir.name.startswith("."):
                    self._bus.register_agent(p_dir.name, mode="isolated")

        self._bus.start()
        count = len(self._bus.list_agents())


    def _register_agent_bus(self, name: str, mode: str = "isolated"):
        """Registers an agent in the Message Bus."""
        if self._bus is None:
            return
        self._bus.register_agent(name, mode=mode)
        self._log.info("torre", f"Agente '{name}' registrado en MessageBus ({mode})")


    def _agent_set_mode(self, name: str, mode: str) -> bool:
        """Changes an agent's mode in the bus (by user order)."""
        if self._bus is None:
            return False
        ok = self._bus.switch_mode(name, mode)
        if ok:
            icons = {"isolated": "🔒", "collaborative": "🤝"}
            icon = icons.get(mode, "❓")
            self._log.info("torre", f"Agente '{name}' cambiado a modo {mode}")
            print(f"  {icon} Agente '{name}' ahora en modo {mode}")
        return ok

    def _bus_status(self):
        """Muestra estado del Message Bus."""
        if self._bus is None:
            print("  📡 Message Bus: No iniciado")
            return
        self._bus.print_status()

    # ── FASE 7: AUTO-LAUNCH (launchd) ──────────

    LAUNCHD_LABEL = "com.digos.torredecontrol"
    LAUNCHD_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

    def _install_launchd(self) -> bool:
        """Installs DIGOS as a launchd service so it starts at login."""
        try:
            # ── macOS TCC check: launchd no puede acceder a Desktop/Documents/Downloads ──
            _project_path = Path(__file__).resolve().parent.parent
            _home = Path.home()
            _restricted_prefixes = [_home / d for d in ("Desktop", "Documents", "Downloads")]
            for _prefix in _restricted_prefixes:
                if _project_path == _prefix or _prefix in _project_path.parents:
                    self._log.error("torre",
                        f"❌ macOS TCC: launchd NO puede acceder a '{_project_path}' "
                        f"(está dentro de {_prefix.name}/). "
                        "Mueve el proyecto fuera de Desktop/Documents/Downloads, "
                        "ej: cp -r ~/Desktop/DIGOS ~/DIGOS")
                    print()
                    print(f"  ⛔ MACOS TCC: No se puede instalar auto-arranque.")
                    print(f"  El proyecto está dentro de '{_prefix.name}/', y macOS")
                    print(f"  bloquea el acceso a launchd desde esa ruta.")
                    print()
                    print(f"  Solución: mueve el proyecto fuera de {_prefix.name}/:")
                    print(f"    cp -r '{_project_path}' ~/DIGOS")
                    print(f"  Luego ejecuta DIGOS desde la nueva ubicación.")
                    print()
                    return False

            plist_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{self.LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{_project_path / 'digos.py'}</string>
        <string>--daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{DIGOS_DIR / 'logs' / 'launchd.stdout.log'}</string>
    <key>StandardErrorPath</key>
    <string>{DIGOS_DIR / 'logs' / 'launchd.stderr.log'}</string>
    <key>WorkingDirectory</key>
    <string>{DIGOS_DIR}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>'''
            self.LAUNCHD_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.LAUNCHD_PATH.write_text(plist_content)
            self.LAUNCHD_PATH.chmod(0o644)
            import subprocess
            subprocess.run(["launchctl", "load", str(self.LAUNCHD_PATH)],
                          capture_output=True, timeout=10)
            self._log.info("torre", "Launchd instalado — DIGOS arrancará al iniciar sesión")
            return True
        except Exception as e:
            self._log.error("torre", f"Error instalando launchd: {e}")
            return False

    def _uninstall_launchd(self) -> bool:
        """Desinstala el servicio launchd."""
        try:
            if self.LAUNCHD_PATH.exists():
                import subprocess
                subprocess.run(["launchctl", "unload", str(self.LAUNCHD_PATH)],
                              capture_output=True, timeout=10)
                self.LAUNCHD_PATH.unlink()
                self._log.info("torre", "Launchd desinstalado")
                return True
            self._log.info("torre", "Launchd no estaba instalado")
            return False
        except Exception as e:
            self._log.error("torre", f"Error desinstalando launchd: {e}")
            return False

    def _launchd_status(self) -> dict:
        """Verifica el estado del servicio launchd."""
        try:
            import subprocess
            # Verificar si el plist existe
            installed = self.LAUNCHD_PATH.exists()
            # Verificar si el proceso está realmente corriendo
            pid_result = subprocess.run(
                ["launchctl", "list", self.LAUNCHD_LABEL],
                capture_output=True, text=True, timeout=5,
            )
            running = False
            if pid_result.returncode == 0 and pid_result.stdout.strip():
                try:
                    parts = pid_result.stdout.strip().split("\t")
                    if len(parts) >= 3 and parts[0] != "-":
                        running = True
                except Exception as e:
                    self._log.warn("torre", f"Error parsing launchd PID output: {e}")
            return {"installed": installed, "running": running}
        except Exception as e:
            self._log.warn("torre", f"Error checking launchd status: {e}")
            return {"installed": self.LAUNCHD_PATH.exists(), "running": False}

    def _ensure_launchd(self):
        """In daemon mode, checks that launchd is configured.
        If not, asks the user if they want to install it."""
        if not self._daemon_mode:
            return
        status = self._launchd_status()
        if status.get("installed"):
            self._log.info("torre", "Launchd ya instalado — DIGOS vive 24/7")
            return
        print()
        print("  🚀 AUTO-LAUNCH")
        print("  ────────────────")
        print("  DIGOS puede iniciarse automáticamente al encender")
        print("  la computadora. Así nunca tienes que iniciarlo manualmente.")
        print()
        if self._confirm("  ¿Instalar auto-arranque?"):
            if self._install_launchd():
                print("  ✅ Auto-arranque instalado. DIGOS vivirá 24/7.")
            else:
                print("  ❌ Error instalando auto-arranque.")
        else:
            print("  Puedes instalarlo después con: digos --install")
        print()

    def print_launchd_status(self):
        """Muestra estado del servicio launchd."""
        status = self._launchd_status()
        print()
        print("  🚀 AUTO-LAUNCH")
        print("  ────────────────")
        if status["installed"]:
            icon = "🟢" if status["running"] else "🟡"
            print(f"  {icon} Servicio: {'Activo' if status['running'] else 'Instalado pero no corriendo'}")
        else:
            print("  ⚫ No instalado. Usa --install para activar.")
        print()

    def print_identity(self):
        """Shows DIGOS system identity."""
        ident = SYSTEM_IDENTITY
        print()
        print(f"  ╔══════════════════════════════════════╗")
        print(f"  ║     {ident['name']} — Identity           ║")
        print(f"  ╚══════════════════════════════════════╝")
        print()
        print(f"  Sistema:   {ident['full_name']}")
        print(f"  Versión:   {ident['version']}")
        print(f"  Creador:   {ident['creator']}")
        print(f"  Hecho por: {ident['created_by']}")
        print(f"  Nombre:    {'No tengo nombre personal' if ident['no_personal_name'] else 'DIGOS'}")
        print()
        print(f"  {'─' * 40}")
        print(f"  Preguntas frecuentes:")
        print(f"    ¿Quién eres?       → No tengo nombre personal. Soy DIGOS.")
        print(f"    ¿Quién te creó?    → {ident['creator']}, {ident['created_by']}.")
        print(f"    ¿Quién te hizo?    → {ident['creator']}, {ident['created_by']}.")
        print(f"    ¿Quién te fabricó? → {ident['creator']}, {ident['created_by']}.")
        print()

    def gateway_show_status(self):
        """Muestra el estado de todos los gateways."""
        if not self._gateways:
            print("\n  📡 GATEWAYS — Ninguno registrado\n")
            return
        print("\n  📡 GATEWAYS")
        print("  ────────────────")
        for gw_id, gw in self._gateways.items():
            icon = "✅" if gw.status == "running" else "⏹️" if gw.status == "stopped" else "🔴"
            print(f"  {icon} [{gw_id:10s}] {gw.name:20s} — {gw.status}")
        print()

    def _gateway_health_check(self):
        """Health check de todos los gateways registrados."""
        for gw_id, gw in self._gateways.items():
            try:
                ok = gw.health_check()
                if not ok and gw.status == "running":
                    gw.status = "error"
                    self._log.warn("torre", f"Gateway {gw_id} — health check falló")
            except Exception as e:
                self._log.warn("torre", f"Gateway {gw_id} — error en health check: {e}")

    def _poll_gateways(self):
        """Poll mensajes entrantes de gateways — CLI y Telegram.

        CLI: lee mensajes de texto del thread de stdin.
        Telegram: texto, voz, foto, audio, documento, video.
        - Voz/Audio → descarga → transcribe_audio → procesa como texto
        - Foto → descarga → view_image → procesa descripción como texto
        - Documento → si es imagen/audio → mismo tratamiento
        - Video → extrae audio → transcribe, extrae frames → visión, combina → agente
        """
        # ── CLI gateway: mensajes de texto desde stdin ──
        cli_gw = self._gateways.get("cli")
        if cli_gw and cli_gw.status == "running":
            for msg in cli_gw.get_updates():
                text = msg.get("text", "").strip()
                if text.lower() in ("exit", "quit", "salir"):
                    if self._log:
                        self._log.info("torre", "CLI: comando de salida recibido")
                    self._running = False
                    return
                if not text:
                    continue
                self._handle_cli_text(cli_gw, text)

        # ── Telegram gateway ──
        tg_gw = self._gateways.get("telegram")
        if not tg_gw or tg_gw.status != "running":
            return

        messages = tg_gw.get_updates()
        for msg in messages:
            chat_id = msg.get("chat_id", "")
            if not chat_id:
                continue

            msg_type = msg.get("type", "text")

            # Update active chat for transparency tracker
            self.set_active_chat(chat_id)

            # ── ASYNC ROUTE: encolar al executor, no bloquear el loop ──
            if self._executor is not None:
                if msg_type == "text":
                    with self._gateway_lock:
                        self._gateway_futures.append(
                            self._executor.submit(self._handle_telegram_text, tg_gw, chat_id, msg["text"])
                        )
                elif msg_type in ("voice", "audio"):
                    with self._gateway_lock:
                        self._gateway_futures.append(
                            self._executor.submit(self._handle_telegram_media, tg_gw, chat_id, msg, media_type="audio")
                        )
                elif msg_type == "photo":
                    with self._gateway_lock:
                        self._gateway_futures.append(
                            self._executor.submit(self._handle_telegram_media, tg_gw, chat_id, msg, media_type="image")
                        )
                elif msg_type == "document":
                    mime = msg.get("mime_type", "")
                    if mime.startswith("image/"):
                        with self._gateway_lock:
                            self._gateway_futures.append(
                                self._executor.submit(self._handle_telegram_media, tg_gw, chat_id, msg, media_type="image")
                            )
                    elif mime.startswith("audio/") or mime in ("application/ogg", "audio/ogg"):
                        with self._gateway_lock:
                            self._gateway_futures.append(
                                self._executor.submit(self._handle_telegram_media, tg_gw, chat_id, msg, media_type="audio")
                            )
                    else:
                        fname = msg.get("file_name", "archivo")
                        tg_gw.send_message(
                            f"📄 Recibí tu documento '{fname}', pero solo proceso "
                            f"imágenes y audio por ahora. ¡Estoy aprendiendo!",
                            chat_id=chat_id,
                        )
                elif msg_type in ("video", "video_note"):
                    with self._gateway_lock:
                        self._gateway_futures.append(
                            self._executor.submit(self._handle_telegram_video, tg_gw, chat_id, msg)
                        )
                else:
                    tg_gw.send_message(
                        "🤖 No pude procesar este tipo de mensaje. "
                        "¡Pero estoy aprendiendo!",
                        chat_id=chat_id,
                    )
            else:
                # Fallback sincrónico (si executor no está disponible)
                if msg_type == "text":
                    self._handle_telegram_text(tg_gw, chat_id, msg["text"])
                elif msg_type in ("voice", "audio"):
                    self._handle_telegram_media(tg_gw, chat_id, msg, media_type="audio")
                elif msg_type == "photo":
                    self._handle_telegram_media(tg_gw, chat_id, msg, media_type="image")
                elif msg_type == "document":
                    mime = msg.get("mime_type", "")
                    if mime.startswith("image/"):
                        self._handle_telegram_media(tg_gw, chat_id, msg, media_type="image")
                    elif mime.startswith("audio/") or mime in ("application/ogg", "audio/ogg"):
                        self._handle_telegram_media(tg_gw, chat_id, msg, media_type="audio")
                    else:
                        fname = msg.get("file_name", "archivo")
                        tg_gw.send_message(
                            f"📄 Recibí tu documento '{fname}', pero solo proceso "
                            f"imágenes y audio por ahora. ¡Estoy aprendiendo!",
                            chat_id=chat_id,
                        )
                elif msg_type in ("video", "video_note"):
                    self._handle_telegram_video(tg_gw, chat_id, msg)
                else:
                    tg_gw.send_message(
                        "🤖 No pude procesar este tipo de mensaje. "
                        "¡Pero estoy aprendiendo!",
                        chat_id=chat_id,
                    )

    def _cleanup_gateway_futures(self):
        """Limpia futures completados del gateway para evitar memory leak."""
        with self._gateway_lock:
            if not self._gateway_futures:
                return
            # Eliminar futures que ya terminaron (done o cancelled)
            self._gateway_futures = [
                f for f in self._gateway_futures
                if not f.done()
            ]

    # ── COMANDOS DE TORRE (capabilities, etc.) ──

    @staticmethod
    def _show_capabilities() -> str:
        """Muestra el CapabilityTruthRegistry completo."""
        try:
            from digos_lib.agent_tools import capability_summary
            return capability_summary()
        except ImportError:
            return "  📋 CapabilityTruthRegistry no disponible."

    def _show_factory_status(self) -> str:
        """Muestra el estado de la Factoría y los agentes internos."""
        lines = ["  🏭 ESTADO DE LA FACTORÍA", "  ──────────────────────────────"]

        if self._factory_manager is not None:
            lines.append("  Factoría: ✅ Inicializada")
        else:
            lines.append("  Factoría: ⏳ No disponible (factory.manager no importado)")
            lines.append("")
            lines.append("  Usa: 'crea un builder' o 'activa la factoría' para inicializarla.")
            return "\n".join(lines)

        if self._superior_agent is not None:
            lines.append("  SuperiorAgent: ✅ Activo")
        else:
            lines.append("  SuperiorAgent: ⏳ No disponible")

        # ── Internal agents ──
        agents = self.list_internal_agents()
        lines.append("")
        if not agents:
            lines.append("  🤖 Agentes internos: (ninguno creado aún)")
            lines.append("")
            lines.append("  Crea agentes con: 'crea un builder', 'crea 2 auditores', etc.")
        else:
            mode_icons = {"collaborative": "🤝", "isolated": "🔒"}
            status_icons = {"running": "✅", "idle": "💤", "error": "❌", "created": "🆕"}
            lines.append("  🤖 Agentes internos ({}):".format(len(agents)))
            for a in agents:
                name = a.get("name", "?")
                atype = a.get("type", "?")
                mode = a.get("mode", "?")
                status = a.get("status", "?")
                mission = a.get("mission", "")
                caps = a.get("capabilities", 0)
                mode_icon = mode_icons.get(mode, "⚙️")
                status_icon = status_icons.get(status, "❓")
                lines.append("    {} {} ({}) {} [{}]".format(status_icon, name, atype, mode_icon, mode))
                if mission:
                    lines.append("       🎯 {}".format(mission))
                lines.append("       🧰 {} herramienta(s)".format(caps))

        return "\n".join(lines)

    @staticmethod
    def _show_help() -> str:
        """Muestra la lista de comandos del sistema disponibles."""
        return (
            "  🆘 COMANDOS DEL SISTEMA\n"
            "  ──────────────────────────────\n"
            "  /capabilities   - CapabilityTruthRegistry (estados de capacidades)\n"
            "  /factory        - Estado de la Factoría y agentes internos\n"
            "  /status         - Estado general del sistema\n"
            "  /tickets        - Tickets del System Engineer (pipeline S&D)\n"
            "  /tickets open   - Solo tickets abiertos del pipeline\n"
            "  /tickets my     - Tus tickets como agente actual\n"
            "  /centinela      - Ejecuta un ciclo de checks del Centinela\n"
            "  /logs           - Muestra los logs del sistema\n"
            "  /help           - Esta ayuda\n"
            "  ──────────────────────────────\n"
            "  Los comandos funcionan sin necesidad de tener el agente activo."
        )

    def _show_status(self) -> str:
        """Captura la salida de status() y la devuelve como string."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.status()
        return buf.getvalue()

    def _show_tickets(self, status: str = None) -> str:
        """Captura la salida de engineer_show_tickets() y la devuelve como string.
        Si status='open', muestra solo tickets abiertos.
        """
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.engineer_show_tickets(status=status)
        return buf.getvalue()

    def _show_my_tickets(self) -> str:
        """Muestra los tickets del agente actual usando get_my_tickets()."""
        agent_name = self.state.get("agente", {}).get("name", "Agente Principal")
        tickets = self._engineer.get_my_tickets(requester=agent_name)
        if not tickets:
            return "\n  📋 No hay tickets para '%s'.\n" % agent_name
        lines = ["\n  📋 MIS TICKETS (%d)" % len(tickets)]
        lines.append("  ────────────────────────")
        for t in tickets:
            sev_icon = "🔴" if t["severity"] == "high" else "🟡" if t["severity"] == "medium" else "🟢"
            fs = t.get("flag_status", "?")
            flag_icon = {
                "inbox": "📥", "processing": "🔧", "testing": "🧪",
                "review": "🔍", "delivered": "✅",
            }.get(fs, "🚩")
            target = t.get("target", "?")
            status = t.get("status", "?")
            diag = (t.get("diagnosis", "") or t["problem"][:40])[:40]
            lines.append(f"  {sev_icon} {flag_icon} #{t['id']:>4} [{fs:>10}] [{status:>10}] {target:20s}  {diag}")
        lines.append("")
        return "\n".join(lines)

    def _show_centinela(self) -> str:
        """Captura la salida de centinela_run_once() y la devuelve como string."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.centinela_run_once()
        return buf.getvalue()

    def _show_logs(self) -> str:
        """Captura la salida de logs_show() y la devuelve como string."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.logs_show()
        return buf.getvalue()

    def _handle_cli_text(self, cli_gw, text: str):
        """Procesa un mensaje de texto del CLI gateway a través del agente.
        Sincrónico (el CLI no tiene executor).
        """
        text = text.strip()
        if not text:
            return

        # ── Comandos del sistema (sin agente) ──
        if text == "/capabilities":
            cli_gw.send_message(self._show_capabilities())
            return
        if text == "/factory":
            cli_gw.send_message(self._show_factory_status())
            return
        if text == "/help":
            cli_gw.send_message(self._show_help())
            return
        if text == "/status":
            cli_gw.send_message(self._show_status())
            return
        if text == "/tickets open":
            cli_gw.send_message(self._show_tickets(status="open"))
            return
        if text == "/tickets my":
            cli_gw.send_message(self._show_my_tickets())
            return
        if text == "/tickets":
            cli_gw.send_message(self._show_tickets())
            return
        if text == "/centinela":
            cli_gw.send_message(self._show_centinela())
            return
        if text == "/logs":
            cli_gw.send_message(self._show_logs())
            return

        if self._agent is None:
            cli_gw.send_message('⚠️ No estoy completamente configurado. Completa el setup con: digos')
            return

        # Crear ticket en Engineer para loguear la solicitud
        ticket_id = self._engineer.create_ticket(
            "usuario", "mensaje:cli",
            f"Solicitud: {text[:100]}", "low", source="cli"
        )

        # Inicializar Engine if not ready
        self._init_engine()

        # Consultar al Engine si el mensaje está alineado con el destino GPS
        decision = self._check_with_engine(text)
        action = decision.get("action", "process_normally")

        if action in ("safety_block", "safety_caution"):
            response = '⛔ No puedo procesar esa solicitud.'
            if self._log:
                self._log.warn("torre", f"Safety block (CLI): {decision.get('reason', '')}")
            cli_gw.send_message(response)
            self._engineer.close_ticket("usuario", ticket_id, f"Bloqueado: {decision.get('reason', '')}")
            return

        if action == "ask_user":
            question = decision.get("question",
                "Tu mensaje no parece alinearse con el objetivo actual. "
                '¿Quieres continuar con el destino actual o cambiarlo?')
            cli_gw.send_message(f'🤔 {question}')
            self._engineer.close_ticket("usuario", ticket_id, f"Pendiente de usuario: {question[:60]}")
            return

        # ── Abrir Activity Panel ──
        if self._activity_panel is not None:
            self._activity_panel.open()
            self._activity_panel.show("process", "🤔 Procesando solicitud...")

        # Procesar con el AIAgent
        self.emit_assistant_message('🤔 Analizando tu mensaje...')
        response = self._agent.process_message(text)

        # ── Cerrar Activity Panel antes de responder ──
        if self._activity_panel is not None:
            self._activity_panel.hide()

        cli_gw.send_message(response)
        self._engineer.close_ticket("usuario", ticket_id, "Respondido")

    def _handle_telegram_text(self, tg_gw, chat_id: str, text: str):
        """Procesa un mensaje de texto de Telegram a través del agente."""
        text = text.strip()
        if not text:
            return

        # ── Comandos del sistema ──
        if text == "/capabilities":
            tg_gw.send_message(
                self._show_capabilities(),
                chat_id=chat_id,
            )
            return
        if text == "/factory":
            tg_gw.send_message(
                self._show_factory_status(),
                chat_id=chat_id,
            )
            return
        if text == "/help":
            tg_gw.send_message(
                self._show_help(),
                chat_id=chat_id,
            )
            return
        if text == "/status":
            tg_gw.send_message(
                self._show_status(),
                chat_id=chat_id,
            )
            return
        if text == "/tickets open":
            tg_gw.send_message(
                self._show_tickets(status="open"),
                chat_id=chat_id,
            )
            return
        if text == "/tickets my":
            tg_gw.send_message(
                self._show_my_tickets(),
                chat_id=chat_id,
            )
            return
        if text == "/tickets":
            tg_gw.send_message(
                self._show_tickets(),
                chat_id=chat_id,
            )
            return
        if text == "/centinela":
            tg_gw.send_message(
                self._show_centinela(),
                chat_id=chat_id,
            )
            return
        if text == "/logs":
            tg_gw.send_message(
                self._show_logs(),
                chat_id=chat_id,
            )
            return

        if self._agent is None:
            tg_gw.send_message(
                "⚠️ Agente no disponible. Inicia el setup primero.",
                chat_id=chat_id,
            )
            return

        try:
            decision = self._check_with_engine(text)
            action = decision.get("action", "process_normally")

            if action in ("safety_block", "safety_reject"):
                tg_gw.send_message(
                    decision.get("reason", "⛔ Lo siento, no puedo procesar este mensaje."),
                    chat_id=chat_id,
                )
            elif action in ("ask_user", "new_destination"):
                tg_gw.send_message(
                    decision.get("question", decision.get("reason", "Necesito clarificar algo...")),
                    chat_id=chat_id,
                )
            else:
                tg_gw.send_chat_action(chat_id, "typing")
                if action == "process_normally_warn":
                    tg_gw.send_message(
                        f"⚠️  {decision.get('reason', '')}",
                        chat_id=chat_id,
                    )
                response = self._agent.process_message(text)
                tg_gw.send_message(response, chat_id=chat_id)
        except Exception as e:
            self._log.warn("torre", f"Error procesando mensaje de Telegram: {e}")
            tg_gw.send_message(
                "⚠️ Error procesando tu mensaje. Intenta de nuevo.",
                chat_id=chat_id,
            )

    def _handle_telegram_media(self, tg_gw, chat_id: str, msg: dict, media_type: str):
        """Descarga y procesa un mensaje multimedia de Telegram.

        Flujo:
          1. Notificar al usuario que estamos procesando
          2. Obtener file_path vía getFile
          3. Descargar el archivo
          4. Transcribir (audio) o describir (imagen) con la tool correspondiente
          5. Enviar transcripción/descripción + caption como input al agente
        """
        from digos_lib.agent_tools import _execute_tool

        file_id = msg.get("file_id", "")
        if not file_id:
            tg_gw.send_message("⚠️ No pude acceder al archivo.", chat_id=chat_id)
            return

        # ── 1. Notificar ──
        if media_type == "audio":
            duration = msg.get("duration", 0)
            dur_str = f" ({duration}s)" if duration else ""
            tg_gw.send_chat_action(chat_id, "typing")
            tg_gw.send_message(f"🎤 Procesando tu audio{dur_str}...", chat_id=chat_id)
            tg_gw.send_chat_action(chat_id, "typing")
        else:
            tg_gw.send_chat_action(chat_id, "typing")
            tg_gw.send_message("🖼️ Analizando tu imagen...", chat_id=chat_id)
            tg_gw.send_chat_action(chat_id, "typing")

        # ── 2. Obtener file_path ──
        file_info = tg_gw.get_file(file_id)
        if not file_info:
            tg_gw.send_message("⚠️ No pude obtener el archivo de Telegram.", chat_id=chat_id)
            return

        file_path = file_info.get("file_path", "")
        if not file_path:
            tg_gw.send_message("⚠️ El archivo no tiene ruta de descarga.", chat_id=chat_id)
            return

        # ── 3. Descargar ──
        # Ensure temp directory for media
        media_dir = DIGOS_DIR / "media_cache"

        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "bin"
        ts = str(int(time.time() * 1000))[-8:]
        local_path = media_dir / f"tg_{msg.get('message_id', '0')}_{ts}.{ext}"

        downloaded = tg_gw.download_file(file_path, str(local_path))
        if not downloaded or not local_path.exists():
            tg_gw.send_message("⚠️ Error al descargar el archivo.", chat_id=chat_id)
            return

        # ── 4. Procesar con la tool correspondiente ──
        result = None
        tool_error = None
        try:
            vault = CajaSeguraInfo.read_slot("principal")
            api_key = vault.get("api_key", "") if vault else ""
            provider_id = vault.get("provider_id", "") if vault else ""
            base_url = self._provider_base_url(provider_id)
            model = vault.get("model", self._provider_default_model(provider_id)) if vault else "gpt-4o"

            if media_type == "audio":
                result = _execute_tool(
                    "transcribe_audio",
                    {"path": str(local_path)},
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                )
            else:
                result = _execute_tool(
                    "view_image",
                    {"path": str(local_path), "question": "Describe esta imagen en detalle."},
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                )
        except Exception as e:
            self._log.warn("torre", f"Error procesando media: {e}")
            tool_error = f"⚠️ Error al procesar: {e}"
        finally:
            # Clean up temp file — always, even on error
            try:
                local_path.unlink()
            except Exception:
                pass

        if tool_error:
            tg_gw.send_message(tool_error, chat_id=chat_id)
            return

        if not result or result.startswith("Error:"):
            tg_gw.send_message(f"⚠️ No pude procesar el archivo: {result}", chat_id=chat_id)
            return

        # ── 5. Construir mensaje compuesto para el agente ──
        caption = msg.get("caption", "").strip()
        if media_type == "audio":
            combined = f"[Transcripción de audio recibido por Telegram]:\n\n{result}"
            if caption:
                combined += f"\n\n[Mensaje adjunto del usuario]: {caption}"
            prefix = "🎤 Transcripción:"
        else:
            combined = f"[Descripción de imagen recibida por Telegram]:\n\n{result}"
            if caption:
                combined += f"\n\n[Mensaje adjunto del usuario]: {caption}"
            prefix = "🖼️ Análisis:"

        # ── 6. Enviar resultado y procesar con el agente ──
        tg_gw.send_message(f"{prefix}\n\n{result[:500]}{'...' if len(result) > 500 else ''}", chat_id=chat_id)

        if self._agent is not None:
            try:
                tg_gw.send_chat_action(chat_id, "typing")
                response = self._agent.process_message(combined)
                tg_gw.send_message(response, chat_id=chat_id)
            except Exception as e:
                self._log.warn("torre", f"Error procesando media con agente: {e}")
                tg_gw.send_message(
                    "⚠️ Error al procesar tu mensaje con el agente.",
                    chat_id=chat_id,
                )

    # ── NOVENO MOVIMIENTO: VIDEO ─────────────────

    @staticmethod
    def _get_video_duration(video_path: str) -> float:
        """Obtiene la duración de un video usando ffprobe.

        Args:
            video_path: Ruta al archivo de video (debe existir)

        Returns duración en segundos, o 0 si no se pudo detectar.
        """
        import subprocess
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format",
                    video_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if probe.returncode != 0:
                return 0.0
            info = json.loads(probe.stdout)
            duration = float(info.get("format", {}).get("duration", 0))
            return duration if duration > 0 else 0.0
        except (subprocess.TimeoutExpired, FileNotFoundError,
                json.JSONDecodeError, KeyError, ValueError, Exception):
            return 0.0

    @staticmethod
    def _extract_audio_from_video(video_path: str, output_path: str) -> bool:
        """Extrae el audio de un video usando ffmpeg.

        Args:
            video_path: Ruta al archivo de video
            output_path: Ruta donde guardar el audio extraído (.mp3)

        Returns True si la extracción fue exitosa.
        """
        import subprocess
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-vn",  # no video
                    "-acodec", "libmp3lame",
                    "-q:a", "2",
                    output_path,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return False
            return Path(output_path).exists() and Path(output_path).stat().st_size > 0
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False

    @staticmethod
    def _extract_key_frames(video_path: str, output_dir: str, max_frames: int = 4) -> list:
        """Extrae frames clave de un video usando ffmpeg.

        Toma frames en 25%, 50%, 75%, 90% de la duración total.

        Args:
            video_path: Ruta al archivo de video
            output_dir: Directorio donde guardar los frames
            max_frames: Número máximo de frames a extraer (default 4)

        Returns lista de rutas a los frames extraídos.
        """
        import subprocess

        try:
            # ── Obtener duración del video ──
            duration = TorreDeControl._get_video_duration(video_path)
            if duration <= 0:
                return []

            # ── Calcular timestamps ──
            # Para videos cortos (< 10s), tomar 2 frames
            # Para videos largos, tomar hasta max_frames
            if duration < 10:
                percentages = [0.25, 0.75]
            elif duration < 60:
                percentages = [0.25, 0.50, 0.75]
            else:
                percentages = [0.12, 0.30, 0.50, 0.70, 0.90]

            percentages = percentages[:max_frames]

            Path(output_dir).mkdir(parents=True, exist_ok=True)
            frames = []

            for i, pct in enumerate(percentages):
                ts = duration * pct
                ts_str = f"{int(ts // 3600):02d}:{int((ts % 3600) // 60):02d}:{ts % 60:06.3f}"
                out_path = Path(output_dir) / f"frame_{i + 1:02d}.jpg"

                result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-ss", ts_str,
                        "-i", video_path,
                        "-frames:v", "1",
                        "-q:v", "3",
                        str(out_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
                    frames.append(str(out_path))

            return frames

        except (subprocess.TimeoutExpired, FileNotFoundError,
                json.JSONDecodeError, KeyError, ValueError, Exception):
            return []

    def _handle_telegram_video(self, tg_gw, chat_id: str, msg: dict):
        """Procesa un video de Telegram: extrae audio → transcribe,
        extrae frames clave → visión, combina todo para el agente.

        Flujo completo del Noveno Movimiento:
          1. Notificar al usuario
          2. Descargar el video
          3. Extraer audio → transcribir con Whisper
          4. Extraer frames clave → analizar cada uno con visión
          5. Combinar transcripción + descripciones + caption
          6. Enviar al agente para respuesta
        """
        from digos_lib.agent_tools import _execute_tool

        file_id = msg.get("file_id", "")
        if not file_id:
            tg_gw.send_message("⚠️ No pude acceder al video.", chat_id=chat_id)
            return

        duration = msg.get("duration", 0)
        file_size = msg.get("file_size", 0)

        # ── 0. Size check BEFORE downloading ──
        MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 MB
        if file_size > MAX_VIDEO_SIZE:
            size_mb = file_size / 1024 / 1024
            tg_gw.send_message(
                f"⚠️ El video es demasiado grande ({size_mb:.1f}MB).\n"
                f"   Límite máximo: 50MB.\n"
                f"   Envía un video más corto, comprimido, o descríbeme qué contiene.",
                chat_id=chat_id,
            )
            self._log.info("torre",
                f"Video rechazado por tamaño: {size_mb:.1f}MB > 50MB (chat {chat_id})")
            return

        dur_str = f" ({duration}s)" if duration else ""
        size_mb = f" ({file_size / 1024 / 1024:.1f}MB)" if file_size else ""

        # ── 1. Notificar ──
        tg_gw.send_chat_action(chat_id, "typing")
        tg_gw.send_message(
            f"🎬 Procesando tu video{dur_str}{size_mb}...\n"
            f"   Extraeré el audio, lo transcribiré, y analizaré los frames clave.",
            chat_id=chat_id,
        )

        # ── 2. Descargar video ──
        file_info = tg_gw.get_file(file_id)
        if not file_info:
            tg_gw.send_message("⚠️ No pude obtener el video de Telegram.", chat_id=chat_id)
            return

        file_path = file_info.get("file_path", "")
        if not file_path:
            tg_gw.send_message("⚠️ El video no tiene ruta de descarga.", chat_id=chat_id)
            return

        media_dir = DIGOS_DIR / "media_cache"
        ext = file_path.rsplit(".", 1)[-1] if "." in file_path else "mp4"
        ts = str(int(time.time() * 1000))[-8:]
        msg_id = msg.get("message_id", "0")
        video_path = media_dir / f"tg_video_{msg_id}_{ts}.{ext}"

        downloaded = tg_gw.download_file(file_path, str(video_path))
        if not downloaded or not video_path.exists():
            tg_gw.send_message("⚠️ Error al descargar el video (posiblemente demasiado grande).",
                               chat_id=chat_id)
            return

        # ── Para cleanup al final ──
        temp_files = [video_path]
        audio_path = None
        frame_paths = []

        try:
            # ── 3. Extraer y transcribir audio ──
            tg_gw.send_chat_action(chat_id, "typing")
            tg_gw.send_message("🎤 Extrayendo y transcribiendo audio...", chat_id=chat_id)

            audio_path = media_dir / f"tg_audio_{msg_id}_{ts}.mp3"
            temp_files.append(audio_path)

            transcription = ""
            if self._extract_audio_from_video(str(video_path), str(audio_path)):
                vault = CajaSeguraInfo.read_slot("principal")
                api_key = vault.get("api_key", "") if vault else ""
                provider_id = vault.get("provider_id", "") if vault else ""
                base_url = self._provider_base_url(provider_id)
                model = vault.get("model", self._provider_default_model(provider_id)) if vault else "gpt-4o"

                result = _execute_tool(
                    "transcribe_audio",
                    {"path": str(audio_path)},
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                )
                if result and not result.startswith("Error:"):
                    transcription = result
            else:
                self._log.warn("torre", f"No se pudo extraer audio del video {msg_id}")

            # ── 4. Extraer y analizar frames clave ──
            tg_gw.send_chat_action(chat_id, "typing")

            # Determinar cuántos frames extraer según duración real (ffprobe)
            actual_duration = self._get_video_duration(str(video_path))
            if actual_duration > 0:
                if actual_duration < 5:
                    max_frames = 1
                elif actual_duration < 15:
                    max_frames = 2
                elif actual_duration < 60:
                    max_frames = 3
                elif actual_duration < 300:
                    max_frames = 4
                else:
                    max_frames = 5
            else:
                max_frames = 3  # fallback si ffprobe falla

            frame_dir = media_dir / f"tg_frames_{msg_id}_{ts}"
            frame_paths = self._extract_key_frames(str(video_path), str(frame_dir), max_frames=max_frames)

            frame_descriptions = []
            if frame_paths:
                n_frames = len(frame_paths)
                tg_gw.send_message(
                    f"🖼️ Analizando {n_frames} frame(s) clave del video...",
                    chat_id=chat_id,
                )

                vault = CajaSeguraInfo.read_slot("principal")
                api_key = vault.get("api_key", "") if vault else ""
                provider_id = vault.get("provider_id", "") if vault else ""
                base_url = self._provider_base_url(provider_id)
                model = vault.get("model", self._provider_default_model(provider_id)) if vault else "gpt-4o"

                for i, fp in enumerate(frame_paths):
                    question = (
                        f"Este es el frame {i + 1} de {n_frames} de un video. "
                        f"Describe qué ves en esta escena: personas, objetos, texto, "
                        f"acciones, ubicación, y cualquier detalle relevante."
                    )
                    result = _execute_tool(
                        "view_image",
                        {"path": fp, "question": question},
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                    )
                    if result and not result.startswith("Error:"):
                        # Clean the prefix added by view_image
                        clean = result.replace("🖼️  Análisis de imagen:\n\n", "")
                        frame_descriptions.append(f"[Frame {i + 1}/{n_frames}]: {clean}")
            else:
                self._log.warn("torre", f"No se pudieron extraer frames del video {msg_id}")

            # ── 5. Combinar todo ──
            combined_parts = []

            if transcription:
                combined_parts.append(
                    f"[Transcripción de audio del video recibido por Telegram]:\n\n{transcription}"
                )

            if frame_descriptions:
                frames_text = "\n\n".join(frame_descriptions)
                combined_parts.append(
                    f"[Análisis visual de {len(frame_descriptions)} frame(s) clave del video]:\n\n{frames_text}"
                )

            caption = msg.get("caption", "").strip()
            if caption:
                combined_parts.append(f"[Mensaje adjunto del usuario]: {caption}")

            if not combined_parts:
                tg_gw.send_message(
                    "⚠️ No pude extraer audio ni frames del video. "
                    "¿Puedes describir lo que contiene?",
                    chat_id=chat_id,
                )
                return

            combined = "\n\n".join(combined_parts)

            # ── 6. Enviar preview y procesar con el agente ──
            # Build a summary preview
            preview_lines = ["🎬 Resumen del video:"]
            if transcription:
                preview = transcription[:300]
                preview_lines.append(f"\n📝 Transcripción:\n{preview}{'...' if len(transcription) > 300 else ''}")
            if frame_descriptions:
                preview_lines.append(f"\n🖼️ {len(frame_descriptions)} frame(s) analizados con visión.")

            tg_gw.send_message("\n".join(preview_lines), chat_id=chat_id)

            # Process with agent
            if self._agent is not None:
                tg_gw.send_chat_action(chat_id, "typing")
                response = self._agent.process_message(combined)
                tg_gw.send_message(response, chat_id=chat_id)
            else:
                tg_gw.send_message(
                    "⚠️ Agente no disponible para procesar el video.",
                    chat_id=chat_id,
                )

        except Exception as e:
            self._log.warn("torre", f"Error procesando video: {e}")
            tg_gw.send_message(
                f"⚠️ Error al procesar el video: {e}",
                chat_id=chat_id,
            )
        finally:
            # ── Cleanup todos los archivos temporales ──
            for fp in temp_files:
                try:
                    if fp.exists():
                        fp.unlink()
                except Exception:
                    pass
            # Cleanup frame directory
            for fp in frame_paths:
                try:
                    Path(fp).unlink()
                except Exception:
                    pass
            if frame_paths:
                try:
                    frame_dir = Path(frame_paths[0]).parent
                    frame_dir.rmdir()
                except Exception:
                    pass

    # ── END NOVENO MOVIMIENTO ─────────────────
