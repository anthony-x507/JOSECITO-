"""MASTER constants — version, providers, language codes, intervals."""
import os
from pathlib import Path
from typing import Dict, Any

VERSION = "1.0.0"
PROFILE_ID = os.environ.get("DIGOS_PROFILE_ID", "master")
MASTER_DIR = Path(os.path.expanduser("~/.digos"))
PROFILE_DIR = MASTER_DIR / "profiles" / PROFILE_ID

CENTINELA_POLL_INTERVAL = 60
TOWER_MAINTENANCE_INTERVAL = 10800
PA_REFLECTION_HOUR = 2
FACTORY_HEALTH_HOURS = 6

LANGUAGES: Dict[str, Dict[str, str]] = {
    "1": {"code": "en", "name": "English"},
    "2": {"code": "es", "name": "Español"},
    "3": {"code": "zh", "name": "中文"},
    "4": {"code": "hi", "name": "हिन्दी"},
    "5": {"code": "ar", "name": "العربية"},
    "6": {"code": "pt", "name": "Português"},
    "7": {"code": "ru", "name": "Русский"},
    "8": {"code": "ja", "name": "日本語"},
    "9": {"code": "de", "name": "Deutsch"},
    "10": {"code": "fr", "name": "Français"},
}

ADDITIONAL_LANGUAGES: Dict[str, Dict[str, str]] = {
    "11": {"code": "it", "name": "Italiano"},
    "12": {"code": "ko", "name": "한국어"},
    "13": {"code": "tr", "name": "Türkçe"},
    "14": {"code": "vi", "name": "Tiếng Việt"},
    "15": {"code": "pl", "name": "Polski"},
    "16": {"code": "nl", "name": "Nederlands"},
    "17": {"code": "el", "name": "Ελληνικά"},
    "18": {"code": "sv", "name": "Svenska"},
    "19": {"code": "cs", "name": "Čeština"},
    "20": {"code": "ro", "name": "Română"},
    "21": {"code": "hu", "name": "Magyar"},
    "22": {"code": "fi", "name": "Suomi"},
    "23": {"code": "he", "name": "עברית"},
    "24": {"code": "th", "name": "ไทย"},
    "25": {"code": "id", "name": "Bahasa Indonesia"},
    "26": {"code": "ms", "name": "Bahasa Melayu"},
    "27": {"code": "tl", "name": "Filipino"},
    "28": {"code": "uk", "name": "Українська"},
    "29": {"code": "bn", "name": "বাংলা"},
    "30": {"code": "ta", "name": "தமிழ்"},
    "31": {"code": "fa", "name": "فارسی"},
    "32": {"code": "ur", "name": "اردو"},
    "33": {"code": "sw", "name": "Kiswahili"},
    "34": {"code": "no", "name": "Norsk"},
    "35": {"code": "da", "name": "Dansk"},
    "36": {"code": "bg", "name": "Български"},
    "37": {"code": "hr", "name": "Hrvatski"},
    "38": {"code": "sk", "name": "Slovenčina"},
    "39": {"code": "ca", "name": "Català"},
    "40": {"code": "sl", "name": "Slovenščina"},
}

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "1":      {"name": "OpenAI",       "test_url": "https://api.openai.com/v1/models",      "auth": "bearer", "key_hint": "sk-..."},
    "2":      {"name": "Anthropic",    "test_url": "https://api.anthropic.com/v1/messages", "auth": "x-api-key", "key_hint": "sk-ant-..."},
    "3":      {"name": "Google Gemini","test_url": "https://generativelanguage.googleapis.com/v1/models?key=***", "auth": "query", "key_hint": "AI..."},
    "4":      {"name": "DeepSeek",     "test_url": "https://api.deepseek.com/v1/models",   "auth": "bearer", "key_hint": "sk-..."},
    "5":      {"name": "OpenRouter",   "test_url": "https://openrouter.ai/api/v1/models",  "auth": "bearer", "key_hint": "sk-or-..."},
    "6":      {"name": "Groq",         "test_url": "https://api.groq.com/openai/v1/models","auth": "bearer", "key_hint": "gsk_..."},
    "7":      {"name": "xAI Grok",     "test_url": "https://api.x.ai/v1/models",            "auth": "bearer", "key_hint": "xai-..."},
    "8":      {"name": "Cohere",       "test_url": "https://api.cohere.com/v1/models",      "auth": "bearer", "key_hint": "API key"},
    "9":      {"name": "Mistral",      "test_url": "https://api.mistral.ai/v1/models",     "auth": "bearer", "key_hint": "API key"},
    "10":     {"name": "Together",     "test_url": "https://api.together.xyz/v1/models",    "auth": "bearer", "key_hint": "API key"},
    "11":     {"name": "Fireworks",    "test_url": "https://api.fireworks.ai/v1/models",    "auth": "bearer", "key_hint": "API key"},
    # String-name aliases
    "openai":    {"name": "OpenAI",       "test_url": "https://api.openai.com/v1/models",      "auth": "bearer", "key_hint": "sk-..."},
    "anthropic": {"name": "Anthropic",    "test_url": "https://api.anthropic.com/v1/messages", "auth": "x-api-key", "key_hint": "sk-ant-..."},
    "google":    {"name": "Google Gemini","test_url": "https://generativelanguage.googleapis.com/v1/models?key=***", "auth": "query", "key_hint": "AI..."},
    "gemini":    {"name": "Google Gemini","test_url": "https://generativelanguage.googleapis.com/v1/models?key=***", "auth": "query", "key_hint": "AI..."},
    "deepseek":  {"name": "DeepSeek",     "test_url": "https://api.deepseek.com/v1/models",   "auth": "bearer", "key_hint": "sk-..."},
    "openrouter":{"name": "OpenRouter",   "test_url": "https://openrouter.ai/api/v1/models",  "auth": "bearer", "key_hint": "sk-or-..."},
    "groq":      {"name": "Groq",         "test_url": "https://api.groq.com/openai/v1/models","auth": "bearer", "key_hint": "gsk_..."},
    "xai":       {"name": "xAI Grok",     "test_url": "https://api.x.ai/v1/models",            "auth": "bearer", "key_hint": "xai-..."},
    "cohere":    {"name": "Cohere",       "test_url": "https://api.cohere.com/v1/models",      "auth": "bearer", "key_hint": "API key"},
    "mistral":   {"name": "Mistral",      "test_url": "https://api.mistral.ai/v1/models",     "auth": "bearer", "key_hint": "API key"},
    "together":  {"name": "Together",     "test_url": "https://api.together.xyz/v1/models",    "auth": "bearer", "key_hint": "API key"},
    "fireworks": {"name": "Fireworks",    "test_url": "https://api.fireworks.ai/v1/models",    "auth": "bearer", "key_hint": "API key"},
    "ollama":    {"name": "Ollama (local)","test_url": "http://localhost:11434/v1/models",   "auth": "none",    "key_hint": "(no key)"},
}

PROVIDER_DEFAULT_MODELS: Dict[str, str] = {
    "1": "gpt-4o",                  "openai": "gpt-4o",
    "2": "claude-sonnet-4-20250514","anthropic": "claude-sonnet-4-20250514",
    "3": "gemini-2.0-flash",        "google": "gemini-2.0-flash", "gemini": "gemini-2.0-flash",
    "4": "deepseek-chat",           "deepseek": "deepseek-chat",
    "5": "openrouter/auto",         "openrouter": "openrouter/auto",
    "6": "llama-3.3-70b-versatile", "groq": "llama-3.3-70b-versatile",
    "7": "grok-2-latest",           "xai": "grok-2-latest",
    "8": "command-r-plus",          "cohere": "command-r-plus",
    "9": "mistral-large-latest",    "mistral": "mistral-large-latest",
    "10": "mistralai/Mixtral-8x22B-Instruct-v0.1", "together": "mistralai/Mixtral-8x22B-Instruct-v0.1",
    "11": "accounts/fireworks/models/llama-v3p3-70b-instruct", "fireworks": "accounts/fireworks/models/llama-v3p3-70b-instruct",
    "ollama": "llava:7b",
}

PROVIDER_URLS: Dict[str, str] = {
    "1": "https://api.openai.com/v1",                       "openai": "https://api.openai.com/v1",
    "2": "https://api.anthropic.com/v1",                     "anthropic": "https://api.anthropic.com/v1",
    "3": "https://generativelanguage.googleapis.com/v1beta/openai", "google": "https://generativelanguage.googleapis.com/v1beta/openai", "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "4": "https://api.deepseek.com/v1",                      "deepseek": "https://api.deepseek.com/v1",
    "5": "https://openrouter.ai/api/v1",                     "openrouter": "https://openrouter.ai/api/v1",
    "6": "https://api.groq.com/openai/v1",                   "groq": "https://api.groq.com/openai/v1",
    "7": "https://api.x.ai/v1",                              "xai": "https://api.x.ai/v1",
    "8": "https://api.cohere.com/v1",                        "cohere": "https://api.cohere.com/v1",
    "9": "https://api.mistral.ai/v1",                        "mistral": "https://api.mistral.ai/v1",
    "10": "https://api.together.xyz/v1",                     "together": "https://api.together.xyz/v1",
    "11": "https://api.fireworks.ai/v1",                     "fireworks": "https://api.fireworks.ai/v1",
    "ollama": "http://localhost:11434/v1",
}

CHANNELS: Dict[str, Dict[str, str]] = {
    "1": {"name": "Telegram", "icon": "📱", "env_var": "TELEGRAM_BOT_TOKEN"},
    "2": {"name": "Discord",  "icon": "💬", "env_var": "DISCORD_BOT_TOKEN"},
    "3": {"name": "WhatsApp", "icon": "📞", "env_var": "WHATSAPP_TOKEN"},
    "4": {"name": "iMessage", "icon": "💚", "env_var": "(no token)"},
    "5": {"name": "Signal",   "icon": "🔒", "env_var": "SIGNAL_TOKEN"},
    "6": {"name": "Matrix",   "icon": "🟢", "env_var": "MATRIX_TOKEN"},
    "7": {"name": "Email",    "icon": "📧", "env_var": "SMTP_CREDENTIALS"},
    "8": {"name": "SMS",      "icon": "📲", "env_var": "TWILIO_CREDENTIALS"},
}

RED_ZONE_SYSTEMS = [
    "safety_candle",
    "gps",
    "work_destination",
    "factory_internal_rules",
    "self_awareness",
    "tower_structure",
    "factory_structure",
]

FACTORY_STATUSES = {
    "pending", "processing", "awaiting_user", "blocked",
    "done_not_closed", "resolved", "closed", "rejected", "failed",
}

FACTORY_TERMINAL_STATUSES = {
    "closed", "delivered", "cancelled", "done_not_closed",
    "awaiting_user", "failed", "rejected", "resolved", "completed", "blocked",
}
