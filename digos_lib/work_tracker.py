"""
work.py — Work Execution Tracker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tracks what the agent is actively working on, what's paused,
and what's completed.

WORK does NOT speak to the user. It reports to SELF.
"""

import json
import os
import time
from typing import Optional, List


class WorkTracker:
    """Tracks active, paused, and completed work."""

    def __init__(self, rocket_path: str):
        self.work_path = os.path.join(rocket_path, "WORK")
        os.makedirs(self.work_path, exist_ok=True)
        self._files = {
            "ACTIVE": os.path.join(self.work_path, "ACTIVE.md"),
            "PAUSED": os.path.join(self.work_path, "PAUSED.md"),
            "COMPLETED": os.path.join(self.work_path, "COMPLETED.md"),
        }

    # ─── ACTIVE ─────────────────────────────────────────────────

    def start_work(self, title: str, description: str = "", category: str = "") -> None:
        """Start a new work item. Overwrites any existing active work."""
        work = {
            "title": title,
            "description": description,
            "category": category,
            "started_at": time.time(),
            "steps_completed": 0,
        }
        self._write("ACTIVE", work)

    def get_active(self) -> Optional[dict]:
        """Get the currently active work item."""
        return self._read("ACTIVE")

    def update_active(self, notes: str = "", steps_done: int = 0) -> None:
        """Update the current work item with progress."""
        active = self.get_active()
        if active:
            if steps_done:
                active["steps_completed"] = active.get("steps_completed", 0) + steps_done
            active["notes"] = notes
            active["updated_at"] = time.time()
            self._write("ACTIVE", active)

    def has_active(self) -> bool:
        """Is there work actively in progress?"""
        return self.get_active() is not None

    # ─── PAUSE / RESUME ─────────────────────────────────────────

    def pause_active(self, reason: str = "") -> None:
        """Move active work to paused."""
        active = self.get_active()
        if active:
            active["paused_at"] = time.time()
            active["pause_reason"] = reason
            self._write("ACTIVE", None)  # Clear active
            paused = self._read("PAUSED") or []
            paused.append(active)
            self._write("PAUSED", paused)

    def resume_latest(self) -> Optional[dict]:
        """Resume the most recently paused work."""
        paused = self._read("PAUSED") or []
        if not paused:
            return None
        latest = paused.pop()
        self._write("PAUSED", paused)
        latest["resumed_at"] = time.time()
        latest.pop("paused_at", None)
        latest.pop("pause_reason", None)
        self._write("ACTIVE", latest)
        return latest

    def get_paused(self) -> List[dict]:
        """Get all paused work items."""
        return self._read("PAUSED") or []

    # ─── COMPLETE ───────────────────────────────────────────────

    def complete_active(self, result: str = "") -> None:
        """Mark active work as completed."""
        active = self.get_active()
        if active:
            active["completed_at"] = time.time()
            active["result"] = result
            self._write("ACTIVE", None)
            completed = self._read("COMPLETED") or []
            completed.append(active)
            self._write("COMPLETED", completed)

    def get_completed(self) -> List[dict]:
        """Get all completed work items."""
        return self._read("COMPLETED") or []

    def get_recent_completed(self, count: int = 3) -> List[dict]:
        """Get the most recent N completed items."""
        completed = self.get_completed()
        return completed[-count:] if completed else []

    # ─── INTERNAL ───────────────────────────────────────────────

    def _write(self, key: str, data) -> None:
        path = self._files[key]
        if data is None:
            # Clear file
            with open(path, "w") as f:
                f.write("null")
        else:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

    def _read(self, key: str):
        path = self._files[key]
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
