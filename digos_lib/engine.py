"""
engine.py — The NÚCLEO Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ties SELF + GPS + WORK into a single loop.

On each interaction:
1. SELF loads identity + GPS + work context
2. GPS analyzes if user's message aligns with destination
3. If consensus → process normally
4. If no consensus → SELF asks user
5. WORK tracks execution progress
"""

import os
from digos_lib.self_awareness import SelfAwareness
from digos_lib.gps import GPS
from digos_lib.work_tracker import WorkTracker
from typing import List

class Engine:
    """The main loop — orchestrates SELF, GPS, and WORK."""

    def __init__(self, rocket_path: str):
        self.rocket_path = rocket_path
        self.self_awareness = SelfAwareness(rocket_path)
        self.gps = self.self_awareness.gps
        self.work_tracker = WorkTracker(rocket_path)
        self._current_context = None

    def get_context_for_agent(self) -> str:
        """
        Build the full context for the agent (LLM prompt).
        Called on every interaction cycle.
        """
        return self.self_awareness.build_system_prompt()

    def process_message(self, user_message: str) -> dict:
        """
        Process an incoming user message through the consensus pipeline.

        Returns a decision dict:
          {"action": "process_normally" | "ask_user" | "new_destination",
           "reason": "...",
           "question": "... (if ask_user)",
           "context": "system prompt text"}
        """
        active = self.work_tracker.get_active()
        active_title = active.get("title", "") if active else ""

        # SELF analyzes with GPS guidance
        decision = self.self_awareness.analyze_user_message(
            user_message, active_title
        )

        # Attach the full context for the LLM
        decision["context"] = self.get_context_for_agent()

        return decision

    def get_triple_consensus(self, user_message: str = None,
                             active_task_title: str = "") -> dict:
        """
        Get the full triple consensus report.
        SELF checks identity, GPS checks destination alignment,
        and WORK checks task progress.
        """
        active = self.work_tracker.get_active()
        atitle = active.get("title", "") if active else active_task_title
        return self.self_awareness.triple_consensus(user_message, atitle)

    def start_new_work(self, title: str, description: str = "", category: str = "") -> None:
        """Start tracking a new work item."""
        self.work_tracker.start_work(title, description, category)

    def set_destination(self, title: str, description: str, steps: List[str]) -> None:
        """Set the GPS destination."""
        self.gps.set_destination(title, description, steps)