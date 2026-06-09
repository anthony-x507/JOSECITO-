#!/usr/bin/env python3
"""
MASTER entry point.

Usage:
  python3 digos.py                    Interactive onboarding
  python3 digos.py --daemon           Run as background daemon (cyclic)
  python3 digos.py --status           Show system status
  python3 digos.py --check            Verify vault credentials
  python3 digos.py --help             Show this help
"""
import argparse
import sys
import os
from pathlib import Path

# Ensure we can find modules
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(
        description="MASTER — Multi-Agent Orchestration System by ABACO Team",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--daemon", action="store_true",
                        help="Run as cyclic daemon (Tower wakes every 3h)")
    parser.add_argument("--status", action="store_true", help="Show system status")
    parser.add_argument("--check", action="store_true", help="Verify vault credentials")
    parser.add_argument("--version", action="store_true", help="Show version")

    args = parser.parse_args()

    if args.version:
        from digos_lib.constants import VERSION
        print(f"MASTER v{VERSION}")
        return 0

    if args.status:
        show_status()
        return 0

    if args.check:
        return check_credentials()

    # Default: run Tower (interactive or daemon based on flag)
    from digos_lib.core_tower import TorreDeControl
    tower = TorreDeControl(daemon_mode=args.daemon)
    tower.run()
    return 0


def show_status():
    from digos_lib.constants import PROFILE_ID, PROFILE_DIR
    from digos_lib.core_vault import CajaSeguraInfo
    from digos_lib.time_core import Clock
    print("=" * 50)
    print(f"  MASTER — Profile: {PROFILE_ID}")
    print(f"  Time: {Clock.iso()}")
    print("=" * 50)
    vault = CajaSeguraInfo.read_slot("principal")
    if not vault:
        print("  No vault configured. Run: python3 digos.py")
        return
    print(f"  Provider:  {vault.get('provider_id', '?')}")
    print(f"  Model:     {vault.get('model', '?')}")
    print(f"  Channel:   {vault.get('gateway_type', '?')}")
    print(f"  API key:   {'✅ set' if vault.get('api_key') else '❌ missing'}")
    print(f"  Bot token: {'✅ set' if vault.get('gateway_token') else '❌ missing'}")
    print("=" * 50)


def check_credentials():
    from digos_lib.core_vault import CajaSeguraInfo
    from digos_lib.provider_api import _provider_api_request, test_telegram_token
    vault = CajaSeguraInfo.read_slot("principal")
    if not vault:
        print("❌ No vault configured")
        return 1
    ok, msg, _ = _provider_api_request(vault.get("provider_id", ""), vault.get("api_key", ""))
    print(f"API key:    {'✅' if ok else '❌'} {msg}")
    if vault.get("gateway_token"):
        ok, msg = test_telegram_token(vault["gateway_token"])
        print(f"Telegram:   {'✅' if ok else '❌'} {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
