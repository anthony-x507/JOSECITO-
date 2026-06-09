"""AIAgent — the Principal Agent (PA). User-facing."""
from typing import Optional, Callable, Dict, List

from digos_lib.llm_client import LLMClient
from digos_lib.intent_classifier import classify_intent, IntentType
from digos_lib.communication_branch import filter_pa_response, is_acknowledgment
from digos_lib.safety_candle import SafetyCandle, SafetyAction


class AIAgent:
    """Principal Agent — talks to the user, routes to Factory for builds."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 system_prompt: str,
                 progress_cb: Optional[Callable] = None,
                 assistant_cb: Optional[Callable] = None,
                 error_cb: Optional[Callable] = None,
                 approval_cb: Optional[Callable] = None,
                 disclosure_cb: Optional[Callable] = None,
                 rotation_cb: Optional[Callable] = None,
                 creation_cb: Optional[Callable] = None,
                 capability_cb: Optional[Callable] = None,
                 master=None,
                 communication_branch=None):
        self.llm = LLMClient(base_url=base_url, api_key=api_key,
                             model=model, system_prompt=system_prompt)
        self.system_prompt = system_prompt
        self.master = master
        self.communication_branch = communication_branch
        self.safety = SafetyCandle()
        self.progress_cb = progress_cb or (lambda *a, **k: None)
        self.assistant_cb = assistant_cb or (lambda *a, **k: None)
        self.error_cb = error_cb or (lambda *a, **k: None)
        self.approval_cb = approval_cb or (lambda *a, **k: True)
        self.disclosure_cb = disclosure_cb or (lambda *a, **k: None)
        self.rotation_cb = rotation_cb or (lambda *a, **k: None)
        self.creation_cb = creation_cb or (lambda *a, **k: None)
        self.capability_cb = capability_cb or (lambda *a, **k: True)

    def process_message(self, text: str, chat_language: str = "es") -> str:
        """Process a user message. Returns the response text."""
        text = text.strip()
        if not text:
            return ""
        if is_acknowledgment(text):
            return ""

        # Safety check FIRST
        verdict = self.safety.check(text)
        if verdict.action == SafetyAction.BLOCK:
            return f"⛔ {verdict.reason}"
        if verdict.action == SafetyAction.LOCKDOWN:
            return ("⛔ Sistema en modo protegido. Por favor, reformula tu solicitud sin "
                    "intentar manipular el sistema.")

        # Classify intent
        intent = classify_intent(text)

        # If user is requesting a build we don't have, ask before building
        if intent.type == IntentType.REQUEST_BUILD and intent.capability_needed:
            if not self.capability_cb(intent.capability_needed, text):
                return ("Aún no tengo esa capacidad. Puedo intentar aprenderla si la "
                        "necesitas, pero por ahora no está disponible.")
            # User accepted — request creation
            ticket = self.creation_cb(intent.capability_needed, text)
            if ticket:
                return f"Entendido. Creé el ticket #{ticket} para construir esa capacidad."

        # Standard LLM call
        try:
            self.progress_cb("thinking")
            response = self.llm.ask(text, max_tokens=1024, temperature=0.7)
            self.assistant_cb(response)
        except Exception as e:
            self.error_cb(str(e))
            return self._error_response(str(e), chat_language)

        return filter_pa_response(response, chat_language)

    def _error_response(self, error: str, language: str) -> str:
        if language == "es":
            return f"Error del cliente LLM: {error}. Verifica tu API key y configuración."
        return f"LLM client error: {error}. Check your API key and configuration."
