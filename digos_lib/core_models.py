"""DIGOS data models."""
from dataclasses import dataclass, field, asdict
from typing import Optional

# VERSION defined here to avoid circular import with digos.py
# Update both digos.py and this file when bumping the version.
VERSION = "0.3.0"

@dataclass
class AgenteRecord:
    """Unified agent record — born with Kendo + Work Destination injected by the Factory."""
    agent_id: str = ""
    name: str = ""
    role: str = "primero"  # "primero" or "sub"
    provider_id: str = ""
    provider_name: str = ""
    language: str = ""
    created_at: str = ""
    model: str = ""
    gateway_type: str = ""
    gateway_configured: bool = False
    setup_complete: bool = False
    status: str = "active"
    # Factory injects these automatically — immutable core values
    has_kendo: bool = True
    has_work_destination: bool = True

@dataclass
class DigosState:
    setup_complete: bool = False
    language: str = ""
    agente: Optional[dict] = None
    gateway: Optional[dict] = None
    version: str = VERSION

@dataclass
class Ticket:
    id: str
    source: str
    target: str
    problem: str
    severity: str
    status: str
    created_at: str
    profile: str = "system"
    model: str = ""
    resolved_at: str = ""
    diagnosis: str = ""
    resolution: str = ""
    assignee: str = ""
    needs_human: bool = False
    notes: list = field(default_factory=list)
    closed_at: str = ""
    # ── Flag Persistente ──
    requester: str = ""       # Quién creó/pidió este ticket (agente)
    flag_status: str = "inbox" # inbox | processing | review | delivered
    result: str = ""           # Resultado entregado por el Engineer
    picked_up_at: str = ""     # Cuándo el Engineer lo recogió
    delivered_at: str = ""     # Cuándo se entregó el resultado
