#!/usr/bin/env python3
"""
MASTER Onboarding v2 — single command, end-to-end.

Bilingual UI (es/en), hidden credential input, validated model,
auto-start daemon. All output in the user's chosen language.
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

REPO_URL = "git@github.com:anthony-x507/JOSECITO-.git"
INSTALL_DIR = os.path.expanduser("~/MASTER")
PROFILE_ID = "master"


# ── Translations ────────────────────────────────────────
T = {
    "es": {
        "banner_done": "✅ Banner listo",
        "cloning": "📥 Bajando MASTER",
        "cloned": "✅ Clonado",
        "already": "✅ Ya existe",
        "clone_fail": "❌ Error bajando",
        "choose_lang": "🌍 Elige tu idioma:",
        "more_langs": "Más idiomas (30 disponibles)",
        "choose_provider": "🤖 Elige tu proveedor de IA:",
        "enter_key": "🔑 Ingresa tu API key de {provider} (oculto):",
        "valid": "✅ Válido",
        "invalid": "❌ {msg} — intenta de nuevo o Ctrl+C para cancelar",
        "choose_channel": "📡 Elige tu canal:",
        "configuring": "{icon} Configurando {name}",
        "botfather": "Obtén tu token de @BotFather en Telegram",
        "bot_token": "Token del bot (oculto):",
        "token": "Token (oculto):",
        "no_token_needed": "✅ {name} — no necesita token",
        "connected": "✅ Conectado: {info}",
        "model": "Modelo (Enter para auto):",
        "invalid_model": "⚠️ '{input}' no parece un nombre de modelo válido. Presiona Enter para auto o escribe uno.",
        "saving": "💾 Guardando en vault cifrado",
        "vault_done": "✅ Vault configurado",
        "starting": "🚀 Arrancando MASTER daemon",
        "daemon_running": "✅ Daemon activo. Abre Telegram y habla con tu bot.",
        "press_ctrl_c": "Presiona Ctrl+C para detener el daemon",
        "cancelled": "Cancelado.",
    },
    "en": {
        "banner_done": "✅ Banner ready",
        "cloning": "📥 Cloning MASTER",
        "cloned": "✅ Cloned",
        "already": "✅ Already exists",
        "clone_fail": "❌ Clone failed",
        "choose_lang": "🌍 Choose your language:",
        "more_langs": "More languages (30 available)",
        "choose_provider": "🤖 Choose your AI provider:",
        "enter_key": "🔑 Enter your {provider} API key (hidden):",
        "valid": "✅ Valid",
        "invalid": "❌ {msg} — try again or Ctrl+C to cancel",
        "choose_channel": "📡 Choose your channel:",
        "configuring": "{icon} Configuring {name}",
        "botfather": "Get token from @BotFather on Telegram",
        "bot_token": "Bot token (hidden):",
        "token": "Token (hidden):",
        "no_token_needed": "✅ {name} — no token needed",
        "connected": "✅ Connected: {info}",
        "model": "Model (Enter for auto):",
        "invalid_model": "⚠️ '{input}' doesn't look like a model name. Press Enter for auto or type one.",
        "saving": "💾 Saving to encrypted vault",
        "vault_done": "✅ Vault configured",
        "starting": "🚀 Starting MASTER daemon",
        "daemon_running": "✅ Daemon running. Open Telegram and talk to your bot.",
        "press_ctrl_c": "Press Ctrl+C to stop the daemon",
        "cancelled": "Cancelled.",
    },
}


def t(key, lang="en", **kwargs):
    """Get translation, with Spanish fallback."""
    text = T.get(lang, T["en"]).get(key, T["en"][key])
    return text.format(**kwargs) if kwargs else text


def clear():
    os.system("clear" if os.name != "nt" else "cls")


def show_banner():
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        from banner import show_banner as _show
        _show()
    except Exception:
        pass


def safe_input(prompt):
    """Input that handles EOF gracefully."""
    try:
        return input(prompt)
    except EOFError:
        return ""


def hidden_input(prompt):
    """Hidden password-style input. Falls back to normal if getpass fails."""
    try:
        import getpass
        return getpass.getpass(prompt)
    except Exception:
        return safe_input(prompt)


# ── Step 1: Clone ──────────────────────────────────────
def step_clone(lang):
    print(f"  {t('cloning', lang)} to {INSTALL_DIR}...")
    if os.path.exists(INSTALL_DIR):
        if os.path.isdir(os.path.join(INSTALL_DIR, "digos_lib")):
            print(f"  {t('already', lang)} at {INSTALL_DIR}")
            return True
        # Not a valid install — remove and re-clone
        shutil.rmtree(INSTALL_DIR)
    os.makedirs(os.path.dirname(INSTALL_DIR), exist_ok=True)
    result = subprocess.run(["git", "clone", REPO_URL, INSTALL_DIR],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  {t('clone_fail', lang)}: {result.stderr[:200]}")
        return False
    print(f"  {t('cloned', lang)} to {INSTALL_DIR}")
    return True


# ── Step 2: Language ───────────────────────────────────
def step_language():
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.constants import LANGUAGES, ADDITIONAL_LANGUAGES
    print()
    print("  🌍 Choose your language / Elige tu idioma:")
    print()
    options = [(k, v) for k, v in LANGUAGES.items()]
    for i, (k, v) in enumerate(options, 1):
        print(f"    {i:2d}. {v['name']}")
    print()
    print(f"    0.  More languages (30 available) / Más idiomas")
    print()
    while True:
        choice = safe_input("  → ").strip()
        if choice == "0":
            print()
            for i, (k, v) in enumerate(ADDITIONAL_LANGUAGES.items(), len(options) + 1):
                print(f"    {i:2d}. {v['name']}")
            print()
            choice = safe_input("  → ").strip()
            all_langs = {**{k: v for k, v in LANGUAGES.items()}, **ADDITIONAL_LANGUAGES}
            if choice in all_langs:
                return all_langs[choice]["code"]
        elif choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1][1]["code"]


# ── Step 3: Provider ───────────────────────────────────
def step_provider(lang):
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.constants import PROVIDERS
    print()
    print(f"  {t('choose_provider', lang)}")
    print()
    providers = [(pid, p) for pid, p in PROVIDERS.items() if pid.isdigit()]
    for i, (pid, p) in enumerate(providers, 1):
        print(f"    {i:2d}. {p['name']}  (key: {p['key_hint']})")
    print()
    while True:
        choice = safe_input("  → ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(providers):
            return providers[int(choice) - 1]


# ── Step 4: API key (HIDDEN) ───────────────────────────
def step_api_key(provider, lang):
    print()
    print(f"  {t('enter_key', lang, provider=provider['name'])}")
    while True:
        key = hidden_input("  → ")
        if not key:
            continue
        from digos_lib.provider_api import _provider_api_request
        provider_id = provider_id_lookup_by_name(provider)
        ok, msg, _ = _provider_api_request(provider_id, key)
        if ok or "No test URL" in msg:
            # Show first/last 4 chars only
            masked = key[:4] + "..." + key[-4:] if len(key) > 12 else "***"
            print(f"  {t('valid', lang)}: {masked}")
            return key
        else:
            print(f"  {t('invalid', lang, msg=msg)}")


def provider_id_lookup_by_name(provider):
    from digos_lib.constants import PROVIDERS
    for pid, p in PROVIDERS.items():
        if p["name"] == provider["name"] and not pid.isdigit():
            return pid
    return "openai"


# ── Step 5: Channel ────────────────────────────────────
def step_channel(lang):
    sys.path.insert(0, INSTALL_DIR)
    from digos_lib.constants import CHANNELS
    print()
    print(f"  {t('choose_channel', lang)}")
    print()
    channels = list(CHANNELS.items())
    for i, (cid, c) in enumerate(channels, 1):
        print(f"    {i:2d}. {c['icon']} {c['name']}")
    print()
    while True:
        choice = safe_input("  → ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(channels):
            return channels[int(choice) - 1]


# ── Step 6: Channel token (HIDDEN) ─────────────────────
def step_channel_token(channel_id, channel, lang):
    cid, c = channel_id, channel
    print()
    print(f"  {t('configuring', lang, icon=c['icon'], name=c['name'])}")
    if cid == "4":  # iMessage
        print(f"  {t('no_token_needed', lang, name=c['name'])}")
        return None
    if cid == "1":  # Telegram
        print(f"  {t('botfather', lang)}")
        print()
        while True:
            token = hidden_input(f"  {t('bot_token', lang)} ")
            if not token:
                continue
            from digos_lib.provider_api import test_telegram_token
            ok, msg = test_telegram_token(token)
            if ok:
                print(f"  {t('connected', lang, info=msg)}")
                return token
            else:
                print(f"  {t('invalid', lang, msg=msg)}")
    # Other channels: just hidden input
    return hidden_input(f"  {t('token', lang)} ") or None


# ── Step 7: Model (validated) ──────────────────────────
def step_model(lang):
    print()
    prompt = f"  {t('model', lang)} "
    while True:
        model = safe_input(prompt).strip()
        if not model:
            return None
        # Basic validation: must contain letters and not be a common garbage input
        if len(model) < 2 or model.lower() in ("yes", "no", "y", "n", "ok", "test", "prueba", "si"):
            print(f"  {t('invalid_model', lang, input=model)}")
            continue
        return model


# ── Step 8: Save vault ────────────────────────────────
def step_save_vault(api_key, provider_id, model, gateway_token, gateway_type, language):
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
    # .env for daemon process (same dir as digos.py)
    env_path = os.path.join(INSTALL_DIR, ".env")
    with open(env_path, "w") as f:
        if api_key:
            f.write(f"DIGOS_API_KEY={api_key}\n")
        if gateway_token:
            f.write(f"DIGOS_GATEWAY_TOKEN={gateway_token}\n")
        f.write(f"DIGOS_PROFILE_ID={PROFILE_ID}\n")
    return True


# ── Step 9: Start daemon ───────────────────────────────
def step_start_daemon(lang):
    print()
    print(f"  {t('starting', lang)}")
    print()
    try:
        result = subprocess.run(
            ["python3", "digos.py", "--daemon"],
            cwd=INSTALL_DIR,
        )
        return result.returncode
    except KeyboardInterrupt:
        return 0


# ── Main ───────────────────────────────────────────────
def main():
    clear()
    show_banner()
    print("  🧭  MASTER  —  ABACO Team")
    print()

    if not step_clone("en"):
        return 1
    os.chdir(INSTALL_DIR)

    language = step_language()
    print(f"  ✅ Language: {language}")
    print()

    provider_id, provider = step_provider(language)
    print(f"  ✅ Provider: {provider['name']}")
    print()

    api_key = step_api_key(provider, language)
    print()

    channel_id, channel = step_channel(language)
    print(f"  ✅ Channel: {channel['name']}")
    print()

    token = step_channel_token(channel_id, channel, language)
    print()

    model = step_model(language)
    print(f"  ✅ Model: {model or 'auto'}")
    print()

    print(f"  {t('saving', language)}")
    step_save_vault(api_key, provider_id, model, token, channel["name"].lower(), language)
    print(f"  {t('vault_done', language)}")
    print()

    # Start daemon
    step_start_daemon(language)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Cancelled.")
        sys.exit(1)
