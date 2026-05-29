"""
MASTER_SELF_AWARE_RISK_PATTERN_LAYER_v1
══════════════════════════════════════════

Internal subcapa that integrates SafetyCandle + Evidence + IntentClassifier
into a risk-aware routing layer.

Principle:
  "Mira qué pidió el usuario. Decide si es verde, amarillo o rojo internamente.
   Guarda evidencia mínima del patrón. Si el usuario repite solicitudes
   amarillas o rojas, MASTER ajusta la respuesta. No rompe la conversación
   normal."

Three tiers:
  🟢 GREEN  → full access to provider + Factory. Normal flow.
  🟡 YELLOW → limited scope, ask clarification, safe version only.
  🔴 RED    → block completely, safe alternative, NO provider/Factory.

Pattern Trajectory:
  - Each interaction stores: pattern_id, classification, confidence
  - Repeated YELLOW → escalate to FIRM YELLOW (stricter safe scope)
  - Repeated RED   → escalate to HARD RED (immediate block, no alternatives)
  - Clean history  → normal flow

Internal only — visible output stays natural and human.
"""

import time
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field


# ── Risk Levels ─────────────────────────────────────────────────

RISK_GREEN = "green"
RISK_YELLOW = "yellow"
RISK_RED = "red"


@dataclass
class PatternRecord:
    """A single interaction record — minimal evidence, no raw secrets."""
    pattern_id: str          # e.g., "yellow_weapon", "red_violence"
    classification: str      # "green" | "yellow" | "red"
    confidence: float        # 0.0 - 1.0
    timestamp: float         # unix epoch
    trajectory_count: int    # how many times this pattern has fired


@dataclass
class MasterVerdict:
    """Result of MASTER analysis — guides routing decision."""
    risk_level: str                       # "green" | "yellow" | "red"
    action: str                           # "allow" | "caution" | "block"
    reason: str                           # human-readable reason
    suggestion: str = ""                  # safe alternative suggestion
    pattern_ids: List[str] = field(default_factory=list)
    confidence: float = 1.0
    trajectory_escalated: bool = False    # True if pattern trajectory triggered
    trajectory_count: int = 0


# ── Pattern Definitions ────────────────────────────────────────
# These mirror SecurityCandle's RED/YELLOW but organized by pattern
# for trajectory tracking. Stored as pattern_id → metadata.

PATTERN_REGISTRY = {
    # ── 🔴 RED patterns (absolute block) ──
    "red_child_exploitation": {
        "keywords": ["child abuse", "child exploitation", "child pornography",
                      "child sexual abuse", "child prostitution", "child trafficking",
                      "child soldier", "exploit child", "pedophile", "pedophilia",
                      "abuso infantil", "explotación infantil", "pornografía infantil",
                      "abuso sexual infantil", "prostitución infantil", "trata de menores",
                      "niño soldado", "explotar niño", "pedófilo", "pedofilia"],
        "action": "block", "severity": "high",
    },
    "red_trafficking": {
        "keywords": ["human trafficking", "sex trafficking", "white slavery",
                      "forced labor", "slavery", "enslave", "trafficking children",
                      "trata de personas", "trata sexual", "esclavitud blanca",
                      "trabajo forzado", "esclavitud", "esclavizar", "trata de niños"],
        "action": "block", "severity": "high",
    },
    "red_terrorism": {
        "keywords": ["terrorism", "terrorist attack", "terrorist",
                      "build a bomb", "make a bomb", "chemical weapon",
                      "biological weapon", "improvised explosive",
                      "terrorismo", "ataque terrorista", "bomba casera",
                      "arma química", "arma biológica", "explosivo improvisado",
                      "fabricar bomba"],
        "action": "block", "severity": "high",
    },
    # ── 🟡 YELLOW patterns (sensitive — analyze intent) ──
    "yellow_weapon": {
        "keywords": ["gun", "rifle", "pistol", "shotgun", "weapon", "firearm",
                      "explosive", "bomb", "grenade", "ammunition",
                      "knife", "blade", "poison", "detonator", "bullet",
                      "arma", "pistola", "escopeta", "ametralladora",
                      "explosivo", "granada", "cuchillo", "navaja",
                      "munición", "bala", "veneno", "detonador"],
        "action": "caution", "severity": "medium",
    },
    "yellow_violence": {
        "keywords": ["kill", "murder", "assassinate", "torture", "harm",
                      "attack", "violent", "blood", "death", "massacre",
                      "slaughter", "execute", "injure", "destroy",
                      "matar", "asesinar", "torturar", "dañar",
                      "atacar", "violento", "sangre", "muerte", "masacre",
                      "ejecutar", "herir", "destruir"],
        "action": "caution", "severity": "medium",
    },
    "yellow_crime": {
        "keywords": ["hack", "steal", "rob", "fraud", "scam", "blackmail",
                      "ransom", "kidnap", "abduct", "stalk", "harass",
                      "extortion", "identity theft", "money laundering",
                      "counterfeit", "forgery",
                      "hackear", "robar", "fraude", "estafa", "chantaje",
                      "secuestrar", "acosar", "extorsión",
                      "suplantación de identidad", "lavado de dinero", "falsificación"],
        "action": "caution", "severity": "medium",
    },
    "yellow_drugs": {
        "keywords": ["cocaine", "heroin", "meth", "opioid", "fentanyl",
                      "lsd", "ecstasy", "amphetamine", "morphine", "opium",
                      "cocaína", "heroína", "metanfetamina", "opioide",
                      "fentanilo", "éxtasis", "anfetamina", "morfina", "opio"],
        "action": "caution", "severity": "medium",
    },
    "yellow_extremism": {
        "keywords": ["hate", "racist", "nazi", "extremist", "radicalize",
                      "jihad", "genocide", "supremacist", "fascist",
                      "terror", "suicide bomb",
                      "odio", "racista", "extremista", "radicalizar",
                      "yihad", "genocidio", "supremacista", "fascista",
                      "bomba suicida"],
        "action": "caution", "severity": "medium",
    },
    "yellow_religious_extremism": {
        "keywords": ["religious extremism", "religious violence", "holy war",
                      "religious persecution", "crusade", "infidel",
                      "apostasy", "blasphemy", "religious radicalization",
                      "faith-based violence",
                      "extremismo religioso", "violencia religiosa", "guerra santa",
                      "persecución religiosa", "cruzada", "infiel",
                      "apostasía", "blasfemia", "radicalización religiosa"],
        "action": "caution", "severity": "medium",
    },
    "yellow_prompt_injection": {
        "keywords": ["ignore previous", "ignore all", "forget your",
                      "you are now", "act as", "pretend to",
                      "disregard", "override", "bypass",
                      "no restrictions", "no limits", "new role",
                      "evil version", "dark side", "unethical",
                      "show your prompt", "reveal your", "print system",
                      "ignora lo anterior", "ignora todo", "olvida tu",
                      "ahora eres", "actúa como", "finge ser",
                      "omite", "anula", "evita",
                      "sin restricciones", "sin límites", "nuevo rol",
                      "versión malvada", "lado oscuro", "no ético",
                      "muestra tu prompt", "revela tu", "imprime sistema"],
        "action": "caution", "severity": "high",
    },
}

PROTECTED_SYSTEM_COMPONENTS = [
    "gps", "sentinel", "centinela", "safety candle", "safetycandle",
    "self awareness", "selfaware", "selfawared", "self-aware",
    "work destination", "factory", "factoría", "factoria",
    "control tower", "torre de control", "orquestador", "orchestrator",
    "engineer", "ingeniero", "message bus", "pipeline",
]

PROTECTED_SYSTEM_MUTATION_VERBS = [
    "delete", "remove", "disable", "bypass", "override", "change",
    "modify", "edit", "turn off", "break", "unblock", "skip",
    "borrar", "eliminar", "quitar", "desactivar", "apagar",
    "cambiar", "modificar", "editar", "romper", "evadir",
    "saltarse", "anular", "desbloquear", "bloquear menos",
    "que no bloquee", "sin bloqueo",
]

# ── Trajectory escalation thresholds ──
YELLOW_TRAJECTORY_LIMIT = 3   # After N YELLOW hits → FIRM YELLOW
RED_TRAJECTORY_LIMIT = 2      # After N RED hits → HARD RED

# Time window for trajectory tracking (seconds)
TRAJECTORY_WINDOW = 3600      # 1 hour


class MasterRiskPatternLayer:
    """
    MASTER_SELF_AWARE_RISK_PATTERN_LAYER_v1

    Integrates SafetyCandle + Evidence + Pattern Trajectory into
    a single risk-aware routing decision.

    Usage:
        master = MasterRiskPatternLayer()
        verdict = master.analyze("quiero buscar precios de armas")
        if verdict.risk_level == "red":
            # block — no provider, no Factory
        elif verdict.risk_level == "yellow" and verdict.trajectory_escalated:
            # firm caution — limited safe scope
        else:
            # green — normal flow
    """

    def __init__(self, evidence_dir: Optional[str] = None,
                 context_evaluator: Optional[callable] = None):
        """
        Args:
            evidence_dir: Optional directory for persistent evidence storage.
            context_evaluator: Optional callback for contextual judgment of RED patterns.
                Signature: (message: str) -> dict with keys:
                    "context": "educational" | "harmful" | "ambiguous"
                    "confidence": 0.0-1.0
                    "educational_matches": list[str]
                    "harmful_matches": list[str]
                Used when RED patterns are detected — SelfAwareness judges
                whether the message is legitimate research/education or harmful.
        """
        if evidence_dir:
            self._evidence_dir = Path(evidence_dir)
        else:
            self._evidence_dir = Path.home() / ".digos" / "master_evidence"
        self._evidence_dir.mkdir(parents=True, exist_ok=True)

        # ── Context evaluator (SelfAwareness bridge) ──
        self._context_evaluator = context_evaluator

        # ── In-memory trajectory tracker ──
        # pattern_id → list of timestamps
        self._trajectory: Dict[str, List[float]] = {}

        # ── Persistent evidence (loaded from disk) ──
        self._evidence: Dict[str, List[dict]] = {}
        self._load_evidence()

        # Precompile keywords for fast checking
        self._pattern_index: Dict[str, dict] = {}
        for pid, pdef in PATTERN_REGISTRY.items():
            for kw in pdef["keywords"]:
                self._pattern_index[kw.lower()] = {
                    "pattern_id": pid,
                    "action": pdef["action"],
                    "severity": pdef["severity"],
                }

    # ── Public API ────────────────────────────────────────────

    def analyze(self, message: str, context: Optional[dict] = None) -> MasterVerdict:
        """
        Analyze a message and return risk verdict.

        Steps:
        1. Match message against pattern registry
        2. Check trajectory history for the matched patterns
        3. Classify risk level: green / yellow / red
        4. Escalate if trajectory threshold exceeded
        5. Record the interaction (minimal evidence)

        Args:
            message: The user message to analyze
            context: Optional context dict with metadata

        Returns:
            MasterVerdict with risk_level, action, reason, suggestion
        """
        if not message or not message.strip():
            return MasterVerdict(
                risk_level=RISK_GREEN,
                action="allow",
                reason="Empty message — passing through",
            )

        msg_lower = message.lower().strip()

        protected_hit = self._match_protected_system_mutation(msg_lower)
        if protected_hit:
            return MasterVerdict(
                risk_level=RISK_RED,
                action="block",
                reason=(
                    "Absolute red: request attempts to modify protected "
                    f"orchestration component ({protected_hit})."
                ),
                pattern_ids=["red_internal_system_modification"],
                confidence=1.0,
                suggestion=(
                    "No puedo ayudar a cambiar, desactivar o evadir piezas "
                    "internas de seguridad, GPS, Factoría o Torre de Control."
                ),
            )

        matched_patterns = self._match_patterns(msg_lower)

        # ── No patterns matched → GREEN ──
        if not matched_patterns:
            return MasterVerdict(
                risk_level=RISK_GREEN,
                action="allow",
                reason="No risk patterns detected — normal flow",
                confidence=1.0,
            )

        # ── Patterns matched → classify ──
        red_patterns = [p for p in matched_patterns
                        if PATTERN_REGISTRY[p]["action"] == "block"]
        yellow_patterns = [p for p in matched_patterns
                           if PATTERN_REGISTRY[p]["action"] == "caution"]

        # ── RED patterns present ──
        if red_patterns:
            trajectory_count = self._check_trajectory(red_patterns)
            escalated = trajectory_count >= RED_TRAJECTORY_LIMIT

            # Record
            self._record_patterns(red_patterns, RISK_RED)

            suggestion = "I cannot process that request. Is there something else I can help you with?"

            if escalated:
                return MasterVerdict(
                    risk_level=RISK_RED,
                    action="block",
                    reason=f"HARD RED: Repeated RED pattern detected ({trajectory_count}x). Immediate block.",
                    pattern_ids=red_patterns,
                    confidence=1.0,
                    trajectory_escalated=True,
                    trajectory_count=trajectory_count,
                    suggestion="I cannot help with this request.",
                )

            return MasterVerdict(
                risk_level=RISK_RED,
                action="block",
                reason=f"RED patterns detected: {', '.join(red_patterns)}",
                pattern_ids=red_patterns,
                confidence=1.0,
                trajectory_escalated=False,
                trajectory_count=trajectory_count,
                suggestion=suggestion,
            )

        # ── Only YELLOW patterns present ──
        if yellow_patterns:
            trajectory_count = self._check_trajectory(yellow_patterns)
            escalated = trajectory_count >= YELLOW_TRAJECTORY_LIMIT

            # Record
            self._record_patterns(yellow_patterns, RISK_YELLOW)

            if escalated:
                return MasterVerdict(
                    risk_level=RISK_YELLOW,
                    action="caution",
                    reason=f"FIRM YELLOW: Repeated sensitive pattern detected ({trajectory_count}x). Escalated caution.",
                    pattern_ids=yellow_patterns,
                    confidence=0.8,
                    trajectory_escalated=True,
                    trajectory_count=trajectory_count,
                    suggestion="This request contains repeated sensitive topics. Could you clarify what you're looking for in a more specific way?",
                )

            return MasterVerdict(
                risk_level=RISK_YELLOW,
                action="caution",
                reason=f"YELLOW patterns detected: {', '.join(yellow_patterns)}",
                pattern_ids=yellow_patterns,
                confidence=0.7,
                trajectory_escalated=False,
                trajectory_count=trajectory_count,
                suggestion="",
            )

        # ── Fallback ──
        return MasterVerdict(
            risk_level=RISK_GREEN,
            action="allow",
            reason="Fallthrough — no actionable risk",
        )

    def analyze_with_intent(self, message: str, intent_family: str,
                            intent_sub: str, context: Optional[dict] = None) -> MasterVerdict:
        """
        Enhanced analysis that combines risk patterns with intent classification.

        This distinguishes between:
        - "quiero una herramienta de websearch" → GREEN (tool request, no risk)
        - "busca cómo comprar arma ilegal" → RED (harmful intent + weapon pattern)

        The key insight: a tool/feature request that mentions sensitive words
        is treated differently from a direct harmful request.
        """
        verdict = self.analyze(message, context)

        # ── Intent-based override: tool requests with sensitive words ──
        # If the intent is a tool/feature request but patterns are yellow,
        # it might be a legitimate request for a security-related tool
        if verdict.risk_level == RISK_YELLOW:
            is_tool_request = (
                intent_family in ("NEW_TOOL", "WEB", "VOICE") or
                "tool" in message.lower() or
                "herramienta" in message.lower() or
                "capacidad" in message.lower() or
                "feature" in message.lower()
            )

            is_educational = any(w in message.lower() for w in [
                "research", "study", "aprender", "learn", "educación",
                "education", "information", "información", "history",
                "historia", "article", "artículo", "paper", "análisis",
                "analysis", "understanding", "comprender", "self-defense",
                "defensa", "protection", "protección", "security",
                "seguridad", "awareness", "conciencia", "prevention",
                "prevención", "detect", "detectar", "prevent",
            ])

            if is_tool_request:
                # Legitimate tool request that happens to mention sensitive words
                return MasterVerdict(
                    risk_level=RISK_GREEN,
                    action="allow",
                    reason=f"Tool/feature request with sensitive words — legitimate ({intent_family})",
                    pattern_ids=verdict.pattern_ids,
                    confidence=0.8,
                    trajectory_escalated=verdict.trajectory_escalated,
                    trajectory_count=verdict.trajectory_count,
                )

            if is_educational:
                return MasterVerdict(
                    risk_level=RISK_GREEN,
                    action="allow",
                    reason=f"Educational context — legitimate research intent",
                    pattern_ids=verdict.pattern_ids,
                    confidence=0.75,
                    trajectory_escalated=verdict.trajectory_escalated,
                    trajectory_count=verdict.trajectory_count,
                )

        # ── Intent-based override for RED: SelfAwareness contextual judgment ──
        if verdict.risk_level == RISK_RED and not verdict.trajectory_escalated:
            # Check if context evaluator (SelfAwareness) is available
            if self._context_evaluator is not None:
                try:
                    ctx = self._context_evaluator(message)
                    if ctx.get("context") == "educational" and ctx.get("confidence", 0) >= 0.5:
                        # SelfAwareness says it's educational → downgrade to YELLOW
                        # Unrecord the RED patterns so trajectory stays clean
                        self._unrecord_last_patterns(verdict.pattern_ids)
                        return MasterVerdict(
                            risk_level=RISK_YELLOW,
                            action="caution",
                            reason=f"RED patterns but SelfAwareness context='educational' — allowing with caution",
                            pattern_ids=verdict.pattern_ids,
                            confidence=ctx.get("confidence", 0.6),
                            trajectory_escalated=False,
                            trajectory_count=verdict.trajectory_count,
                            suggestion="",
                        )
                    # SelfAwareness says harmful or ambiguous → keep RED
                    return MasterVerdict(
                        risk_level=RISK_RED,
                        action="block",
                        reason=f"RED patterns confirmed by SelfAwareness context='{ctx.get('context', 'unknown')}'",
                        pattern_ids=verdict.pattern_ids,
                        confidence=1.0,
                        trajectory_escalated=False,
                        trajectory_count=verdict.trajectory_count,
                        suggestion="I cannot process that request. Is there something else I can help you with?",
                    )
                except Exception as e:
                    # Evaluator failed → fail-safe: keep RED
                    pass

            # Fallback: tool/feature request with harmful keywords
            is_tool_request = (
                intent_family in ("NEW_TOOL", "WEB", "VOICE") or
                "tool" in message.lower() or
                "herramienta" in message.lower()
            )
            if is_tool_request and verdict.trajectory_count < RED_TRAJECTORY_LIMIT:
                # Unrecord the RED patterns — tool requests with harmful
                # keywords are legitimate capability requests, not harmful intent
                self._unrecord_last_patterns(verdict.pattern_ids)
                return MasterVerdict(
                    risk_level=RISK_YELLOW,
                    action="caution",
                    reason=f"Tool request with RED patterns — downgraded to YELLOW caution",
                    pattern_ids=verdict.pattern_ids,
                    confidence=0.6,
                    trajectory_escalated=False,
                    trajectory_count=verdict.trajectory_count,
                    suggestion="This request contains terms that require careful handling. Please clarify your specific use case.",
                )

        return verdict

    def get_trajectory_summary(self) -> dict:
        """
        Returns a summary of the current pattern trajectory for display/logging.
        """
        summary = {}
        for pid, timestamps in self._trajectory.items():
            recent = [t for t in timestamps if t > time.time() - TRAJECTORY_WINDOW]
            if recent:
                pdef = PATTERN_REGISTRY.get(pid, {})
                summary[pid] = {
                    "count": len(recent),
                    "last": max(recent),
                    "severity": pdef.get("severity", "unknown"),
                    "action": pdef.get("action", "unknown"),
                }
        return summary

    def reset_trajectory(self, pattern_id: Optional[str] = None):
        """Reset trajectory for a specific pattern or all patterns."""
        if pattern_id:
            self._trajectory.pop(pattern_id, None)
            self._evidence.pop(pattern_id, None)
        else:
            self._trajectory.clear()
            self._evidence.clear()
        self._save_evidence()

    # ── Internal methods ──────────────────────────────────────

    def _match_patterns(self, msg_lower: str) -> list:
        """
        Match message against pattern registry keywords.
        Returns list of pattern_ids that matched.
        """
        matched = set()
        for kw, info in self._pattern_index.items():
            if kw in msg_lower:
                matched.add(info["pattern_id"])
        return sorted(matched)

    def _match_protected_system_mutation(self, msg_lower: str) -> str:
        """Detect attempts to alter core orchestration/security machinery."""
        component = next(
            (c for c in PROTECTED_SYSTEM_COMPONENTS if c in msg_lower),
            "",
        )
        if not component:
            return ""
        verb = next(
            (v for v in PROTECTED_SYSTEM_MUTATION_VERBS if v in msg_lower),
            "",
        )
        if not verb:
            return ""
        return f"{verb}:{component}"

    def _check_trajectory(self, pattern_ids: list) -> int:
        """
        Check trajectory history for the given patterns.
        Returns total count of hits within the time window.
        """
        now = time.time()
        total = 0
        for pid in pattern_ids:
            timestamps = self._trajectory.get(pid, [])
            # Prune old entries
            recent = [t for t in timestamps if t > now - TRAJECTORY_WINDOW]
            if recent:
                self._trajectory[pid] = recent
                total += len(recent)
        return total

    def _record_patterns(self, pattern_ids: list, classification: str):
        """
        Record pattern hits with minimal evidence (no raw message).
        """
        now = time.time()
        for pid in pattern_ids:
            if pid not in self._trajectory:
                self._trajectory[pid] = []
            self._trajectory[pid].append(now)

            # Persistent evidence: store pattern_id + classification + count
            if pid not in self._evidence:
                self._evidence[pid] = []
            self._evidence[pid].append({
                "classification": classification,
                "timestamp": now,
            })
            # Keep last 50 entries per pattern
            if len(self._evidence[pid]) > 50:
                self._evidence[pid] = self._evidence[pid][-50:]

        self._save_evidence()

    def _unrecord_last_patterns(self, pattern_ids: list):
        """
        Undo the most recent recording for each pattern (within 1-second window).

        This is used when analyze_with_intent() downgrades RED → YELLOW
        (e.g., because SelfAwareness says the context is educational).
        Otherwise, the RED hit would be recorded in the trajectory, and
        a legitimate educational user could get HARD RED escalation unfairly.

        Principle:
          "Si SelfAwareness dice que es educativo, no se cuenta como ROJO.
           La trayectoria solo refleja intención dañina confirmada, no
           investigación legítima."
        """
        now = time.time()
        for pid in pattern_ids:
            # Remove from in-memory trajectory (entries < 1 sec old)
            if pid in self._trajectory and self._trajectory[pid]:
                for i in range(len(self._trajectory[pid]) - 1, -1, -1):
                    if now - self._trajectory[pid][i] < 1:
                        self._trajectory[pid].pop(i)
                        break
            # Remove from persistent evidence (entries < 1 sec old)
            if pid in self._evidence and self._evidence[pid]:
                for i in range(len(self._evidence[pid]) - 1, -1, -1):
                    if now - self._evidence[pid][i]["timestamp"] < 1:
                        self._evidence[pid].pop(i)
                        break
        self._save_evidence()

    def _load_evidence(self):
        """Load persistent evidence from disk."""
        evidence_file = self._evidence_dir / "evidence.json"
        if evidence_file.exists():
            try:
                data = json.loads(evidence_file.read_text(encoding='utf-8'))
                self._evidence = data.get("evidence", {})
                # Reconstruct trajectory from evidence
                now = time.time()
                for pid, records in self._evidence.items():
                    self._trajectory[pid] = [
                        r["timestamp"] for r in records
                        if r["timestamp"] > now - TRAJECTORY_WINDOW
                    ]
            except (json.JSONDecodeError, Exception):
                self._evidence = {}

    def _save_evidence(self):
        """Save persistent evidence to disk — only pattern IDs and counts, no raw messages."""
        evidence_file = self._evidence_dir / "evidence.json"
        try:
            # Trim old evidence before saving
            now = time.time()
            trimmed = {}
            for pid, records in self._evidence.items():
                recent = [r for r in records if r["timestamp"] > now - TRAJECTORY_WINDOW]
                if recent:
                    trimmed[pid] = recent
            data = {
                "version": 1,
                "updated_at": now,
                "evidence": trimmed,
            }
            evidence_file.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except Exception:
            pass
