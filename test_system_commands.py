#!/usr/bin/env python3
"""
test_system_commands.py — Prueba todos los comandos del sistema
de la TorreDeControl a través de _handle_cli_text().

Uso: python3 test_system_commands.py
"""

import sys
import os
import tempfile
from pathlib import Path

# Asegurar que podemos importar los módulos del proyecto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Aislar estado local: este script no debe leer tickets reales ni residuos de
# otras baterías de prueba en ~/.digos.
TEST_HOME = Path(tempfile.mkdtemp(prefix="digos_system_commands_"))
os.environ["HOME"] = str(TEST_HOME)
(TEST_HOME / ".digos" / "profiles").mkdir(parents=True, exist_ok=True)
(TEST_HOME / ".digos" / "logs").mkdir(parents=True, exist_ok=True)

from digos_lib.core_tower import TorreDeControl
from digos_lib.core_gateways import GatewayCLI


class TestCLI:
    """Simula el GatewayCLI pero captura mensajes en lugar de imprimirlos."""

    def __init__(self):
        self.messages = []
        self.last_message = ""

    def send_message(self, msg: str, **kw):
        self.messages.append(msg)
        self.last_message = msg
        print(f"  [OUTPUT]\n{msg}\n  [/OUTPUT]")


class TestTG:
    """Simula GatewayTelegram pero captura mensajes en lugar de enviarlos."""

    def __init__(self):
        self.messages = []
        self.last_message = ""
        self.last_chat_id = ""

    def send_message(self, msg: str, chat_id: str = "", **kw):
        self.messages.append((chat_id, msg))
        self.last_message = msg
        self.last_chat_id = chat_id
        print(f"  [TG→{chat_id}]\n{msg}\n  [/TG]")

    def send_chat_action(self, chat_id: str, action: str = "typing"):
        pass  # no-op para la prueba


def test_command(tower, gw, command: str, expected_keywords: list,
                 handler: str = "cli", chat_id: str = "test_chat") -> bool:
    """Testea un comando vía CLI o Telegram y verifica keywords."""
    print(f"\n{'='*60}")
    print(f"  TEST ({handler.upper()}): {command}")
    print(f"{'='*60}")

    gw.messages = []
    gw.last_message = ""

    # Ejecutar el handler correspondiente
    if handler == "cli":
        tower._handle_cli_text(gw, command)
    elif handler == "tg":
        tower._handle_telegram_text(gw, chat_id, command)

    output = gw.last_message
    if not output:
        print(f"  ❌ No se recibió respuesta para {command}")
        return False

    # Verificar palabras clave esperadas
    all_ok = True
    for keyword in expected_keywords:
        if keyword.lower() in output.lower():
            print(f"  ✅ Contiene: '{keyword}'")
        else:
            print(f"  ❌ Falta:    '{keyword}'")
            all_ok = False

    if all_ok:
        print(f"\n  ✅ {command} — PASÓ")
    else:
        print(f"\n  ❌ {command} — FALLÓ (faltan keywords)")

    return all_ok


# Helper for this script; prevent pytest from collecting it as a test function.
test_command.__test__ = False


def main():
    print("🏗️  INICIALIZANDO TORRE DE CONTROL...")
    print("═" * 60)

    tower = TorreDeControl(daemon_mode=False)
    cli_gw = TestCLI()
    tg_gw = TestTG()

    print("✅ TorreDeControl inicializada")
    print()

    # ── Definición de casos de prueba ──
    # Cada caso: (handler, comando, [keywords])
    test_cases = [
        # CLI tests
        ("cli", "/capabilities", ["CAPABILITY", "REGISTRY", "registered"]),
        ("cli", "/factory", ["FACTORÍA", "MANAGER", "No disponible"]),
        ("cli", "/status", ["ESTADO", "DIGOS", "TORRE", "Self-Awareness", "Centinela", "Engineer"]),
        ("cli", "/tickets", ["No hay tickets"]),
        ("cli", "/centinela", ["CENTINELA", "checks"]),
        ("cli", "/logs", ["LOGS"]),
        ("cli", "/help", ["COMANDOS", "SISTEMA", "/capabilities", "/factory",
                          "/status", "/tickets", "/centinela", "/logs", "/help"]),
        ("cli", "/invalido", ["configurado"]),
        # Telegram tests
        ("tg", "/capabilities", ["CAPABILITY", "REGISTRY", "registered"]),
        ("tg", "/factory", ["FACTORÍA", "MANAGER", "No disponible"]),
        ("tg", "/status", ["ESTADO", "DIGOS", "TORRE", "Self-Awareness", "Centinela", "Engineer"]),
        ("tg", "/tickets", ["No hay tickets"]),
        ("tg", "/centinela", ["CENTINELA", "checks"]),
        ("tg", "/logs", ["LOGS"]),
        ("tg", "/help", ["COMANDOS", "SISTEMA", "/capabilities", "/factory",
                          "/status", "/tickets", "/centinela", "/logs", "/help"]),
        ("tg", "/invalido", ["Agente no disponible"]),
    ]

    results = []
    for handler, cmd, keywords in test_cases:
        gw = cli_gw if handler == "cli" else tg_gw
        results.append(test_command(tower, gw, cmd, keywords, handler=handler))

    # Resumen
    print(f"\n{'='*60}")
    print("  RESUMEN DE RESULTADOS")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r)
    failed = sum(1 for r in results if not r)
    cli_passed = sum(1 for i, r in enumerate(results) if r and i < 8)
    cli_total = 8
    tg_passed = sum(1 for i, r in enumerate(results) if r and i >= 8)
    tg_total = 8
    print(f"  🖥️  CLI:      {cli_passed}/{cli_total} pasaron")
    print(f"  🤖 Telegram: {tg_passed}/{tg_total} pasaron")
    print(f"  ────────────────────")
    print(f"  ✅ Total:    {passed}/{len(results)} pasaron")

    if failed > 0:
        print("\n  ⚠️  Hubo fallos. Revisa los detalles arriba.")
        sys.exit(1)
    else:
        print("\n  🎉 ¡Todos los comandos funcionan en ambos handlers!")


if __name__ == "__main__":
    main()
