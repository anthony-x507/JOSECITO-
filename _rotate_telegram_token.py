#!/usr/bin/env python3
"""Rota el token de Telegram en CajaSeguraInfo usando SystemEngineer."""
import sys, os, getpass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from digos_lib.core_log import LogKeeper
from digos_lib.core_engineer import SystemEngineer
from digos_lib.core_vault import CajaSeguraInfo

print("  🔄 Rotación de token de Telegram")
print("  ─────────────────────────────────")
print()

# Pedir token sin mostrarlo
token = getpass.getpass("  Pega tu token de @BotFather (no se muestra): ").strip()

if not token:
    print("  ❌ Token vacío. Cancelando.")
    sys.exit(1)

print(f"  Validando token contra Telegram...")
print()

# Usar SystemEngineer.rotate_credential para validar y guardar
log = LogKeeper()
eng = SystemEngineer(log)

result = eng.rotate_credential("gateway_token", token, requester="usuario")

if result["ok"]:
    print(f"  ✅ Token rotado exitosamente!")
    print(f"  🆔 Ticket: #{result['ticket_id']}")
    print(f"  📦 Cerrados relacionados: {result.get('closed_related', 0)}")
    print()
    print("  ℹ️  Los strikes del Centinela se resetearán en el próximo ciclo.")
else:
    print(f"  ❌ Rotación fallida: {result['message']}")
    sys.exit(1)
