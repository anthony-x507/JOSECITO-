#!/usr/bin/env python3
"""
DIGOS AIAgent — LLM Core with tool calling + transparency
===========================================================
Re-export from digos_lib/agent_core.py + agent_tools.py
for backwards compatibility.
"""
from digos_lib.agent_core import AIAgent
from digos_lib.agent_tools import AVAILABLE_TOOLS, DANGEROUS_TOOLS, _execute_tool
