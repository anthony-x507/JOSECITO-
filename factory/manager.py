"""Embedded FactoryManager used by clean DIGOS clones.

The Factory accepts capability requests, creates traceable tickets, and returns
the same contract TorreDeControl expects. It does not claim that a capability is
installed until generated code exists and passes later validation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional
from uuid import uuid4

from digos_lib.constants import DIGOS_DIR
from .superior import SuperiorAgent


class FactoryManager:
    """Small executable Factory runtime for local DIGOS product tests."""

    def __init__(self) -> None:
        self._superior = SuperiorAgent()
        self._progress_cb: Optional[Callable[[str, dict], None]] = None
        self._factory_dir = DIGOS_DIR / "factory"
        self._tickets_dir = self._factory_dir / "tickets"
        self._counter_file = self._factory_dir / "counter.json"

    def setup(self) -> None:
        self._tickets_dir.mkdir(parents=True, exist_ok=True)
        if not self._counter_file.exists():
            self._counter_file.write_text('{"next_ticket": 1}\n', encoding="utf-8")

    def _next_ticket_number(self) -> int:
        self.setup()
        try:
            data = json.loads(self._counter_file.read_text(encoding="utf-8"))
        except Exception:
            data = {"next_ticket": 1}
        ticket_number = int(data.get("next_ticket", 1))
        self._counter_file.write_text(
            json.dumps({"next_ticket": ticket_number + 1}, indent=2) + "\n",
            encoding="utf-8",
        )
        return ticket_number

    def _emit(self, name: str, args: Optional[dict] = None) -> None:
        if self._progress_cb is None:
            return
        try:
            self._progress_cb(name, args or {})
        except Exception:
            pass

    def request_new_capability(
        self,
        capability_id: str,
        family: str = "",
        description: str = "",
        target_capabilities=None,
        target_limitations=None,
        tool_name: str = "",
        requested_by: str = "agente",
        llm_api_key: str = "",
        llm_base_url: str = "",
        llm_model: str = "",
    ) -> Dict[str, object]:
        """Accepts a capability request into the Factory pipeline.

        The current embedded Factory creates the ticket and assigns a builder.
        It intentionally leaves generated_code empty until a real builder stage
        generates and validates code. TorreDeControl must not mark the tool as
        executable only because this request was accepted.
        """

        self.setup()
        ticket_number = self._next_ticket_number()
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        ticket_id = f"{now}-{ticket_number:04d}"
        sandbox_id = str(uuid4())
        clean_capability = (capability_id or "capability").strip()
        clean_tool = (tool_name or clean_capability).strip()
        builder_name = f"{clean_capability}_builder"

        self._emit("create_capability", {"capability": clean_capability})
        builder = self._superior.create_internal(
            agent_type="builder",
            mode="collaborative",
            name=builder_name,
            mission=f"Prepare capability request for {clean_capability}",
        )
        self._emit("builder", {"agent": builder.name})
        self._emit("sandbox", {"sandbox": sandbox_id})
        self._emit("auditor", {"ticket": ticket_id})

        ticket = {
            "ticket_id": ticket_id,
            "ticket_number": ticket_number,
            "capability_id": clean_capability,
            "family": family,
            "description": description,
            "tool_name": clean_tool,
            "requested_by": requested_by,
            "builder": builder.name,
            "sandbox_id": sandbox_id,
            "revision": "v1",
            "status": "accepted_for_factory_review",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target_capabilities": list(target_capabilities or []),
            "target_limitations": list(target_limitations or []),
            "provider_ready": bool(llm_api_key and llm_base_url and llm_model),
        }
        ticket_path = self._tickets_dir / f"{ticket_id}.json"
        ticket_path.write_text(json.dumps(ticket, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return {
            "ok": True,
            "ticket_id": ticket_id,
            "ticket_number": ticket_number,
            "agent_name": builder.name,
            "tool_name": clean_tool,
            "sandbox_id": sandbox_id,
            "revision": "v1",
            "status": "accepted_for_factory_review",
            "generated_code": "",
            "code_validated": False,
            "message": "Solicitud aceptada por la Factoría para revisión.",
        }
