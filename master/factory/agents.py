"""Factory agents — Engineer, Builder, Auditor, Reviewer. All isolated LLMs."""
from typing import Optional
from digos_lib.llm_client import LLMClient


class FactoryAgent:
    """Base class for factory workers."""

    def __init__(self, name: str, llm: LLMClient, role: str):
        self.name = name
        self.llm = llm
        self.role = role

    def work(self, spec: str) -> str:
        return self.llm.ask(f"[{self.role}] Process:\n{spec}", max_tokens=2048)


class Engineer(FactoryAgent):
    def __init__(self, llm: LLMClient):
        super().__init__("engineer", llm, "Engineer — writes specs, returns for verification")


class Builder(FactoryAgent):
    def __init__(self, llm: LLMClient):
        super().__init__("builder", llm, "Builder — implements the spec")


class Auditor(FactoryAgent):
    def __init__(self, llm: LLMClient):
        super().__init__("auditor", llm, "Auditor — security & quality check")


class Reviewer(FactoryAgent):
    def __init__(self, llm: LLMClient):
        super().__init__("reviewer", llm, "Reviewer — final QA")
