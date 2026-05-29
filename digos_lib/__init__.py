"""DIGOS modular library.

Architecture:
  constants.py      — Single source of truth (VERSION, paths, providers, etc.)
  provider_api.py   — Tests connectivity with AI providers
  
  core_models.py    — AgenteRecord, DigosState, Ticket
  core_vault.py      — CajaSeguraInfo (encrypted credential cabinet)
  core_log.py        — LogKeeper (structured JSON logs with rotation)
  core_centinela.py  — Centinela (defect detection, alarms, reminders)
  core_engineer.py   — SystemEngineer (ticket system with mailbox architecture)
  core_self.py       — SelfAwarenessCore (tower's internal state machine)
  core_tower.py      — TorreDeControl (orquestador principal)
  core_gateways.py   — BaseGateway, GatewayCLI, GatewayTelegram
  
  self_awareness.py — SelfAwareness (agent's rich soul: GPS + WorkTracker + SafetyCandle)
  gps.py             — GPS (guidance: destination, course, deviation analysis)
  work_tracker.py    — WorkTracker (active/paused/completed work tracking)
  engine.py          — Engine (orchestrates SELF + GPS + WORK)
  
  agent_tools.py     — AVAILABLE_TOOLS, DANGEROUS_TOOLS, tool executors
  agent_core.py      — AIAgent (LLM interaction loop with tool calling)
"""
from digos_lib.constants import (
    VERSION, DIGOS_DIR, STATE_FILE, KEY_FILE, LOG_DIR,
    STRIKES_FILE, SELF_FILE, VAULT_FILE,
    LANGUAGES, PROVIDERS, GATEWAYS,
    SYSTEM_IDENTITY, IDENTITY_RESPONSES,
    CENTINELA_INTERVAL, STRIKE_LIMIT,
    SYSTEM_NAME, SYSTEM_VERSION,
)
from digos_lib.provider_api import _provider_api_request

from digos_lib.core_models import AgenteRecord, DigosState, Ticket
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.core_log import LogKeeper
from digos_lib.core_centinela import Centinela
from digos_lib.core_engineer import SystemEngineer
from digos_lib.core_self import SelfAwarenessCore
from digos_lib.core_pipeline import TicketConversationPipeline
from digos_lib.core_tower import TorreDeControl
from digos_lib.core_gateways import BaseGateway, GatewayCLI, GatewayTelegram

from digos_lib.self_awareness import SelfAwareness
from digos_lib.gps import GPS
from digos_lib.work_tracker import WorkTracker
from digos_lib.engine import Engine

from digos_lib.agent_tools import AVAILABLE_TOOLS, DANGEROUS_TOOLS
# AIAgent is lazy-imported to avoid circular import with agent.py
# (agent.py imports from digos_lib, and core_tower imports from agent)
