# MASTER

**Multi-Agent Orchestration System**
**Built by ABACO Team (Anthony Sanchez + 2 AIs)**
**Version 1.0.0**

---

## What is MASTER?

MASTER is a multi-agent orchestration system that installs with a single command and operates via Telegram (or other channels). It consists of:

- **Tower** — Central orchestrator (cyclic, 3h wake)
- **Centinela** — 24/7 watchdog (no LLM)
- **PA (Principal Agent)** — User-facing
- **Factory** — Capability builder (5 isolated LLMs)
- **Internal Agents** — Specialized workers (COLABORADORES / CERRADOS)
- **Safety Candle** — Lightweight intent classifier
- **Tickets** — Persistent work tracking
- **Time Core** — Clock, Calendar, AlarmSystem

## One-Command Install

```bash
python3 ~/Desktop/onboard.py
```

Or, after cloning:

```bash
python3 digos.py --daemon
```

## Quick Start

```bash
# Run onboarding (interactive)
python3 tools/onboard.py

# Or start daemon directly
python3 digos.py --daemon

# Check system status
python3 digos.py --status

# Verify credentials
python3 digos.py --check

# Run tests
python3 tools/scanner.py
```

## Supported Languages (40)

Phase 1 (10): English, Español, 中文, हिन्दी, العربية, Português, Русский, 日本語, Deutsch, Français
Phase 2 (30+): Italian, Korean, Turkish, Vietnamese, Polish, Dutch, Greek, Swedish, Czech, Romanian, ...

## Supported Providers (20+)

OpenAI, Anthropic, Google Gemini, DeepSeek, OpenRouter, Groq, xAI, Cohere, Mistral, Together, Fireworks, Ollama (local), ...

## Supported Channels (8)

Telegram, Discord, WhatsApp, iMessage, Signal, Matrix, Email, SMS

## Architecture

See `MASTER_SPECIFICATION.md` (32KB, 20 sections) for the complete specification.

## License

Open
