"""Camino B — Intent classification for capability gap detection."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict


class IntentType(str, Enum):
    GREETING = "greeting"
    FAREWELL = "farewell"
    QUESTION = "question"
    COMMAND = "command"
    REQUEST_BUILD = "request_build"
    REQUEST_INFO = "request_info"
    UNKNOWN = "unknown"


@dataclass
class Intent:
    type: IntentType
    capability_needed: Optional[str] = None
    confidence: float = 0.0
    raw_text: str = ""


_GREETING_WORDS = ["hola", "hello", "hi", "buenos", "buenas", "hey", "saludos"]
_FAREWELL_WORDS = ["adios", "adios", "bye", "chao", "hasta luego", "nos vemos", "goodbye"]
_BUILD_PATTERNS = [
    "quiero que", "necesito que", "puedes hacer", "puedes crear",
    "i want you to", "i need you to", "can you build", "can you make",
    "create a", "build a", "make a",
]


def classify_intent(text: str) -> Intent:
    """Single-pass intent classifier. Returns Intent."""
    text_lower = text.lower().strip()

    for word in _GREETING_WORDS:
        if text_lower.startswith(word) and len(text_lower) < 30:
            return Intent(IntentType.GREETING, confidence=0.9, raw_text=text)

    for word in _FAREWELL_WORDS:
        if text_lower.startswith(word) and len(text_lower) < 30:
            return Intent(IntentType.FAREWELL, confidence=0.9, raw_text=text)

    for pattern in _BUILD_PATTERNS:
        if pattern in text_lower:
            capability = _detect_capability(text_lower)
            return Intent(IntentType.REQUEST_BUILD, capability, 0.8, text)

    if "?" in text or text_lower.startswith("que ") or text_lower.startswith("what"):
        return Intent(IntentType.QUESTION, confidence=0.7, raw_text=text)

    if any(text_lower.startswith(cmd) for cmd in ["haz ", "create ", "do ", "make ", "run "]):
        return Intent(IntentType.COMMAND, confidence=0.7, raw_text=text)

    return Intent(IntentType.UNKNOWN, confidence=0.0, raw_text=text)


def _detect_capability(text_lower: str) -> Optional[str]:
    """Guess which capability the user is asking for."""
    if "imagen" in text_lower or "image" in text_lower or "picture" in text_lower or "photo" in text_lower:
        return "image_generation"
    if "audio" in text_lower or "voz" in text_lower or "voice" in text_lower or "speech" in text_lower:
        return "stt_audio_input"
    if "traduc" in text_lower or "translat" in text_lower:
        return "translation"
    if "busca" in text_lower or "search" in text_lower or "look up" in text_lower:
        return "web_search"
    if "email" in text_lower or "correo" in text_lower:
        return "email_send"
    return "unknown"
