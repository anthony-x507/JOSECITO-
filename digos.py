#!/usr/bin/env python3
"""
DIGOS v0.3 — Phase 5: Adoption + Transparency
==============================================
Control Tower: born first, guides the user from download
to the handoff to the Principal Agent.

Phase 4: Transparency layer — Real-time ToolProgressTracker.
Phase 4b: AIAgent with LLM and tool calling.
Phase 5: Adoption Engine — migrates from Hermes and Open Cloud.
System Engineer (tickets + diagnostics), Log Keeper (rotating logs),
Self-Awareness Core (identity + state machine).

All constants live in digos_lib/constants.py — single source of truth.
"""

# ─────────────────────────────────────────────
# CONSTANTS — from single source of truth
# ─────────────────────────────────────────────

from digos_lib.constants import (
    VERSION, DIGOS_DIR, STATE_FILE, KEY_FILE, LOG_DIR,
    STRIKES_FILE, SELF_FILE, VAULT_FILE,
    LANGUAGES, PROVIDERS, GATEWAYS,
    SYSTEM_IDENTITY, IDENTITY_RESPONSES,
    CENTINELA_INTERVAL, STRIKE_LIMIT,
    SYSTEM_NAME, SYSTEM_VERSION,
)
from digos_lib.provider_api import _provider_api_request

# Phase 4: Transparency
from transparency import ToolProgressTracker

# Phase 4b: AIAgent with tool calling
from agent import AIAgent

# Phase 5: Adoption Engine — migrate from Hermes/OpenClaw
from adoption import AdoptionEngine, TransformationEngine

# Phase 5b: Security Guardrail — Safe Box + Prompt Injection
from security import CajaSegura as SecurityCaja, CajaSeguraReport as SecurityReport

# Phase 6: Message Bus — Multi-Agent Communication
from bus import MessageBus

# ─────────────────────────────────────────────
# MODULAR IMPORTS — Classes extracted to digos_lib/
# ─────────────────────────────────────────────

from digos_lib.core_models import AgenteRecord, DigosState, Ticket
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.core_log import LogKeeper
from digos_lib.core_centinela import Centinela
from digos_lib.core_engineer import SystemEngineer
from digos_lib.core_self import SelfAwarenessCore
from digos_lib.core_tower import TorreDeControl
from digos_lib.core_gateways import BaseGateway, GatewayCLI, GatewayTelegram

# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="DIGOS — Intelligent Agent System")
    parser.add_argument("--status", action="store_true", help="Mostrar estado completo del sistema")
    parser.add_argument("--version", action="store_true", help="Mostrar versión")
    parser.add_argument("--daemon", action="store_true", help="Iniciar en modo daemon 24/7")

# Comandos de TORRE DE CONTROL
    parser.add_argument("--centinela", action="store_true", help="Ejecutar un ciclo de checks del Centinela")
    parser.add_argument("--tickets", action="store_true", help="Mostrar tickets del System Engineer")
    parser.add_argument("--open-tickets", action="store_true", help="Mostrar solo tickets abiertos")
    parser.add_argument("--logs", action="store_true", help="Mostrar logs recientes")
    parser.add_argument("--log-level", type=str, default=None, choices=["INFO", "WARN", "ERROR"],
                        help="Filtrar logs por nivel")
    parser.add_argument("--log-source", type=str, default=None,
                        help="Filtrar logs por fuente (tower, centinela, engineer, self)")
    parser.add_argument("--log-limit", type=int, default=20,
                        help="Número de entradas de log a mostrar (default: 20)")

    # GATEWAY commands (Phase 3)
    parser.add_argument("--gateways", action="store_true", help="Mostrar estado de gateways")
    parser.add_argument("--gateway", type=str, default=None,
                        help="Iniciar un gateway específico (cli, telegram)")

    # AUTO-LAUNCH commands (Phase 7)
    parser.add_argument("--install", action="store_true", help="Instalar auto-arranque (launchd)")
    parser.add_argument("--uninstall", action="store_true", help="Desinstalar auto-arranque")
    parser.add_argument("--launchd-status", action="store_true", help="Estado del servicio launchd")

    # Identidad del sistema
    parser.add_argument("--identity", action="store_true", help="Mostrar identidad del sistema")

    # 🕰️ RelojInterno
    parser.add_argument("--clock", action="store_true", help="Mostrar estado del RelojInterno")

    args = parser.parse_args()

    if args.version:
        print(f"DIGOS v{VERSION}")
        return

    tower = TorreDeControl(daemon_mode=args.daemon)

    if args.gateways or args.gateway:
        tower._init_gateways()
        if args.gateways:
            tower.gateway_show_status()
            return
        if args.gateway == "telegram":
            import os as _os
            tg_token = _os.environ.get("TELEGRAM_BOT_TOKEN", "")
            if not tg_token:
                import getpass as _gp
                print("  🤖 Token de Telegram (no se mostrará mientras escribes):")
                tg_token = _gp.getpass("  → ")
            gw = GatewayTelegram(tg_token)
            gw.set_logger(tower._log)
            tower.register_gateway(gw)
            gw.start()
            return
        if args.gateway == "cli":
            gw = GatewayCLI()
            gw.set_logger(tower._log)
            tower.register_gateway(gw)
            print("  Iniciando Gateway CLI...")
            gw.start()
            return
        print(f"  Gateway '{args.gateway}' no reconocido. Usa: cli, telegram")
        return

    if args.status:
        tower.status()
        tower.print_launchd_status()
        return

    if args.install:
        ok = tower._install_launchd()
        print(f"  {'✅' if ok else '❌'} Auto-arranque {'instalado' if ok else 'falló'}")
        return

    if args.uninstall:
        ok = tower._uninstall_launchd()
        print(f"  {'✅' if ok else '⚠️'} Auto-arranque {'desinstalado' if ok else 'no estaba instalado'}")
        return

    if args.launchd_status:
        tower.print_launchd_status()
        return

    if args.clock:
        if hasattr(tower._self_awareness, 'clock') and tower._self_awareness.clock:
            tower._self_awareness.clock.print_status()
        else:
            print("  🕰️ RelojInterno no disponible")
        return

    if args.identity:
        tower.print_identity()
        return

    if args.centinela:
        tower.centinela_run_once()
        return

    if args.tickets:
        tower.engineer_show_tickets()
        return

    if args.open_tickets:
        tower.engineer_show_tickets(status="open")
        return

    if args.logs:
        tower.logs_show(level=args.log_level, source=args.log_source, limit=args.log_limit)
        return

    # Modo normal: run onboarding o handoff
    tower.run()


if __name__ == "__main__":
    main()
