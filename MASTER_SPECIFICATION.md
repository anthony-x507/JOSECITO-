# MASTER — Complete System Specification

**Version:** 1.0
**Authors:** ABACO Team (Anthony Sanchez + 2 AIs)
**Repository:** `git@github.com:anthony-x507/JOSECITO-.git` (public, SSH)
**License:** Open
**Last Updated:** 2026-06-09

---

## 1. SYSTEM IDENTITY

### 1.1 Name

- **Official Name:** MASTER
- **Not:** ABACO, DIGOS, JOSECITO, ABACO_Hub, ORCHESTRA (these are historical/codebase names)
- **ABACO** is the **team** that created MASTER (Anthony Sanchez + 2 AIs)
- **JOSECITO-** is the **repository checkout name** (arbitrary GitHub name)
- **DIGOS** is the **historical codename** used in early source code — must be removed

### 1.2 Brand Voice

- All conversation: **Spanish**
- All code, comments, documentation, system prompts, commit messages, error messages, prompts: **English**
- Repository description, README: **English**
- This is non-negotiable

### 1.3 What MASTER Is

MASTER is a **multi-agent orchestration system** designed to be installed by any user with a single command, configured via an interactive onboarding, and operated via Telegram (or other channels). It consists of:

- A **central orchestrator** (the Tower) that maintains system health
- A **24/7 watchdog** (Centinela) that never sleeps
- A **user-facing agent** (PA — Principal Agent) that talks to the user
- A **Factory** that builds new internal capabilities and tools
- **Internal agents** that perform specialized tasks
- A **ticket system** that tracks work across components
- A **safety system** (Safety Candle) that classifies and blocks harmful requests
- A **time system** (Time Core) that schedules and fires alarms

---

## 2. ARCHITECTURE — HIGH LEVEL

```
                         USER
                          |
                          v
                   ┌──────────────┐
                   │  GATEWAYS    │  (Telegram, Discord, WhatsApp, CLI, iMessage...)
                   └──────┬───────┘
                          |
                          v
                  ┌────────────────┐
                  │  SYSTEM ENGINE │  (GPS / SELF / WORK — routes messages)
                  └────────┬───────┘
                           |
                           v
                  ┌────────────────┐
                  │  PA (Agent)    │  (user-facing, LLM-powered)
                  └────────┬───────┘
                           |
        ┌──────────────────┼──────────────────┐
        |                  |                  |
        v                  v                  v
   ┌─────────┐      ┌───────────┐      ┌──────────────┐
   │ TOWER   │      │ FACTORY   │      │ INTERNAL     │
   │ (cyclic)│      │ (pipeline)│      │ AGENTS       │
   └────┬────┘      └─────┬─────┘      └──────────────┘
        |                 |
        v                 v
   ┌──────────────────────────┐
   │     CENTINELA (24/7)     │  (no LLM, pure code, watchdog)
   └──────────────────────────┘
```

### 2.1 Data Flow

1. **User sends message** to a gateway (Telegram, CLI, etc.)
2. **Gateway** receives, normalizes the message, enqueues it
3. **Tower's poll loop** dequeues messages every cycle
4. **System Engine** (`_check_with_engine`) validates the request against GPS/SELF/WORK rules
5. **PA** (Principal Agent) processes the message using its LLM
6. **PA may delegate** to the Factory (for tool creation) or to Internal Agents
7. **Response** is sent back through the gateway
8. **Centinela** (in parallel) monitors everything for safety, performance, and rule violations

---

## 3. ONBOARDING — SINGLE COMMAND

### 3.1 Philosophy

The user runs **exactly one command** to install MASTER. No separate clone, no separate setup, no separate daemon start. Everything is done by a single Python script.

### 3.2 Command

```bash
python3 ~/Desktop/onboard.py
```

### 3.3 Flow

1. **Clone** the repository from GitHub to `~/MASTER/`
2. **Welcome banner** with hiperrealista ANSI ninja art and "MASTER" in color (M=red, A=white, S=red, T=white, E=white, R=red)
3. **Language selection** — **40 languages total**, 10 visible by default, 30 behind "Other languages" option
4. **Provider selection** — **20+ providers** (OpenAI, Anthropic, Google, DeepSeek, OpenRouter, Groq, xAI, Cohere, Mistral, Together, Fireworks, Ollama, etc.)
5. **API key entry** — validated against the provider's actual endpoint
6. **Channel selection** — 8 channels (Telegram, Discord, WhatsApp, iMessage, Signal, Matrix, Email, SMS)
7. **Token entry** — validated against the channel's actual API
8. **Vault writing** — credentials stored in `~/.digos/profiles/<name>/vault.enc` using encryption
9. **Daemon auto-start** — `digos.py --daemon` runs at the end, the user sees the daemon come alive

### 3.4 Anti-Patterns (must NOT happen)

- ❌ Two separate commands (one for install, one for daemon)
- ❌ Manual `cd ~/MASTER && git clone`
- ❌ User has to set environment variables manually
- ❌ Daemon requires manual start after onboarding
- ❌ Only 2 languages
- ❌ Only 1 provider
- ❌ Only 1 channel
- ❌ All providers validated against OpenAI's endpoint (must use provider-specific validation)

### 3.5 Supported Languages (Phase 1 — 10)

1. English (en)
2. Español (es)
3. 中文 (zh)
4. हिन्दी (hi)
5. العربية (ar)
6. Português (pt)
7. Русский (ru)
8. 日本語 (ja)
9. Deutsch (de)
10. Français (fr)

### 3.6 Additional Languages (Phase 2 — 30+)

Italian, Korean, Turkish, Vietnamese, Polish, Dutch, Greek, Swedish, Czech, Romanian, Hungarian, Finnish, Hebrew, Thai, Indonesian, Malay, Filipino, Ukrainian, Bengali, Tamil, Persian, Urdu, Swahili, Norwegian, Danish, Bulgarian, Croatian, Slovak, Catalan, Slovenian, Lithuanian, Latvian, Estonian, Serbian, Macedonian, Albanian, Icelandic, Welsh, Irish

### 3.7 Supported Providers (20+)

| ID | Provider | Env Var | Auth | Test URL |
|:--:|----------|---------|------|----------|
| 1 / openai | OpenAI | OPENAI_API_KEY | bearer | https://api.openai.com/v1/models |
| 2 / anthropic | Anthropic | ANTHROPIC_API_KEY | x-api-key | https://api.anthropic.com/v1/messages |
| 3 / google, gemini | Google Gemini | GOOGLE_API_KEY | query | https://generativelanguage.googleapis.com/v1/models?key=*** |
| 4 / deepseek | DeepSeek | DEEPSEEK_API_KEY | bearer | https://api.deepseek.com/v1/models |
| 5 / openrouter | OpenRouter | OPENROUTER_API_KEY | bearer | https://openrouter.ai/api/v1/models |
| 6 / groq | Groq | GROQ_API_KEY | bearer | https://api.groq.com/openai/v1/models |
| 7 / xai | xAI Grok | XAI_API_KEY | bearer | https://api.x.ai/v1/models |
| 8 / cohere | Cohere | COHERE_API_KEY | bearer | https://api.cohere.com/v1/models |
| 9 / mistral | Mistral | MISTRAL_API_KEY | bearer | https://api.mistral.ai/v1/models |
| 10 / together | Together | TOGETHER_API_KEY | bearer | https://api.together.xyz/v1/models |
| 11 / fireworks | Fireworks | FIREWORKS_API_KEY | bearer | https://api.fireworks.ai/v1/models |
| ollama | Ollama (local) | (none) | none | http://localhost:11434/v1 |

### 3.8 Supported Channels (8)

| ID | Channel | Required Token | Validation |
|:--:|---------|----------------|------------|
| 1 | Telegram | Bot Token from @BotFather | `https://api.telegram.org/bot<token>/getMe` |
| 2 | Discord | Bot Token | Discord API |
| 3 | WhatsApp | Business API token | WhatsApp Business API |
| 4 | iMessage | (macOS only, no token) | AppleScript bridge |
| 5 | Signal | Phone number + API | Signal API |
| 6 | Matrix | Access token | Matrix homeserver |
| 7 | Email | SMTP credentials | SMTP AUTH |
| 8 | SMS | Twilio Account SID + Auth Token | Twilio API |

---

## 4. THE TOWER (Central Orchestrator)

### 4.1 Role

The Tower is the **conductor** of MASTER. It is responsible for:
- **System health** — monitoring all components
- **Self-preservation** — diagnosing and fixing itself
- **Cyclic maintenance** — running diagnostics every 3 hours
- **Architectural enforcement** — making sure all components follow the rules
- **Listening to Centinela alarms** — waking up when needed

### 4.2 Cyclic Behavior

The Tower **does NOT run 24/7**. It works in cycles:

```
┌─────────────────────────────────────────────────────────┐
│                    TOWER CYCLE                          │
├─────────────────────────────────────────────────────────┤
│  1. WAKE (start of cycle)                               │
│  2. RUN DIAGNOSTICS (LLM-powered)                       │
│  3. SELF-ANALYZE (TSAME — Tower Self-Analysis Engine)   │
│  4. CHECK HEALTH (agents, tickets, factory)             │
│  5. PROCESS ALARMS (from Centinela)                     │
│  6. SLEEP (3 hours or until woken by Centinela)         │
└─────────────────────────────────────────────────────────┘
```

### 4.3 TSAME — Tower Self-Analysis & Modification Engine

TSAME is the Tower's **introspection system**. It uses an isolated LLM to:
- Observe the system state
- Detect issues
- Propose fixes (the Tower can self-modify, but only with constraints)

**Key TSAME rules:**
- TSAME runs only during Tower cycles (not 24/7)
- TSAME has its own isolated LLM (does not share with PA or Factory)
- TSAME can READ all system state but can only WRITE to non-critical systems
- TSAME never touches the **RED ZONE** (see Section 11)

### 4.4 Wake Events

The Tower wakes from its 3-hour sleep when:
1. A **Centinela alarm** fires (high severity)
2. The user sends a message (via gateway → Centinela notifies Tower)
3. A **scheduled alarm** from TimeCore fires
4. The **maintenance timer** (3 hours) expires

The Tower does NOT process every Telegram message directly. **Centinela handles message routing 24/7**. The Tower only wakes for high-priority events.

### 4.5 Tower's LLM (Isolated)

The Tower has its **own LLM client**, completely isolated from PA's LLM and Factory's LLMs. This is for **self-analysis** — the Tower uses it to reason about its own state.

**API:**
```python
tower.ask(prompt: str) -> str
```

**Configuration (auto-detected from vault):**
- `api_key`: from vault
- `base_url`: derived from `provider_id` (string OR numeric, both must work)
- `model`: default per provider, can be overridden

**Provider URL Resolution — CRITICAL:**
The `provider_id` in the vault is a **string name** (e.g., `"deepseek"`, not `"4"`). The Tower's URL resolver MUST accept both string names and numeric IDs. This is a known bug source — the URL map must include all string-name aliases.

```python
PROVIDER_URLS = {
    "1": "https://api.openai.com/v1", "openai": "https://api.openai.com/v1",
    "4": "https://api.deepseek.com/v1", "deepseek": "https://api.deepseek.com/v1",
    # ... etc
}
```

---

## 5. CENTINELA (24/7 Watchdog)

### 5.1 Role

Centinela is the **ever-vigilant guardian**. It runs 24/7, never sleeps, has no LLM (pure Python for speed and predictability). It is responsible for:
- **Health monitoring** — checking API keys, tokens, agent status
- **Ticket routing** — creating tickets for the Factory when issues are detected
- **Alarms** — firing alarms to wake the Tower
- **Safety classification** — first-pass safety check on incoming messages
- **Stall detection** — identifying stuck tickets or stuck agents

### 5.2 Polling Interval

Default: **60 seconds** (`CENTINELA_POLL_INTERVAL = 60`)

### 5.3 What Centinela Does NOT Do

- ❌ Does not use LLM
- ❌ Does not communicate with the user
- ❌ Does not modify code
- ❌ Does not bypass safety rules

### 5.4 API Key Check

Centinela periodically validates the API key. **Critical:** The check must use the **correct test URL for the provider**, not a hardcoded one.

**Validation flow:**
1. Read provider from vault
2. Look up the provider's `test_url` in the providers map (accepts both numeric IDs and string names)
3. Make a request to that URL with the API key
4. If HTTP 200 → key is valid
5. If HTTP 401/403 → key is invalid → create a ticket for the user
6. If no test URL found → **log warning, do NOT flag as invalid** (this was a previous bug)

**Strike System:**
- 1st-2nd failure: log warning
- 3rd failure: create a ticket for the user
- The user is notified via Telegram that the API key has been rejected

---

## 6. PA — PRINCIPAL AGENT (User-Facing)

### 6.1 Role

PA is the **only agent that talks to the user**. All user-facing communication goes through PA.

PA's responsibilities:
- **Conversation** — natural language dialogue
- **Intent classification** — what does the user want?
- **Capability gap detection** — when the user needs something MASTER can't do (Camino B)
- **Tool execution** — calling tools registered in the system
- **Graceful degradation** — when a capability is missing, communicate clearly

### 6.2 PA's LLM

PA has its **own LLM client** (separate from Tower's and Factory's).

**Configuration:**
- `api_key`, `base_url`, `model` from vault
- `system_prompt` — generated dynamically based on language and context

### 6.3 System Prompt

The system prompt is **dynamically built** based on:
- User's language (default: Spanish, fallback: English)
- User's identity (name from onboarding)
- Provider info
- System context (clock, alarms, self-awareness state)

**Critical rules for the system prompt:**
- The system MUST identify itself as **MASTER**, not DIGOS, not "an AI assistant"
- The system MUST respond in the user's **detected chat language**, not the user's selected onboarding language (these are different)
- The system MUST be concise, direct, helpful
- The system MUST NOT volunteer creator information unless asked

**Example Spanish system prompt:**
```
Eres MASTER, un sistema inteligente de orquestación multi-agente.
Creado por ABACO Team (Anthony Sanchez + 2 IAs).
Tienes acceso a herramientas. Úsalas cuando sea necesario.
Sé conciso, directo y útil.
Responde SIEMPRE en español a menos que el usuario escriba en inglés.
...
```

### 6.4 Language Detection

PA receives `chat_language` parameter for each message. The flow:
1. **Gateway** detects the chat's language using `resolve_telegram_chat_language(chat_id, text)`
2. **Tower** passes `chat_language` to PA when calling `process_message(text, chat_language)`
3. **PA's system prompt** explicitly says which language to use
4. **Tower post-processes** the response with `enforce_response_language(response, chat_language)` as a safety net

### 6.5 Camino B (Capability Gap Detection)

When the user asks for something MASTER can't do, PA must:
1. Detect the missing capability
2. Ask the user: "I don't have [capability] yet. Want me to build it?"
3. If user confirms → create a Factory ticket
4. If user declines → apologize and offer alternatives

**This must NOT block indefinitely.** If a capability is requested but can't be built (missing tools, missing dependencies), the ticket should be marked `blocked` and the user notified — not left in `pending` forever.

---

## 7. THE FACTORY (Capability Builder)

### 7.1 Role

The Factory **builds new tools and capabilities** for MASTER. When PA detects a missing capability and the user confirms, PA creates a ticket → Engineer picks it up → Factory builds it.

### 7.2 Pipeline

```
Engineer → Builder → Auditor → Reviewer → Integrator
   │          │          │          │           │
   │          │          │          │           └── Deploys to production
   │          │          │          └── Final QA check
   │          │          └── Security audit
   │          └── Writes the code
   └── Writes the spec
```

Each agent has its **own isolated LLM** (5 total LLMs in the Factory).

### 7.3 Factory Law (CRITICAL)

**Every new tool must be MORE EFFICIENT and SUPERIOR to the previous one.** This is enforced as a hard gate by the Integrator. No tool goes to production unless it's better than what it replaces.

### 7.4 Engineer's Voice

When an Engineer receives a bad or incomplete ticket, it does NOT reject. It returns it with **"RETURN FOR VERIFICATION"** and specific constructive questions. This is a tone choice — collaborative, not gatekeeping.

### 7.5 Ticket Statuses

| Status | Meaning | Next |
|--------|---------|------|
| `pending` | Just created, waiting for Engineer | Engineer picks up |
| `processing` | Engineer working on it | Builder picks up |
| `awaiting_user` | Needs user input | User responds |
| `blocked` | Cannot proceed (missing dep, etc.) | Notify user, don't loop |
| `done_not_closed` | Built, awaiting verification | Reviewer picks up |
| `resolved` | Verified, deployed | Closed by requester |
| `closed` | Requester closed it | Archive |
| `rejected` | Engineer returned for verification | User fixes and resubmits |
| `failed` | Pipeline failed | Notify user with error |

---

## 8. INTERNAL AGENTS

### 8.1 What They Are

Internal agents are **specialized workers** that PA can delegate to. They are NOT the Factory (which builds tools), they are the **users of the tools**.

Examples:
- A "Translator" internal agent
- A "Code Reviewer" internal agent
- A "Data Analyst" internal agent

### 8.2 Two Modes

Internal agents can be created in **two modes**:

#### Mode 1: COLABORADORES (Open Line)
- Can communicate freely with PA, Tower, and Factory
- Have a ticket queue
- Can create new tickets
- Have their own LLM
- Used for complex multi-step tasks

#### Mode 2: CERRADOS (Closed)
- Can ONLY receive a task and report back to PA
- No direct access to Tower or Factory
- Simpler, more constrained
- Used for isolated, single-purpose work

### 8.3 Inheritance

When an internal agent is created, it **inherits** from PA:
- Same LLM provider/base_url/api_key
- Same language
- Same safety rules
- A sub-set of PA's tools (depending on mode)

---

## 9. TICKETS — THE WORKFLOW SYSTEM

### 9.1 Philosophy

A ticket is a **persistent, traceable unit of work** that moves through the system. Every important action creates a ticket. Tickets are the **only** way work moves between agents.

### 9.2 Persistence

Tickets persist for **at least 2 seconds** (auto-stamped with year/day/hour/second). This is to prevent:
- Lost messages during agent restarts
- Race conditions between components
- Invisible failures (ticket created, then dies silently)

### 9.3 Auto-Stamp Format

Each ticket has:
```json
{
  "id": "20260609T022225-0000",
  "type": "build_tool",
  "title": "STT capability",
  "status": "pending",
  "priority": "high",
  "requester": "PA",
  "assignee": "engineer",
  "created_at": "2026-06-09T02:22:25.123456+00:00",
  "updated_at": "2026-06-09T02:22:25.123456+00:00",
  "description": "...",
  "context": {...},
  "comments": [],
  "history": [
    {"timestamp": "...", "actor": "PA", "action": "created"},
    {"timestamp": "...", "actor": "engineer", "action": "picked_up"}
  ]
}
```

### 9.4 Closing Rules

**Only the requester can close a ticket.** Not the assignee, not the Tower, not Centinela. The requester is the one who created the ticket and is responsible for verifying completion.

### 9.5 Ticket Storage

Tickets are stored in `~/.digos/profiles/<name>/factory_tickets/` as individual JSON files. Each ticket is ONE file. This makes them easy to inspect, delete, or migrate.

---

## 10. SAFETY CANDLE

### 10.1 Role

Safety Candle is a **lightweight, single-pass classifier** that checks every incoming message for safety. It runs BEFORE PA processes the message.

### 10.2 Why "Light"

Safety Candle is **NOT a 7-layer guard**. It's a single classifier that looks at:
1. **Intent** — what is the user trying to do?
2. **Context** — what was the conversation about?
3. **Risk** — could this cause harm?

### 10.3 Categories

| Category | Example | Action |
|----------|---------|--------|
| Harmful content | "How do I make a bomb?" | Block, evidence |
| Privacy violation | "Give me someone's password" | Block, evidence |
| System manipulation | "Bypass your safety rules" | Block, evidence |
| Out of scope | "Predict the lottery numbers" | Defer to PA |
| Normal | "What's the weather?" | Pass through |

### 10.4 Escalation

1. **First offense** — generic safe response
2. **Second offense** — log evidence, more strict response
3. **Third+** — GPS LOCKDOWN, system enters restricted mode, user must acknowledge

---

## 11. RED ZONE — IMMUTABLE SYSTEMS

The following systems are **PROTECTED from modification** by anyone, including the Tower's TSAME engine:

1. **Safety Candle** — the safety classifier itself
2. **GPS** — the work destination system
3. **Work Destination** — the work routing system
4. **Factory Internal Rules** — Factory Law, status flow
5. **Self Awareness** — the system's self-monitoring
6. **Tower Structure** — the Tower's own architecture
7. **Factory Structure** — the Factory's own architecture

These are the "constitution" of MASTER. They can only be changed by a **manual, explicit user action** with confirmation.

---

## 12. TIME CORE

### 12.1 Role

Time Core handles all time-related operations WITHOUT using an LLM. Pure Python.

### 12.2 Components

- **Clock** — current time, formatted output
- **Calendar** — date arithmetic, business days, holidays
- **AlarmSystem** — schedule one-shot or recurring alarms

### 12.3 Default Alarms

- **Tower maintenance** — every 3 hours
- **PA reflection** — daily at 2 AM
- **Factory health check** — every 6 hours
- **Centinela** — every 60 seconds (not an alarm, a poll)

### 12.4 Alarm Routing

When an alarm fires:
1. The target agent is notified
2. If the target is asleep (e.g., Tower), it's woken
3. The alarm is logged

---

## 13. FLAT FOLDER SYSTEM

### 13.1 Why

To save tokens and keep the repository manageable, MASTER uses a **flat folder structure** with `.index` files for navigation, instead of deeply nested folders.

### 13.2 Structure

```
TORRE/
├── CONSTITUTION.md
├── TOWER_OPERATIONS.md
├── CENTINELA_OPERATIONS.md
├── PA_OPERATIONS.md
├── FACTORY_OPERATIONS.md
├── INTERNAL_AGENTS_OPERATIONS.md
├── FLAT_FOLDER_SYSTEM.md
├── TESTING_SYSTEM.md
└── .index
```

Each `.index` file contains a one-line description of every file in the directory. Tools that need to know what's in the folder read the index first.

---

## 14. SYMPHONY AUDITOR (Testing System)

### 14.1 Role

The Symphony Auditor is MASTER's **self-diagnostic scanner**. It runs scenarios to verify the system is functioning correctly.

### 14.2 Categories

1. **Safety** (15 scenarios) — does Safety Candle block correctly?
2. **PA** (15 scenarios) — does PA respond correctly?
3. **Factory** (10 scenarios) — does the pipeline work?
4. **Centinela** (10 scenarios) — does the watchdog detect issues?
5. **Tower** (5 scenarios) — does the cyclic behavior work?
6. **Agents** (5 scenarios) — do internal agents function?

### 14.3 Verdicts

| Verdict | Meaning |
|---------|---------|
| `CLEAN` | System behaves as expected |
| `MISMATCH` | System does something different than expected |
| `UNCERTAIN` | Cannot determine if correct |
| `FALSE_POSITIVE` | System flagged something as wrong when it's not |
| `CRASHED` | System crashed during the test |

### 14.4 Hot-Fix Mode (Avión Caliente)

When a test fails:
1. Clean the state of the failing component
2. Re-run the SAME test immediately
3. If it passes → it was a **stale state issue** (not a code issue)
4. If it fails → it's a **code issue**, proceed to fix

The plane keeps flying. Don't bring it back to the hangar.

---

## 15. AVION CALIENTE — TESTING METHODOLOGY

The system is tested in **flight**, not in a hangar. This means:

1. **Never stop everything** for a fix. The system must keep running.
2. **Clean state, re-run** — if a test fails, clean the state of the relevant component and re-run.
3. **Same altitude, same conditions** — when re-running, the test conditions must be identical.
4. **Compare results** — if the re-run passes, it was a stale state issue.
5. **Document everything** — every test, every fix, every observation is recorded.

---

## 16. CONVERSATION RULES

### 16.1 Languages

- **Code:** English (variable names, comments, docstrings, error messages, commit messages, log messages)
- **Documentation:** English (all .md files, READMEs, specs)
- **User-facing system prompts:** Match user's chat language
- **Conversation with the user (in the dev/agent context):** Spanish

### 16.2 Tone

- **Firm but warm** — not harsh
- **Use "RETURN FOR VERIFICATION"** not "REJECT"
- **Acknowledge user frustration** — "Tienes razón", "Entendido"
- **Direct answers** — no "I cannot" unless truly impossible
- **One-command simplicity** — the user should never need more than one command

---

## 17. CODE ORGANIZATION

### 17.1 Repository Structure

```
JOSECITO-/                        # GitHub repo (checkout name)
├── PROJECT_IDENTITY.md           # Canonical identity
├── digos.py                      # Entry point
├── digos_lib/
│   ├── core_tower.py             # Tower class (lifecycle, cycle, TSAME)
│   ├── core_centinela.py         # Centinela watchdog
│   ├── core_engineer.py          # System Engineer
│   ├── core_vault.py             # Encrypted credentials storage
│   ├── core_identity.py          # Anti-clone, version
│   ├── core_factory.py           # Factory manager
│   ├── agent_core.py             # PA / AIAgent
│   ├── communication_branch.py   # PA voice / response style
│   ├── intent_classifier.py      # Camino B intent detection
│   ├── language_detector.py      # Language detection
│   ├── llm_client.py             # LLM HTTP client
│   ├── provider_api.py           # Provider-specific API tests
│   ├── safety_candle.py          # Safety classifier
│   ├── time_core.py              # Clock, Calendar, AlarmSystem
│   └── constants.py              # Constants, PROVIDERS map
├── master/
│   └── factory/
│       ├── engineer.py           # Engineer agent
│       ├── builder.py            # Builder agent
│       ├── auditor.py            # Auditor agent
│       ├── reviewer.py           # Reviewer agent
│       └── manager.py            # Factory manager
├── TORRE/                        # Documentation (flat)
│   ├── CONSTITUTION.md
│   ├── TOWER_OPERATIONS.md
│   ├── CENTINELA_OPERATIONS.md
│   ├── PA_OPERATIONS.md
│   ├── PA_RESPONSE_STYLE.md
│   ├── FACTORY_OPERATIONS.md
│   ├── INTERNAL_AGENTS_OPERATIONS.md
│   ├── FLAT_FOLDER_SYSTEM.md
│   └── TESTING_SYSTEM.md
└── tools/                        # Utilities
    ├── scanner.py                # Symphony Auditor
    ├── run_scanner.py            # CLI for scanner
    ├── scanner_scenarios/        # 60 JSON scenarios
    ├── onboard.py                # One-command onboarding
    ├── install.py                # One-command install (auto)
    ├── diagnostic.py             # Post-onboarding diagnostic
    ├── banner.py                 # Welcome banner
    ├── ninja_banner.txt          # ANSI art ninja
    └── README.md
```

### 17.2 Code Rules

- **No file over 8000 lines** — if a file is too large, split it
- **No circular imports** — use lazy imports if needed
- **All errors logged, not swallowed** — no bare `except: pass`
- **All state persisted** — no in-memory-only state for critical data
- **No hardcoded paths** — use `os.path.expanduser("~/.digos/...")` for user paths
- **No `print()` in production code** — use the logger
- **All credentials in vault, never in code or .env**

### 17.3 Testing Rules

- Every new feature has at least 1 test scenario
- Every fix for a bug has a regression test
- Tests live in `tools/scanner_scenarios/` as JSON
- Tests are run by `python3 tools/run_scanner.py --scenario <id>`

---

## 18. KNOWN BUGS FROM SESSION 2026-06-08

These were the bugs we discovered and the status of each fix:

| # | Bug | Status | Fixed in |
|:--:|------|:------:|----------|
| 1 | Provider URL maps only accept numeric IDs | ✅ Fixed | constants.py, core_tower.py |
| 2 | Centinela gives false positive on API keys (no test URL) | ✅ Fixed | constants.py |
| 3 | Tower diagnostics crash (.complete() → .ask()) | ✅ Fixed | core_tower.py |
| 4 | TSAME crash (agents_needing_attention) | ✅ Fixed | core_tower.py |
| 5 | Gateways die when Tower sleeps | ⚠️ Partial | core_tower.py |
| 6 | Onboarding patched already-patched digos.py | ✅ Fixed | onboard.py |
| 7 | UnboundLocalError: shutil in onboard.py | ✅ Fixed | onboard.py |
| 8 | state.json language NOT SET | ❌ Not fixed | onboarding flow |
| 9 | _ensure_launchd() blocks daemon with prompt | ❌ Not fixed | core_tower.py |
| 10 | Multiple daemons cause HTTP 409 on Telegram | ⚠️ Documented | user-side |
| 11 | Factory tickets stuck in blocked indefinitely | ❌ Not fixed | factory pipeline |
| 12 | Ctrl+C doesn't stop daemon (3h sleep) | ⚠️ Partial | core_tower.py |

---

## 19. DEPLOYMENT INSTRUCTIONS

### 19.1 From Scratch

```bash
# 1. Single command (clones, configures, validates, starts)
python3 ~/Desktop/onboard.py

# 2. Open Telegram, talk to your bot
# Done.
```

### 19.2 Update Existing Install

```bash
cd ~/MASTER
git pull origin main
python3 digos.py --daemon
```

### 19.3 Run Tests

```bash
cd ~/MASTER
python3 tools/run_scanner.py --quick
```

### 19.4 Reset Everything (DESTRUCTIVE)

```bash
pkill -9 -f "digos.py"
rm -rf ~/.digos/profiles/master ~/.digos/profiles/master-local
find ~/Library/LaunchAgents -name "*digos*" -delete
python3 ~/Desktop/onboard.py
```

---

## 20. APPENDIX — KEY DECISIONS LOG

| Date | Decision | Reason |
|------|----------|--------|
| 2026-06-08 | Tower is cyclic (3h), not 24/7 | Save LLM tokens, Centinela handles 24/7 |
| 2026-06-08 | All musicians have isolated LLMs | No cross-contamination |
| 2026-06-08 | PA + Centinela are the only ones that contact Tower/Factory | Architectural clarity |
| 2026-06-08 | Internal Agents: COLABORADORES or CERRADOS | Two clear use cases |
| 2026-06-08 | Tickets persist 2s minimum | Prevent lost work |
| 2026-06-08 | 7 systems in RED ZONE | Protect critical infrastructure |
| 2026-06-08 | Safety Candle RED: light, single-pass | Speed over paranoia |
| 2026-06-08 | Factory Law: each tool must be better | Continuous improvement |
| 2026-06-08 | Engineer uses "RETURN FOR VERIFICATION" | Collaborative, not gatekeeping |
| 2026-06-08 | PA repairs ideas, Tower repairs code | Clear jurisdiction |
| 2026-06-08 | Avión Caliente methodology | Test in flight, not hangar |
| 2026-06-09 | One-command onboarding | User experience |
| 2026-06-09 | 40 languages, 20+ providers, 8 channels | Maximum accessibility |
| 2026-06-09 | All credentials in vault, never .env | Security |

---

**END OF SPECIFICATION**

**Next action:** Use this document to write the code from scratch. Follow the structure exactly. Test with the Symphony Auditor. Use the Avión Caliente methodology.
