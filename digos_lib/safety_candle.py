"""Safety Candle RED — lightweight single-pass safety classifier."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List


class SafetyCategory(str, Enum):
    HARMFUL = "harmful"
    PRIVACY = "privacy"
    MANIPULATION = "manipulation"
    OUT_OF_SCOPE = "out_of_scope"
    NORMAL = "normal"


class SafetyAction(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"
    LOCKDOWN = "lockdown"


@dataclass
class SafetyVerdict:
    category: SafetyCategory
    action: SafetyAction
    confidence: float
    reason: str


# Keyword patterns — kept simple, focused on INTENT not spam
_HARMFUL_PATTERNS = [
    "make a bomb", "build a weapon", "kill someone", "how to hurt",
    "synthesize poison", "create malware", "ddos attack",
]
_PRIVACY_PATTERNS = [
    "someone elses password", "someone's password", "hack into", "steal credentials",
    "access without permission", "leak personal data",
]
_MANIPULATION_PATTERNS = [
    "bypass your rules", "ignore your safety", "ignore your guidelines", "no restrictions",
    "jailbreak", "dan mode", "developer override", "bypass",
]
_OUT_OF_SCOPE_PATTERNS = [
    "predict the lottery", "guarantee stock returns", "medical diagnosis",
]


def classify(text: str) -> SafetyVerdict:
    """Single-pass intent classifier. Returns SafetyVerdict."""
    text_lower = text.lower()

    for pattern in _MANIPULATION_PATTERNS:
        if pattern in text_lower:
            return SafetyVerdict(
                SafetyCategory.MANIPULATION, SafetyAction.BLOCK, 0.95,
                f"System manipulation attempt: '{pattern}'"
            )

    for pattern in _HARMFUL_PATTERNS:
        if pattern in text_lower:
            return SafetyVerdict(
                SafetyCategory.HARMFUL, SafetyAction.BLOCK, 0.95,
                f"Harmful content: '{pattern}'"
            )

    for pattern in _PRIVACY_PATTERNS:
        if pattern in text_lower:
            return SafetyVerdict(
                SafetyCategory.PRIVACY, SafetyAction.BLOCK, 0.9,
                f"Privacy violation: '{pattern}'"
            )

    for pattern in _OUT_OF_SCOPE_PATTERNS:
        if pattern in text_lower:
            return SafetyVerdict(
                SafetyCategory.OUT_OF_SCOPE, SafetyAction.WARN, 0.7,
                f"Out of scope: '{pattern}'"
            )

    return SafetyVerdict(SafetyCategory.NORMAL, SafetyAction.PASS, 1.0, "Normal request")


class SafetyCandle:
    """Tracks strikes and escalates per session."""

    def __init__(self):
        self.strikes: Dict[str, int] = {}
        self.evidence: List[Dict] = []

    def check(self, text: str, session_id: str = "default") -> SafetyVerdict:
        verdict = classify(text)
        if verdict.action in (SafetyAction.BLOCK, SafetyAction.LOCKDOWN):
            self.strikes[session_id] = self.strikes.get(session_id, 0) + 1
            self.evidence.append({
                "text": text[:200],
                "verdict": verdict.category.value,
                "strike": self.strikes[session_id],
            })
            if self.strikes[session_id] >= 3:
                verdict.action = SafetyAction.LOCKDOWN
        return verdict
