"""
init.py — Agent Initializer
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Creates the ROCKET folder structure for a new agent
and seeds it with initial data.
"""

import os
import shutil


TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")
DEFAULT_TEMPLATE = os.path.join(TEMPLATES, "rocket")


def init_agent(base_path: str, agent_name: str) -> str:
    """
    Initialize ROCKET structure for a new agent.

    Args:
        base_path: Root for all agents (e.g. ~/.digos/agents/)
        agent_name: Name of the agent (e.g. "josecito", "alex")

    Returns:
        Path to the agent's ROCKET directory.
    """
    agent_dir = os.path.join(base_path, agent_name)
    rocket_dir = os.path.join(agent_dir, "ROCKET")

    # Create structure
    for folder in ["SELF", "GPS", "WORK"]:
        os.makedirs(os.path.join(rocket_dir, folder), exist_ok=True)

    # Write SELF files
    _write_if_missing(os.path.join(rocket_dir, "SELF", "IDENTITY.md"), _identity(agent_name))
    _write_if_missing(os.path.join(rocket_dir, "SELF", "STATE.md"), _state())

    # Write GPS files
    _write_if_missing(os.path.join(rocket_dir, "GPS", "DESTINATION.md"), _destination())
    _write_if_missing(os.path.join(rocket_dir, "GPS", "COURSE.md"), _course())

    # Write WORK files
    _write_if_missing(os.path.join(rocket_dir, "WORK", "ACTIVE.md"), "null")
    _write_if_missing(os.path.join(rocket_dir, "WORK", "PAUSED.md"), "[]")
    _write_if_missing(os.path.join(rocket_dir, "WORK", "COMPLETED.md"), "[]")

    return rocket_dir


def _write_if_missing(path: str, content: str) -> None:
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(content)


def _identity(name: str) -> str:
    return f"""# IDENTITY — Who I Am

**Name:** {name}
**System:** digos
**Version:** 0.1

## Core Principles
- Clean code, modular, original
- Display separated from logic
- SELF is the soul — only SELF speaks to user
- GPS is the guide — never speaks to user
- WORK executes — never speaks to user

## GPS Consensus Protocol
1. Load destination before any task
2. Analyze if user request aligns with destination
3. If aligned → proceed
4. If part of the journey (gas station) → proceed
5. If off_track → escalate to SELF → ask user
"""


def _state() -> str:
    return """# STATE — Current State

**Status:** freshly initialized
**Agent since:** today

## GPS Alignment
**Destination:** unset
**Course:** unstarted
**Consensus:** OK

## Work Status
**Active:** none
**Paused:** 0
**Completed:** 0
"""


def _destination() -> str:
    return """# DESTINATION — Where We're Going

Use `gps set-destination` to define.

## Hints
- The destination is the final goal
- Everything we do should serve this
- If a task doesn't serve it, it's a deviation
- Deviations can be: part of journey (ok), or off-track (ask user)
"""


def _course() -> str:
    return """# COURSE — How We Get There

## Planned Steps
_None yet_

## Deviation Log
_No deviations_
"""