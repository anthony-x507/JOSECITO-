#!/usr/bin/env python3
"""
MASTER Post-Onboarding Diagnostic

Run after onboarding to verify everything is configured correctly.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("🧪 MASTER Post-Onboarding Diagnostic")
    print("=" * 50)
    errors = 0

    from digos_lib.core_vault import CajaSeguraInfo
    vault = CajaSeguraInfo.read_slot("principal")
    if not vault:
        print("  ❌ No vault configured")
        return 1

    api_key = vault.get("api_key", "")
    provider_id = vault.get("provider_id", "")
    gateway_token = vault.get("gateway_token", "")
    gateway_type = vault.get("gateway_type", "")

    print(f"  Provider:      {provider_id}")
    print(f"  API key:       {'✅ set' if api_key else '❌ missing'}")
    print(f"  Gateway:       {gateway_type}")
    print(f"  Bot token:     {'✅ set' if gateway_token else '❌ missing'}")

    # Test API
    if api_key and provider_id:
        from digos_lib.provider_api import _provider_api_request
        ok, msg, _ = _provider_api_request(provider_id, api_key)
        print(f"  API check:     {'✅' if ok else '❌'} {msg}")
        if not ok:
            errors += 1

    # Test Telegram
    if gateway_token:
        from digos_lib.provider_api import test_telegram_token
        ok, msg = test_telegram_token(gateway_token)
        print(f"  Telegram:      {'✅' if ok else '❌'} {msg}")
        if not ok:
            errors += 1

    print("=" * 50)
    if errors == 0:
        print("  ✅ All checks passed")
        return 0
    print(f"  ❌ {errors} check(s) failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
