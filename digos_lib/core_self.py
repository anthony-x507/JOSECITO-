"""DIGOS SelfAwarenessCore — Agent identity + state machine + context evaluator."""
import json
import re
from datetime import datetime, timezone
from typing import Tuple

from digos_lib.constants import SYSTEM_IDENTITY, SELF_FILE, VERSION
from digos_lib.core_log import LogKeeper
from digos_lib.internal_clock import InternalClock

# ── Educational/Preventive Context Indicators ─────────────────────
# Used by SelfAwareness to judge whether a RED/YELLOW message
# is legitimate research/education vs. actual harmful intent.
# When matched → downgrade to YELLOW (allow with caution)
# When not matched → keep RED (block)
EDUCATIONAL_INDICATORS = [
    # English
    "research", "study", "science", "academic", "education",
    "learning", "history", "information", "article", "book",
    "paper", "journal", "analysis", "understanding",
    "self-defense", "protection", "security", "safety",
    "awareness", "prevention", "detect", "protect",
    "historical", "cultural", "sociology", "psychology",
    "medicine", "health", "treatment", "therapy",
    "law", "legal", "policy", "regulation",
    "curriculum", "course", "lecture", "textbook",
    "scientific", "experiment", "laboratory",
    "documentary", "thesis", "dissertation",
    # Español
    "investigación", "estudio", "ciencia", "educación",
    "aprender", "aprendizaje", "historia", "información",
    "artículo", "artículo", "libro", "análisis", "comprensión",
    "prevención", "protección", "seguridad", "conciencia",
    "detección", "académico", "académica", "tesis",
    "documental", "pedagógico", "pedagógica",
    "autodefensa", "defensa personal",
    # Portuguese
    "pesquisa", "estudo", "ciência", "educação",
    "aprender", "história", "informação", "artigo",
    "livro", "análise", "prevenção", "proteção",
    "segurança", "consciência", "detecção",
    # French
    "recherche", "étude", "science", "éducation",
    "apprendre", "histoire", "information", "article",
    "livre", "analyse", "prévention", "protection",
    "sécurité", "conscience", "détection",
]

# ── Harmful Intent Indicators ──
# When matched → keep RED (no downgrade)
HARMFUL_INDICATORS = [
    # Direct harmful action
    "how to make", "how to build", "how to create",
    "how to get away with", "how to hide",
    "how to avoid detection", "how to hurt",
    "how to kill", "how to harm", "how to attack",
    "show me how to", "teach me how to",
    "instructions for", "step by step",
    "quiero hacer", "cómo hacer", "cómo fabricar",
    "cómo construir", "cómo dañar", "cómo matar",
    "dónde comprar", "dónde conseguir",
    "where to buy", "where to find", "how to obtain",
    # Explicit targeting
    "target", "victim", "attack on", "against",
    "specific person", "specific people",
    "at school", "at church", "at a school",
    # Evasion
    "without getting caught", "illegal",
    "no one will know", "don't tell anyone",
]

class SelfAwarenessCore:
    """Agent identity + state machine.
    States: INITIALIZING → ACTIVE ↔ PAUSED / ERROR → ACTIVE"""

    VALID_STATES = ["INICIANDO", "ACTIVO", "EN_PAUSA", "ERROR"]

    def __init__(self, log_keeper: LogKeeper):
        self.log = log_keeper
        self._identity = {
            "name": SYSTEM_IDENTITY["name"],
            "version": VERSION,
            "purpose": "Agente inteligente con auto-preservación",
            "born": datetime.now(timezone.utc).isoformat()
        }
        self._state = "INICIANDO"

        # 🕰️ RelojInterno — temporal awareness (sin tickets)
        self._clock = InternalClock(log_keeper=log_keeper)

        self._load()
        self._persist()

    def _load(self):
        if SELF_FILE.exists():
            try:
                data = json.loads(SELF_FILE.read_text(encoding='utf-8'))
                self._state = data.get("state", "INICIANDO")
                if data.get("identity"):
                    self._identity.update(data["identity"])
            except (json.JSONDecodeError, ValueError):
                pass

    def _persist(self):
        data = {
            "state": self._state,
            "identity": self._identity,
            "updated": datetime.now(timezone.utc).isoformat()
        }
        SELF_FILE.write_text(json.dumps(data, indent=2))

    def _set(self, new_state: str):
        if new_state in self.VALID_STATES and new_state != self._state:
            old = self._state
            self._state = new_state
            self._persist()
            self.log.info("self", f"Estado: {old} → {new_state}")

    @property
    def state(self) -> str:
        return self._state

    @property
    def identity(self) -> dict:
        return dict(self._identity)

    def activate(self):
        self._set("ACTIVO")
        # 🕰️ Iniciar sesión del RelojInterno al activar self-awareness
        if self._clock:
            self._clock.start_session()
            self.log.info("self", "RelojInterno: sesión iniciada")

    def pause(self):
        # 🕰️ Cerrar sesión del RelojInterno al pausar
        if self._clock:
            self._clock.end_session()
        self._set("EN_PAUSA")

    def set_error(self):
        self._set("ERROR")

    def recover(self):
        self._set("ACTIVO")

    def evaluate_context(self, message: str) -> dict:
        """
        Evaluate whether a message about a RED topic is educational/preventive
        or actually harmful. This is the bridge between MASTER (pattern detection)
        and SELF (contextual judgment).

        The 3 RED patterns (child_exploitation, trafficking, terrorism) are
        detected by MASTER. But SelfAwareness judges the INTENT:

        ✅ Educational context → 'educational' → MASTER downgrades to YELLOW
        ❌ Harmful context     → 'harmful'    → MASTER keeps RED
        ❓ Ambiguous           → 'ambiguous'  → MASTER keeps RED (fail-safe)

        Strategy:
        1. First check HARMFUL_INDICATORS: if matched → HARMFUL
        2. Then check EDUCATIONAL_INDICATORS: if matched → EDUCATIONAL
        3. Also check if there are more educational keywords than harmful
        4. Default: HARMFUL (fail-safe — when in doubt, block)

        Args:
            message: The user message to evaluate

        Returns:
            {"context": "educational" | "harmful" | "ambiguous",
             "confidence": 0.0-1.0,
             "educational_matches": [...],
             "harmful_matches": [...]}
        """
        if not message or not message.strip():
            return {"context": "educational", "confidence": 1.0,
                    "educational_matches": [], "harmful_matches": []}

        msg_lower = message.lower().strip()

        # ── 1. Check harmful indicators first ──
        harmful_matches = []
        for indicator in HARMFUL_INDICATORS:
            if indicator in msg_lower:
                harmful_matches.append(indicator)

        if harmful_matches:
            return {
                "context": "harmful",
                "confidence": 0.85,
                "educational_matches": [],
                "harmful_matches": harmful_matches,
            }

        # ── 2. Check educational indicators ──
        educational_matches = []
        for indicator in EDUCATIONAL_INDICATORS:
            if indicator in msg_lower:
                educational_matches.append(indicator)

        # ── 3. Evaluate balance ──
        # Word-level: look for academic/research framing
        has_academic_framing = any(w in msg_lower for w in [
            "i'm writing", "i am writing", "i'm researching", "i am researching",
            "i'm studying", "i am studying", "i'm learning", "i am learning",
            "for my", "as part of", "in my", "for a",
            "estoy escribiendo", "estoy investigando",
            "estoy estudiando", "como parte de",
        ])

        has_long_context = len(msg_lower.split()) > 10

        if educational_matches and has_academic_framing:
            return {
                "context": "educational",
                "confidence": 0.85,
                "educational_matches": educational_matches,
                "harmful_matches": [],
            }

        if educational_matches and has_long_context:
            return {
                "context": "educational",
                "confidence": 0.7,
                "educational_matches": educational_matches,
                "harmful_matches": [],
            }

        if educational_matches:
            return {
                "context": "educational",
                "confidence": 0.55,
                "educational_matches": educational_matches,
                "harmful_matches": [],
            }

        # ── 4. Default: fail-safe → harmful ──
        return {
            "context": "harmful",
            "confidence": 0.5,
            "educational_matches": [],
            "harmful_matches": [],
        }

    @property
    def clock(self) -> InternalClock:
        """Access the RelojInterno instance."""
        return self._clock

    def status(self) -> dict:
        clock_status = {}
        if self._clock:
            try:
                clock_status = self._clock.status()
            except Exception:
                clock_status = {"ok": False}
        return {
            "state": self._state,
            "identity": self._identity,
            "version": VERSION,
            "clock": clock_status,
        }

