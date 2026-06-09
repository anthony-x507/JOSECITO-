"""Factory manager — orchestrates Engineer → Builder → Auditor → Reviewer."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

from digos_lib.constants import PROFILE_DIR
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.llm_client import LLMClient
from master.factory.agents import Engineer, Builder, Auditor, Reviewer


class FactoryManager:
    """Orchestrates the 5 isolated factory agents."""

    def __init__(self):
        self._agents: Dict[str, object] = {}
        self.tickets_dir = PROFILE_DIR / "factory_tickets"
        self.pipelines_dir = PROFILE_DIR / "pipelines"
        self.tickets_dir.mkdir(parents=True, exist_ok=True)
        self.pipelines_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_agents()

    def _initialize_agents(self) -> None:
        vault = CajaSeguraInfo.read_slot("principal") or {}
        api_key = vault.get("api_key", "")
        provider_id = vault.get("provider_id", "")
        if not api_key or not provider_id:
            return
        from digos_lib.constants import PROVIDER_URLS, PROVIDER_DEFAULT_MODELS
        base_url = PROVIDER_URLS.get(provider_id, PROVIDER_URLS["openai"])
        model = PROVIDER_DEFAULT_MODELS.get(provider_id, "gpt-4o")
        system_prompts = {
            "engineer": "You are the Engineer. Write clear, testable specs.",
            "builder":  "You are the Builder. Write efficient, portable code.",
            "auditor":  "You are the Auditor. Find security and quality issues.",
            "reviewer": "You are the Reviewer. Approve only if Factory Law passes.",
        }
        for role, prompt in system_prompts.items():
            llm = LLMClient(base_url=base_url, api_key=api_key, model=model,
                            system_prompt=prompt)
            if role == "engineer":
                self._agents[role] = Engineer(llm)
            elif role == "builder":
                self._agents[role] = Builder(llm)
            elif role == "auditor":
                self._agents[role] = Auditor(llm)
            elif role == "reviewer":
                self._agents[role] = Reviewer(llm)

    def inject_llms(self, llm_client_class, base_config: Dict) -> None:
        """Re-inject LLMs from updated config (called by Tower on init)."""
        for role in ("engineer", "builder", "auditor", "reviewer"):
            llm = llm_client_class(
                base_url=base_config.get("base_url", ""),
                api_key=base_config.get("api_key", ""),
                model=base_config.get("model", "gpt-4o"),
                system_prompt=f"You are the {role.title()} in the Factory.",
            )
            if role == "engineer":
                self._agents[role] = Engineer(llm)
            elif role == "builder":
                self._agents[role] = Builder(llm)
            elif role == "auditor":
                self._agents[role] = Auditor(llm)
            elif role == "reviewer":
                self._agents[role] = Reviewer(llm)

    def health_check(self) -> Dict:
        """Returns factory health status."""
        return {
            "agents_healthy": len(self._agents),
            "stuck_tickets": self._count_stuck_tickets(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _count_stuck_tickets(self) -> int:
        count = 0
        cutoff = datetime.now(timezone.utc).timestamp() - 300  # 5 min
        for p in self.tickets_dir.glob("ticket_*.json"):
            try:
                with open(p) as f:
                    t = json.load(f)
                if t.get("status") in ("pending", "processing"):
                    created = datetime.fromisoformat(t["created_at"]).timestamp()
                    if created < cutoff:
                        count += 1
            except Exception:
                continue
        return count
