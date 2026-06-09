#!/usr/bin/env python3
"""
MASTER Onboarding — single command, end-to-end.

Flow:
  1. Clone (or use existing) repository
  2. Show welcome banner
  3. Language (40 options, 10 shown + 30 behind "more")
  4. Provider (20+ options)
  5. API key (validated per provider)
  6. Channel (8 options)
  7. Bot token (validated per channel)
  8. Save to vault (encrypted)
  9. Auto-start daemon

Usage:
  python3 onboard.py            Run onboarding
  python3 onboard.py --auto     Non-interactive (uses .env or defaults)
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

REPO_URL = "git@github.com:anthony-x507/JOSECITO-.git"
INSTALL_DIR = os.path.expanduser("~/MASTER")
PROFILE_ID = "master"


def clear():
    os.system("clear" if os.name != "nt" else "cls")


def show_banner():
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    from banner import show_banner as _show
    _show()


# ── Step 1: Clone ────────────────────────────────────
def step_clone():
    print(f"  📥 Cloning MASTER to {INSTALL_DIR}...")
    if os.path.exists(INSTALL_DIR):
        print(f"  ✅ Already exists at {INSTALL_DIR}")
        return True
    os.makedirs(os.path.dirname(INSTALL_DIR), exist_ok=True)
    result = subprocess.run(["git", "clone", REPO_URL, INSTALL_DIR],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ❌ Clone failed: {result.stderr}")
        return False
    print(f"  ✅ Cloned to {INSTALL_DIR}")
    return True


# ── Step 2: Language ─────────────────────────────────
def step_language():
    """40 languages: 10 shown first, 30 behind 'more'."""
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.constants import LANGUAGES, ADDITIONAL_LANGUAGES
    print()
    print("  🌍 Choose your language:")
    print()
    options = []
    for k, v in LANGUAGES.items():
        options.append((k, v))
    for i, (k, v) in enumerate(options, 1):
        print(f"    {i:2d}. {v['name']}")
    print()
    print(f"    0.  More languages ({len(ADDITIONAL_LANGUAGES)} available)")
    print()
    while True:
        try:
            choice = input("  → ").strip()
            if choice == "0":
                print()
                for i, (k, v) in enumerate(ADDITIONAL_LANGUAGES.items(), len(options) + 1):
                    print(f"    {i:2d}. {v['name']}")
                print()
                choice = input("  → ").strip()
                all_langs = {**{k: v for k, v in LANGUAGES.items()}, **ADDITIONAL_LANGUAGES}
                if choice in all_langs:
                    return all_langs[choice]["code"]
            elif choice.isdigit() and 1 <= int(choice) <= len(options):
                return options[int(choice) - 1][1]["code"]
        except (ValueError, IndexError, EOFError):
            pass


# ── Step 3: Provider ─────────────────────────────────
def step_provider():
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.constants import PROVIDERS
    print()
    print("  🤖 Choose your AI provider:")
    print()
    providers = list(PROVIDERS.items())
    for i, (pid, p) in enumerate(providers, 1):
        if pid.isdigit():
            print(f"    {i:2d}. {p['name']}  (key: {p['key_hint']})")
    print()
    while True:
        try:
            choice = input("  → ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(providers):
                pid, p = providers[int(choice) - 1]
                return pid, p
        except (ValueError, IndexError, EOFError):
            pass


# ── Step 4: API key ─────────────────────────────────
def step_api_key(provider):
    print()
    print(f"  🔑 Enter your {provider['name']} API key ({provider['key_hint']})")
    while True:
        key = input("  → ").strip()
        if not key:
            continue
        # Validate
        from digos_lib.provider_api import _provider_api_request
        ok, msg, _ = _provider_api_request(provider_id_lookup_by_name(provider), key)
        if ok or "No test URL" in msg:
            print(f"  ✅ Valid: {msg}")
            return key
        else:
            print(f"  ❌ {msg} — try again or Ctrl+C to cancel")


def provider_id_lookup_by_name(provider):
    """Find the string-name provider id from a provider dict."""
    for pid, p in [
        ("openai", {"name": "OpenAI"}), ("anthropic", {"name": "Anthropic"}),
        ("google", {"name": "Google Gemini"}), ("deepseek", {"name": "DeepSeek"}),
        ("openrouter", {"name": "OpenRouter"}), ("groq", {"name": "Groq"}),
        ("xai", {"name": "xAI Grok"}), ("cohere", {"name": "Cohere"}),
        ("mistral", {"name": "Mistral"}), ("together", {"name": "Together"}),
        ("fireworks", {"name": "Fireworks"}),
    ]:
        if p["name"] == provider["name"]:
            return pid
    # Fallback: find by name in PROVIDERS
    from digos_lib.constants import PROVIDERS
    for pid, p in PROVIDERS.items():
        if p["name"] == provider["name"] and not pid.isdigit():
            return pid
    return "openai"


# ── Step 5: Channel ─────────────────────────────────
def step_channel():
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.constants import CHANNELS
    print()
    print("  📡 Choose your channel:")
    print()
    channels = list(CHANNELS.items())
    for i, (cid, c) in enumerate(channels, 1):
        print(f"    {i:2d}. {c['icon']} {c['name']}")
    print()
    while True:
        try:
            choice = input("  → ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(channels):
                return channels[int(choice) - 1]
        except (ValueError, IndexError, EOFError):
            pass


# ── Step 6: Channel token ───────────────────────────
def step_channel_token(channel_id, channel):
    cid, c = channel_id, channel
    print()
    print(f"  {c['icon']} Configuring {c['name']}")
    if cid == "4":  # iMessage
        print(f"  ✅ iMessage (macOS only — no token needed)")
        return None
    if cid == "1":  # Telegram
        print(f"  Get token from @BotFather on Telegram")
        print()
        while True:
            token = input(f"  Bot Token: ").strip()
            if not token:
                continue
            from digos_lib.provider_api import test_telegram_token
            ok, msg = test_telegram_token(token)
            if ok:
                print(f"  ✅ Connected: {msg}")
                return token
            else:
                print(f"  ❌ {msg} — try again")
    return input(f"  Token: ").strip() or None


# ── Step 7: Save vault ─────────────────────────────
def step_save_vault(api_key, provider_id, model, gateway_token, gateway_type, language):
    """Save credentials to the encrypted vault."""
    os.environ["DIGOS_PROFILE_ID"] = PROFILE_ID
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.core_vault import CajaSeguraInfo
    creds = {
        "api_key": api_key,
        "provider_id": provider_id,
        "model": model,
        "gateway_token": gateway_token or "",
        "gateway_type": gateway_type,
        "language": language,
    }
    CajaSeguraInfo.write_slot("principal", creds)
    # Also save to .env for the daemon process
    env_path = os.path.join(INSTALL_DIR, ".env")
    with open(env_path, "w") as f:
        if api_key:
            f.write(f"DIGOS_API_KEY={api_key}\n")
        if gateway_token:
            f.write(f"DIGOS_GATEWAY_TOKEN={gateway_token}\n")
        f.write(f"DIGOS_PROFILE_ID={PROFILE_ID}\n")
    return True


# ── Main ─────────────────────────────────────────────
def main():
    clear()
    show_banner()
    print("  🧭  MASTER  —  ABACO Team")
    print()

    if not step_clone():
        return 1
    os.chdir(INSTALL_DIR)

    language = step_language()
    print(f"  ✅ Language: {language}")

    provider_id, provider = step_provider()
    print(f"  ✅ Provider: {provider['name']}")

    api_key = step_api_key(provider)
    channel_id, channel = step_channel()
    print(f"  ✅ Channel: {channel['name']}")

    token = step_channel_token(channel_id, channel)
    model = input(f"  Model (default: auto): ").strip() or None

    step_save_vault(api_key, provider_id, model, token, channel["name"].lower(), language)
    print()
    print(f"  ✅ Vault configured")
    print()
    print(f"  🚀 Starting MASTER daemon...")
    print()

    # Start daemon
    result = subprocess.run(
        ["python3", "digos.py", "--daemon"],
        cwd=INSTALL_DIR,
    )
    return result.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(1)
