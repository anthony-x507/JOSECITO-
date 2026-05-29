"""Minimal SuperiorAgent for the embedded DIGOS Factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class InternalAgent:
    """Represents an internal Factory agent created by the SuperiorAgent."""

    name: str
    internal_type: str
    mode: str
    mission: str
    status: str = "created"
    capabilities: List[str] = field(default_factory=list)

    def get_capabilities(self) -> List[str]:
        return list(self.capabilities)


class SuperiorAgent:
    """Creates and keeps track of internal Factory agents."""

    def __init__(self) -> None:
        self.internal_agents: Dict[str, InternalAgent] = {}

    def create_internal(
        self,
        agent_type: str,
        mode: str = "collaborative",
        name: str = "",
        mission: str = "",
    ) -> InternalAgent:
        clean_type = (agent_type or "builder").strip().lower()
        clean_mode = (mode or "collaborative").strip().lower()
        agent_name = name.strip() or f"{clean_type}_{len(self.internal_agents) + 1}"
        agent = InternalAgent(
            name=agent_name,
            internal_type=clean_type,
            mode=clean_mode,
            mission=mission.strip(),
            capabilities=["plan", "review", "report"],
        )
        self.internal_agents[agent_name] = agent
        return agent
