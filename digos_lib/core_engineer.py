"""System Engineer — processes tickets, creates specs for the Factory."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List

from digos_lib.constants import PROFILE_DIR
from digos_lib.time_core import Calendar
from digos_lib.llm_client import LLMClient


class SystemEngineer:
    """Reads tickets, writes specs, returns to user for verification."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm
        self.tickets_dir = PROFILE_DIR / "factory_tickets"
        self.tickets_dir.mkdir(parents=True, exist_ok=True)

    def create_ticket(self, title: str, description: str,
                      requester: str = "system", target: str = "factory",
                      priority: str = "normal", ticket_type: str = "build",
                      metadata: Optional[Dict] = None) -> str:
        ticket_id = Calendar.auto_stamp()
        ticket = {
            "id": ticket_id,
            "type": ticket_type,
            "title": title,
            "description": description,
            "status": "pending",
            "priority": priority,
            "requester": requester,
            "target": target,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "assignee": None,
            "comments": [],
            "history": [{"timestamp": datetime.now(timezone.utc).isoformat(),
                         "actor": requester, "action": "created"}],
            "metadata": metadata or {},
        }
        path = self.tickets_dir / f"ticket_{ticket_id}.json"
        with open(path, "w") as f:
            json.dump(ticket, f, indent=2)
        return ticket_id

    def list_open_tickets(self) -> List[Dict]:
        tickets = []
        for p in self.tickets_dir.glob("ticket_*.json"):
            try:
                with open(p) as f:
                    t = json.load(f)
                if t.get("status") not in ("closed", "resolved", "cancelled"):
                    tickets.append(t)
            except Exception:
                continue
        return tickets

    def get_ticket(self, ticket_id: str) -> Optional[Dict]:
        path = self.tickets_dir / f"ticket_{ticket_id}.json"
        if not path.exists():
            return None
        with open(path) as f:
            return json.load(f)

    def update_ticket_status(self, ticket_id: str, status: str, actor: str = "engineer") -> bool:
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return False
        ticket["status"] = status
        ticket["updated_at"] = datetime.now(timezone.utc).isoformat()
        ticket["history"].append({
            "timestamp": ticket["updated_at"],
            "actor": actor,
            "action": f"status_changed:{status}",
        })
        path = self.tickets_dir / f"ticket_{ticket_id}.json"
        with open(path, "w") as f:
            json.dump(ticket, f, indent=2)
        return True

    def write_spec(self, ticket_id: str) -> bool:
        """Engineer writes a spec for the ticket. Returns True on success."""
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            return False
        # Mark as processing
        self.update_ticket_status(ticket_id, "processing", "engineer")
        # In a real system, this would call the LLM to write the spec
        # For v1.0, we keep it deterministic
        spec = (
            f"SPEC for {ticket_id}\n"
            f"Title: {ticket['title']}\n"
            f"Description: {ticket['description']}\n"
            f"Type: {ticket['type']}\n"
            f"Priority: {ticket['priority']}\n"
            f"\n-- Acceptance criteria --\n"
            f"- The tool MUST be more efficient than the previous one (Factory Law).\n"
            f"- The tool MUST be portable across machines.\n"
            f"- The tool MUST NOT touch the RED ZONE systems.\n"
        )
        ticket["spec"] = spec
        ticket["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self.tickets_dir / f"ticket_{ticket_id}.json"
        with open(path, "w") as f:
            json.dump(ticket, f, indent=2)
        return True
