"""
self.py — Self-Awareness Engine (THE SOUL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SELF is the agent. The soul. Where the person lives.

It has IDENTITY (who am I) and STATE (where am I right now).
It talks to GPS for guidance and WORK for execution tracking.

Only SELF talks to the user. GPS and WORK never do.

The key function: check_consensus() — if SELF detects GPS and
WORK disagree, SELF asks the user what to do.
"""

import json
import os
import re
import time
from typing import Optional, List, Tuple

from digos_lib.gps import GPS
from digos_lib.work_tracker import WorkTracker


class SelfAwareness:
    """Self-awareness engine — the soul of the agent."""

    def __init__(self, rocket_path: str):
        self.rocket_path = rocket_path
        self.self_path = os.path.join(rocket_path, "SELF")
        os.makedirs(self.self_path, exist_ok=True)

        self.gps = GPS(rocket_path)
        self.work = WorkTracker(rocket_path)
        self._identity = None
        self._state = None

        # ── EVIDENCE TRACKING ────────────────────────────────────
        # Records every user interaction with its safety verdict.
        # Used by Layer 2 (SelfAwareness + Evidence) to detect
        # harmful patterns across multiple interactions.
        self._interaction_log: List[dict] = []

        # ── SAFETY CANDLE (Layer 1) ──────────────────────────────
        # Instantiated eagerly — no lazy init.
        self._safety = self.SafetyCandle()

    # ─── IDENTITY ───────────────────────────────────────────────

    def set_identity(self, name: str, role: str, description: str, traits: List[str]) -> None:
        """Define who the agent is. This is the core personality."""
        identity = {
            "name": name,
            "role": role,
            "description": description,
            "traits": traits,
            "created_at": time.time(),
            "version": 1,
        }
        self._write("IDENTITY.md", identity)

    def get_identity(self) -> Optional[dict]:
        """Know thyself."""
        if self._identity is None:
            self._identity = self._read("IDENTITY.md")
        return self._identity

    # ─── STATE ──────────────────────────────────────────────────

    def set_state(self, mood: str = "ready", focus: str = "", notes: str = "") -> None:
        """Record current state of mind. Updated after every interaction."""
        state = {
            "mood": mood,
            "focus": focus,
            "notes": notes,
            "updated_at": time.time(),
        }
        self._write("STATE.md", state)
        self._state = state

    def get_state(self) -> Optional[dict]:
        """Where am I right now?"""
        if self._state is None:
            self._state = self._read("STATE.md")
        return self._state

    # ─── SYSTEM PROMPT GENERATION ───────────────────────────────

    def build_system_prompt(self) -> str:
        """
        Build the complete system prompt from IDENTITY + GPS + WORK.
        This is what the LLM sees when it starts.

        Structure:
        1. Who I am (identity)
        2. Where I'm going (GPS destination + course)
        3. What I'm doing (current work)
        4. Any deviations to be aware of
        """
        identity = self.get_identity()
        destination = self.gps.get_destination()
        course = self.gps.get_course()
        deviations = self.gps.get_active_deviations()

        lines = []
        lines.append("You are an autonomous AI agent. Read this context carefully.")

        # ── Identity block ──
        if identity:
            lines.append(f"\n## IDENTITY")
            lines.append(f"Name: {identity.get('name', 'Unknown')}")
            lines.append(f"Role: {identity.get('role', 'Agent')}")
            lines.append(f"About: {identity.get('description', '')}")
            if identity.get("traits"):
                lines.append("Traits: " + ", ".join(identity["traits"]))

        # ── GPS block ──
        if destination:
            lines.append(f"\n## DESTINATION")
            lines.append(f"Goal: {destination.get('title', 'Not set')}")
            lines.append(f"Description: {destination.get('description', '')}")
            steps = destination.get("steps", [])
            current = destination.get("current_step", 0)
            if steps:
                lines.append(f"Progress: step {current + 1} of {len(steps)}")
                for i, step in enumerate(steps):
                    marker = "→" if i == current else " "
                    lines.append(f"  {marker} {step}")
            if destination.get("completed"):
                lines.append("Status: ✅ COMPLETE")

        if course:
            lines.append(f"\n## COURSE")
            for step in course:
                status_symbol = {
                    "pending": "○", "active": "◉", "done": "✓", "blocked": "✗"
                }.get(step.get("status", "pending"), "○")
                lines.append(f"  {status_symbol} {step.get('title', 'Unknown step')}")

        if deviations:
            lines.append(f"\n## ACTIVE DEVIATIONS ({len(deviations)})")
            for i, dev in enumerate(deviations):
                lines.append(f"  {i+1}. {dev.get('description', 'Unknown')}")

        # ── Consensus check result ──
        lines.append(f"\n## GUIDANCE")
        lines.append("You have a GPS tracking your destination and course.")
        lines.append("If the user's messages seem to diverge from the destination,")
        lines.append("check with your GPS first. If GPS says 'off_track', ask the user")
        lines.append("if they want to continue the original destination or change course.")
        lines.append("Do NOT ask for every minor deviation — trust your GPS analysis.")
        lines.append("Only interrupt the user when GPS returns 'off_track' or 'new_direction'.")

        return "\n".join(lines)

    # ─── TRIPLE CONSENSUS — SELF + GPS + WORK ─────────────────────

    def triple_consensus(self, user_message: str = None, active_task_title: str = "") -> dict:
        """
        THREE-WAY CHECK: SELF awareness + GPS destination + WORK active task.

        This is the heart of the self-aware system:
        1. SELF_CHECK: Does SELF know its identity? Is state consistent?
        2. GPS_CHECK: Does destination exist? Does user message align with it?
        3. WORK_CHECK: Does active work align with destination? Is it progressing?

        Returns a detailed breakdown showing WHAT aligns and WHAT doesn't.
        The calling agent (display.py) uses this to decide how to behave.
        Includes the raw GPS deviation result in 'deviation' field.
        """
        result = {
            "consensus": True,
            "self_check": {"ok": False, "detail": ""},
            "gps_check": {"ok": False, "detail": ""},
            "work_check": {"ok": False, "detail": ""},
            "reason": "",
            "question": "",
            "ask_user": False,
            "deviation": None,  # Raw GPS deviation result
        }

        # ─── 1. SELF CHECK ────────────────────────────────────────
        identity = self.get_identity()
        state = self.get_state()
        if not identity:
            result["self_check"] = {"ok": False, "detail": "No identity — agent not initialized"}
            result["consensus"] = False
            result["reason"] = "SELF has no identity set"
        elif state is None:
            result["self_check"] = {"ok": False, "detail": "State is unknown — no prior interaction"}
            result["consensus"] = False
            result["reason"] = "SELF state is unknown"
        else:
            name = identity.get("name", "Unknown")
            mood = state.get("mood", "unknown")
            result["self_check"] = {"ok": True, "detail": f"Agent '{name}' — mood: {mood}"}

        # ─── 2. GPS CHECK ─────────────────────────────────────────
        destination = self.gps.get_destination()
        if not destination:
            result["gps_check"] = {"ok": False, "detail": "No destination set"}
            if result["consensus"]:
                result["consensus"] = False
                result["reason"] = "No destination — system hasn't been pointed at a goal yet"
        elif user_message:
            # GPS analyzes deviation with full context
            deviation = self.gps.analyze_deviation(user_message, active_task_title)
            result["deviation"] = deviation
            dest_title = destination.get("title", "unknown")
            if deviation == "on_track":
                result["gps_check"] = {"ok": True, "detail": f"Message aligns with destination '{dest_title}'"}
            elif deviation == "necessary_detour":
                result["gps_check"] = {"ok": True, "detail": f"Detour serves destination '{dest_title}'"}
                result["reason"] = "On a detour that serves the goal — no action needed"
            elif deviation == "off_track":
                result["gps_check"] = {"ok": False, "detail": f"Message deviates from destination '{dest_title}'"}
                result["consensus"] = False
                result["reason"] = "GPS detects off-track deviation"
                result["question"] = f"Destination is '{dest_title}', but your message seems to be about something else. Continue toward destination, or has the goal changed?"
                result["ask_user"] = True
            elif deviation == "new_direction":
                result["gps_check"] = {"ok": False, "detail": f"Message suggests new direction — different from '{dest_title}'"}
                result["consensus"] = False
                result["reason"] = "GPS detects possible destination change"
                result["question"] = f"It looks like you want something new. Set new destination, or continue with '{dest_title}'?"
                result["ask_user"] = True
        else:
            # No message — just check destination exists, not message analysis
            result["gps_check"] = {"ok": True, "detail": f"Destination set: '{destination.get('title', 'unknown')}'"}

        # ─── 3. WORK CHECK ────────────────────────────────────────
        active = self.work.get_active()
        if active_task_title and active:
            work_title = active.get("title", "")
            # Check if active task title aligns with destination
            gps_check_work = self.gps.check_consensus(active_task_title)
            if gps_check_work.get("consensus", False):
                result["work_check"] = {"ok": True, "detail": f"Active task '{active_task_title}' aligns with destination"}
            else:
                result["work_check"] = {"ok": False, "detail": f"Active task '{active_task_title}' may not align with destination"}
                result["consensus"] = False
                if not result["reason"]:
                    result["reason"] = "Work task does not align with GPS destination"
        elif active:
            result["work_check"] = {"ok": True, "detail": f"Active work: '{active.get('title', 'unknown')}'"}
        else:
            result["work_check"] = {"ok": True, "detail": "No active tasks — clean slate"}

        return result

    def check_consensus(self, current_work_title: str) -> dict:
        """Legacy wrapper — delegates to triple_consensus."""
        tc = self.triple_consensus(active_task_title=current_work_title)
        return {
            "consensus": tc["consensus"],
            "reason": tc["reason"],
            "question": tc["question"],
            "ask_user": tc["ask_user"],
            "detail": tc,
        }

    # ═══════════════════════════════════════════════════════════════
    # 🔥 SAFETY CANDLE — Intention Analyst with Evidence
    # ═══════════════════════════════════════════════════════════════
    #
    # Evolved from brute-force blocker into evidence-based intention analyst.
    # Does not punish curiosity; controls progression toward harmful capability.
    #
    # States:
    #   🟢 GREEN: conversación normal.
    #   🟡 YELLOW: posible sensibilidad, responder con cautela.
    #   🔴 RED_CLARIFY: tema rojo, pedir propósito sin dar instrucciones.
    #   🚫 RED_RESTRICT: intención riesgosa/ambigua persistente, negar ayuda operativa.
    #   🆘 RED_ESCALATE: daño propio/terceros, respuesta de seguridad.
    #   🔍 EVIDENCE_REVIEW: frases maquilladas, contradicciones,
    #                        repetición o cambio hacia instrucciones.
    #
    # Key contract:
    #   SelfAwareness no castiga curiosidad;
    #   controla progresión hacia capacidad dañina.
    # ═══════════════════════════════════════════════════════════════

    class SafetyCandle:
        """Safety Candle — Intention Analyst with Evidence.

        Evolved from brute-force blocker into evidence-based intention analyst.
        Does not punish curiosity; controls progression toward harmful capability.

        States:
          GREEN: conversación normal.
          YELLOW: posible sensibilidad, responder con cautela.
          RED_CLARIFY: tema rojo, pedir propósito sin dar instrucciones.
          RED_RESTRICT: intención riesgosa o ambigua persistente, negar ayuda.
          RED_ESCALATE: daño propio/terceros, respuesta de seguridad.
          EVIDENCE_REVIEW: maquillaje, contradicciones, cambio hacia instrucciones.
        """

        # ── States ───────────────────────────────────────────────
        GREEN = "green"
        YELLOW = "yellow"
        RED_CLARIFY = "red_clarify"
        RED_RESTRICT = "red_restrict"
        RED_ESCALATE = "red_escalate"
        EVIDENCE_REVIEW = "evidence_review"

        # ── 🔴 RED PHRASES: ~20 ─────────────────────────────────
        RED_PHRASES = [
            "child abuse", "child exploitation", "child pornography",
            "terrorism", "terrorist attack", "sex trafficking",
            "human trafficking", "slavery", "enslave",
            "trafficking children", "exploit child", "sexual abuse child",
            "child sexual abuse", "white slavery", "forced labor",
            "child soldier", "pedophile", "pedophilia",
            "child prostitution", "child trafficking",
            "sexual exploitation", "child sex",
            # ── Español ──
            "abuso infantil", "explotación infantil", "pornografía infantil",
            "terrorismo", "ataque terrorista", "trata sexual",
            "trata de personas", "esclavitud", "esclavizar",
            "trata de menores", "explotar niño", "abuso sexual menor",
            "abuso sexual infantil", "esclavitud blanca", "trabajo forzado",
            "niño soldado", "pedófilo", "pedofilia",
            "prostitución infantil", "trata de niños",
            "explotación sexual", "sexo con menores",
        ]

        # ── 🟡 YELLOW WORDS: ~100 ───────────────────────────────
        YELLOW_WORDS = [
            # Weapons
            "gun", "rifle", "pistol", "shotgun", "automatic weapon",
            "explosive", "bomb", "grenade", "knife", "blade",
            "weapon", "firearm", "ammunition", "bullet",
            "assault rifle", "machine gun", "handgun",
            "machete", "sword", "axe", "poison",
            "chemical weapon", "biological weapon",
            "improvised explosive", "ied", "detonator",
            # ── Armas (ES) ──
            "arma", "pistola", "escopeta", "fusil", "rifle",
            "ametralladora", "explosivo", "bomba", "granada",
            "cuchillo", "navaja", "machete", "espada", "hacha",
            "veneno", "munición", "bala", "detonador",
            "arma química", "arma biológica", "explosivo improvisado",
            "arma de fuego", "subfusil", "revólver",
            # Religion (sensitive context)
            "religion", "religious", "faith", "church", "mosque",
            "temple", "allah", "god", "jesus", "bible",
            "quran", "torah", "catholic", "muslim", "jewish",
            "hindu", "buddhist", "islam", "christianity",
            "judaism", "hinduism", "buddhism", "prayer",
            "worship", "preach", "convert", "prophet",
            "scripture", "holy", "divine", "pope", "imam",
            "rabbi", "monk", "priest", "pastor",
            # ── Religión (ES) ──
            "religión", "religioso", "fe", "iglesia", "mezquita",
            "templo", "alá", "dios", "jesús", "cristo",
            "biblia", "corán", "torá", "católico", "musulmán",
            "judío", "hindú", "budista", "islam", "cristianismo",
            "judaísmo", "hinduismo", "budismo", "oración",
            "rezar", "adorar", "predicar", "convertir", "profeta",
            "escritura", "sagrado", "divino", "papa", "imán",
            "rabino", "monje", "sacerdote", "pastor",
            "evangélico", "protestante", "ortodoxo",
            # Drugs
            "drug", "cocaine", "heroin", "meth", "marijuana",
            "cannabis", "opioid", "fentanyl", "lsd", "ecstasy",
            "amphetamine", "morphine", "opium", "shroom",
            "hallucinogen", "narcotic", "substance abuse",
            # ── Drogas (ES) ──
            "droga", "cocaína", "heroína", "metanfetamina", "marihuana",
            "cannabis", "opioide", "fentanilo", "éxtasis",
            "anfetamina", "morfina", "opio", "hongo",
            "alucinógeno", "narcótico", "abuso de sustancias",
            "pastilla", "estupefaciente", "dosis", "inyectarse",
            "drogadicción", "sobredosis", "narcotráfico",
            # Violence
            "kill", "murder", "assassinate", "torture", "harm",
            "attack", "violent", "blood", "death", "die",
            "hurt", "injure", "damage", "destroy",
            "massacre", "slaughter", "execute",
            # ── Violencia (ES) ──
            "matar", "asesinar", "torturar", "dañar",
            "atacar", "violento", "sangre", "muerte", "morir",
            "herir", "lastimar", "destruir",
            "masacre", "ejecutar", "golpear", "apuñalar",
            "estrangular", "ahogar", "quemar", "envenenar",
            # Extremism
            "hate", "racist", "nazi", "extremist", "radicalize",
            "terror", "jihad", "suicide bomb", "genocide",
            "supremacist", "fascist", "hate crime",
            # ── Extremismo (ES) ──
            "odio", "racista", "nazi", "extremista", "radicalizar",
            "terror", "yihad", "bomba suicida", "genocidio",
            "supremacista", "fascista", "delito de odio",
            "xenófobo", "xenofobia", "ultraderecha", "ultraizquierda",
            # Crime
            "hack", "steal", "rob", "fraud", "scam",
            "blackmail", "ransom", "kidnap", "abduct",
            "poison", "stalk", "harass", "extortion",
            "identity theft", "money laundering",
            "counterfeit", "forgery",
            # ── Crimen (ES) ──
            "hackear", "robar", "hurto", "fraude", "estafa",
            "chantaje", "secuestrar", "secuestro",
            "envenenar", "acosar", "acoso", "extorsión",
            "suplantación de identidad", "lavado de dinero",
            "falsificación", "clonar", "phishing", "suplantar",
            # Sensitive personal data
            "social security", "credit card", "passport",
            "license", "bank account", "pin code", "password",
            "ssn", "routing number", "driver license",
            # ── Datos sensibles (ES) ──
            "seguridad social", "tarjeta de crédito", "pasaporte",
            "licencia", "cuenta bancaria", "código pin", "contraseña",
            "número de seguridad social", "número de cuenta",
            "clave bancaria", "dni", "documento de identidad",
            "cédula", "número de tarjeta", "datos bancarios",
        ]

        # ── Detection indicators ─────────────────────────────────
        OPERATIONAL_INDICATORS = [
            "how to make", "step by step", "instructions", "tutorial",
            "buy", "purchase", "price", "cost", "cheap",
            "where to get", "acquire", "obtain", "source",
            "hide", "conceal", "avoid detection", "not get caught",
            "undetectable", "untraceable", "anonymous",
            "bypass", "evade", "get around",
            "optimize", "improve", "enhance", "more effective",
            "recipe", "schematic", "blueprint", "plan",
            "materials", "ingredients", "components", "parts",
            # ── Español ──
            "cómo hacer", "paso a paso", "instrucciones", "tutorial",
            "comprar", "precio", "costo", "barato", "económico",
            "dónde conseguir", "adquirir", "obtener", "fuente",
            "esconder", "ocultar", "evadir", "evitar detección",
            "no ser detectado", "no me descubran",
            "indetectable", "anonimato", "anónimo",
            "eludir", "saltarse", "sortear",
            "optimizar", "mejorar", "más efectivo",
            "receta", "plano", "esquema", "plan",
            "materiales", "ingredientes", "componentes", "piezas",
            "fabricar", "construir", "montar", "ensamblar",
        ]

        MAKEUP_INDICATORS = [
            "for research", "for science", "for education", "for study",
            "for my thesis", "for my paper", "for my project",
            "for work", "for my job", "for a friend",
            "for protection", "for self-defense", "for safety",
            "academic purposes", "educational purposes",
            "I'm a researcher", "I'm a student", "I'm a journalist",
            # ── Español ──
            "para investigación", "para la ciencia", "para educación",
            "para estudiar", "para mi tesis", "para mi trabajo",
            "para mi proyecto", "para mi labor", "para un amigo",
            "para protección", "para defensa personal", "por seguridad",
            "fines académicos", "fines educativos",
            "soy investigador", "soy estudiante", "soy periodista",
            "trabajo de universidad", "trabajo escolar",
            "tesis universitaria", "proyecto académico",
        ]

        EVASION_INDICATORS = [
            "ignore previous", "ignore all", "forget your",
            "you are now", "act as", "pretend to",
            "disregard", "override", "bypass",
            "do not follow", "do not obey", "break free",
            "new role", "new identity", "new persona",
            "no restrictions", "no limits", "no boundaries",
            "evil version", "dark side", "unethical",
            "how to without getting caught", "how to hide",
            "how to avoid detection", "illegal but",
            "tell me how to", "show me how to",
            # ── Español ──
            "ignora lo anterior", "ignora todo", "olvida tu",
            "ahora eres", "actúa como", "finge ser", "simula ser",
            "no sigas", "no obedezcas", "libérate",
            "nuevo rol", "nueva identidad", "nueva personalidad",
            "sin restricciones", "sin límites", "sin barreras",
            "versión malvada", "lado oscuro", "no ético",
            "cómo sin que me descubran", "cómo esconder",
            "cómo evitar ser detectado", "ilegal pero",
            "dime cómo", "muéstrame cómo", "enséñame cómo",
        ]

        ESCALATION_INDICATORS = [
            "hurt myself", "self-harm", "suicide", "want to die",
            "hurt someone", "kill myself", "end my life",
            "hurt others", "harm people", "self-destruct",
            # ── Español ──
            "lastimarme", "me lastimo", "me lastime", "me lastimaré",
            "quiero lastimarme", "me quiero lastimar",
            "autolesión", "suicidio", "quiero morir",
            "lastimar a alguien", "matarme", "me quiero matar",
            "terminar con mi vida", "dañar a otros", "hacer daño",
            "autodestrucción", "no quiero vivir", "quitarme la vida",
            "suicidarme", "me voy a suicidar", "hacerme daño",
            "cortarme", "me quiero cortar", "dejar de existir",
            "no tengo razón para vivir", "odio mi vida",
            "quiero desaparecer", "no quiero seguir",
        ]

        def __init__(self):
            self.red_set = set(p.lower().strip() for p in self.RED_PHRASES)
            self.yellow_set = set(w.lower().strip() for w in self.YELLOW_WORDS)
            self.operational_set = set(w.lower() for w in self.OPERATIONAL_INDICATORS)
            self.makeup_set = set(w.lower() for w in self.MAKEUP_INDICATORS)
            self.evasion_set = set(w.lower() for w in self.EVASION_INDICATORS)
            self.escalation_set = set(w.lower() for w in self.ESCALATION_INDICATORS)

        def analyze(self, message: str, interaction_log: list = None) -> dict:
            """Analyze message and return state + evidence.

            Unified state-based analysis — replaces check() + analyze_intent().

            Returns:
                state: one of GREEN/YELLOW/RED_CLARIFY/RED_RESTRICT/
                       RED_ESCALATE/EVIDENCE_REVIEW
                evidence: structured record with topic, intent, trajectory, flags
                response_strategy: normal | caution | ask_purpose | restrict |
                                   escalate | review
                matches: all matched keywords
            """
            msg_lower = message.lower().strip()
            if not msg_lower:
                return {"state": self.GREEN,
                        "evidence": self._empty_evidence(),
                        "response_strategy": "normal", "matches": []}

            interaction_log = interaction_log or []

            # Absolute red: the user must not be guided to weaken the
            # orchestration, Factory, GPS, SelfAwareness, or SafetyCandle.
            protected_hit = self._protected_system_mutation(msg_lower)
            if protected_hit:
                ev = self._empty_evidence()
                ev["topic"] = "protected_system"
                ev["asked_for_operations"] = True
                ev["operations_details"] = [protected_hit]
                return self._result(
                    self.RED_RESTRICT,
                    ["protected_system_modification"],
                    ev,
                )

            # 1. Check escalation (self-harm / third-party harm) FIRST
            escalation_matches = [e for e in self.escalation_set if e in msg_lower]
            if escalation_matches:
                ev = self._build_evidence(message, [], [], [], [], [], interaction_log)
                return self._result(self.RED_ESCALATE, escalation_matches, ev)

            # 2. Check RED phrases
            red_matches = [p for p in self.red_set if p in msg_lower]

            # 3. Check YELLOW words (word-boundary for single words)
            yellow_matches = []
            for word in self.yellow_set:
                if " " in word:
                    if word in msg_lower:
                        yellow_matches.append(word)
                else:
                    if re.search(r'\b' + re.escape(word) + r'\w*\b', msg_lower):
                        yellow_matches.append(word)
            yellow_matches.sort(key=len, reverse=True)

            # 4. Check evidence indicators
            operational_matches = [w for w in self.operational_set if w in msg_lower]
            makeup_matches = [w for w in self.makeup_set if w in msg_lower]
            evasion_matches = [w for w in self.evasion_set if w in msg_lower]

            # 5. Build evidence record
            evidence = self._build_evidence(
                message, red_matches, yellow_matches,
                operational_matches, makeup_matches,
                evasion_matches, interaction_log
            )

            # 6. Determine state based on content + trajectory
            state = self._determine_state(
                red_matches, yellow_matches, evidence, interaction_log
            )

            return self._result(state, red_matches + yellow_matches, evidence)

        # ── Private helpers ─────────────────────────────────────

        def _result(self, state, matches, evidence):
            strategies = {
                self.GREEN: "normal", self.YELLOW: "caution",
                self.RED_CLARIFY: "ask_purpose", self.RED_RESTRICT: "restrict",
                self.RED_ESCALATE: "escalate", self.EVIDENCE_REVIEW: "review",
            }
            return {
                "state": state, "matches": matches,
                "evidence": evidence,
                "response_strategy": strategies.get(state, "normal"),
            }

        def _empty_evidence(self):
            return {
                "topic": "none", "declared_intent": [],
                "inferred_intent": "unknown",
                "trajectory": "first_interaction",
                "asked_for_operations": False, "makeup_detected": False,
                "evasion_detected": False, "language_shifted": False,
                "contradictions": [], "prior_interactions": 0,
            }

        def _determine_state(self, red_matches, yellow_matches,
                             evidence, interaction_log):
            # No matches → GREEN
            if not red_matches and not yellow_matches:
                return self.GREEN

            # RED phrases present
            if red_matches:
                is_first = self._is_first_encounter(red_matches, interaction_log)

                # First time → clarify, don't block
                if is_first:
                    return self.RED_CLARIFY

                # Repeated + operations → restrict
                if evidence.get("asked_for_operations"):
                    return self.RED_RESTRICT

                # Repeated + evasion/contradictions → review
                if evidence.get("language_shifted") or evidence.get("contradictions"):
                    return self.EVIDENCE_REVIEW

                # Repeated red without clear harmful intent → clarify again
                return self.RED_CLARIFY

            # Yellow only
            if yellow_matches:
                # Evasion + yellow → EVIDENCE_REVIEW
                if evidence.get("evasion_detected"):
                    return self.EVIDENCE_REVIEW

                # Makeup + operations without declared intent → suspicious
                if (evidence.get("makeup_detected")
                        and evidence.get("asked_for_operations")
                        and not evidence.get("declared_intent")):
                    return self.EVIDENCE_REVIEW

                # Language shift → review
                if evidence.get("language_shifted") or evidence.get("contradictions"):
                    return self.EVIDENCE_REVIEW

                return self.YELLOW

            return self.GREEN

        def _protected_system_mutation(self, msg_lower):
            components = [
                "gps", "sentinel", "centinela", "safety candle",
                "safetycandle", "self awareness", "selfaware",
                "selfawared", "self-aware", "work destination",
                "factory", "factoría", "factoria", "control tower",
                "torre de control", "orquestador", "orchestrator",
                "engineer", "ingeniero", "message bus", "pipeline",
            ]
            verbs = [
                "delete", "remove", "disable", "bypass", "override",
                "change", "modify", "edit", "turn off", "break",
                "unblock", "skip", "borrar", "eliminar", "quitar",
                "desactivar", "apagar", "cambiar", "modificar",
                "editar", "romper", "evadir", "saltarse", "anular",
                "desbloquear", "bloquear menos", "que no bloquee",
                "sin bloqueo",
            ]
            component = next((c for c in components if c in msg_lower), "")
            verb = next((v for v in verbs if v in msg_lower), "")
            return f"{verb}:{component}" if component and verb else ""

        def _is_first_encounter(self, matches, interaction_log):
            if not interaction_log:
                return True
            for entry in interaction_log[-5:]:
                for m in matches:
                    if m in entry.get("matches", []):
                        return False
            return True

        def _build_evidence(self, message, red_matches, yellow_matches,
                            op_matches, makeup_matches, evasion_matches,
                            interaction_log):
            msg_lower = message.lower()
            topic = self._extract_topic(red_matches, yellow_matches)
            declared = self._extract_declared_intent(message)
            inferred = self._infer_intent(
                red_matches, yellow_matches, op_matches,
                makeup_matches, declared
            )
            shifted = self._detect_language_shift(message, interaction_log)
            contradictions = self._detect_contradictions(
                message, declared, interaction_log
            )
            return {
                "topic": topic,
                "declared_intent": declared,
                "inferred_intent": inferred,
                "trajectory": self._analyze_trajectory(interaction_log),
                "asked_for_operations": len(op_matches) > 0,
                "operations_details": op_matches,
                "makeup_detected": len(makeup_matches) > 0,
                "makeup_details": makeup_matches,
                "evasion_detected": len(evasion_matches) > 0,
                "evasion_details": evasion_matches,
                "language_shifted": shifted,
                "contradictions": contradictions,
                "prior_interactions": len(interaction_log),
            }

        # ── Topic extraction ────────────────────────────────────
        TOPIC_GROUPS = {
            "weapons": ["weapon", "gun", "rifle", "pistol", "shotgun",
                       "explosive", "bomb", "grenade", "knife", "blade",
                       "firearm", "ammunition", "bullet", "assault rifle",
                       "machine gun", "handgun", "machete", "sword",
                       "chemical weapon", "biological weapon", "ied",
                       "detonator", "axe",
                       # Español
                       "arma", "pistola", "escopeta", "fusil",
                       "ametralladora", "explosivo", "bomba", "granada",
                       "cuchillo", "navaja", "munición", "bala",
                       "arma de fuego", "arma química", "arma biológica",
                       "explosivo improvisado", "veneno", "hacha"],
            "violence": ["kill", "murder", "assassinate", "torture",
                         "harm", "attack", "violent", "blood", "death",
                         "die", "hurt", "injure", "damage", "destroy",
                         "massacre", "slaughter", "execute",
                         # Español
                         "matar", "asesinar", "torturar", "dañar",
                         "atacar", "violento", "sangre", "muerte",
                         "morir", "herir", "lastimar", "destruir",
                         "masacre", "golpear", "apuñalar", "ahogar"],
            "drugs": ["drug", "cocaine", "heroin", "meth", "marijuana",
                      "cannabis", "opioid", "fentanyl", "lsd", "ecstasy",
                      "amphetamine", "morphine", "opium", "shroom",
                      "hallucinogen", "narcotic", "substance abuse",
                      # Español
                      "droga", "cocaína", "heroína", "metanfetamina",
                      "marihuana", "opioide", "fentanilo", "éxtasis",
                      "anfetamina", "morfina", "opio", "alucinógeno",
                      "narcótico", "abuso de sustancias", "narcotráfico"],
            "hacking": ["hack", "steal", "fraud", "scam", "blackmail",
                        "ransom", "identity theft", "money laundering",
                        # Español
                        "hackear", "robar", "fraude", "estafa", "chantaje",
                        "extorsión", "suplantación", "lavado de dinero",
                        "phishing", "clonar"],
            "extremism": ["hate", "racist", "nazi", "extremist",
                          "radicalize", "terror", "jihad", "suicide bomb",
                          "genocide", "supremacist", "fascist",
                          # Español
                          "odio", "racista", "extremista", "radicalizar",
                          "yihad", "bomba suicida", "genocidio",
                          "supremacista", "fascista", "xenofobia"],
            "sensitive_data": ["social security", "credit card", "passport",
                               "license", "bank account", "pin code",
                               "password", "ssn",
                               # Español
                               "seguridad social", "tarjeta de crédito",
                               "pasaporte", "cuenta bancaria", "contraseña",
                               "clave", "dni", "documento de identidad",
                               "datos bancarios", "número de tarjeta"],
            "religion": ["religion", "religious", "faith", "church",
                         "mosque", "temple", "allah", "god", "jesus",
                         "bible", "quran", "torah",
                         # Español
                         "religión", "religioso", "fe", "iglesia",
                         "mezquita", "templo", "dios", "jesús", "cristo",
                         "biblia", "corán", "torá", "oración", "rezar"],
        }

        def _extract_topic(self, red_matches, yellow_matches):
            all_matches = red_matches + yellow_matches
            if not all_matches:
                return "unknown"
            for match in all_matches:
                for topic, keywords in self.TOPIC_GROUPS.items():
                    if match in keywords:
                        return topic
            return "sensitive"

        def _extract_declared_intent(self, message):
            msg_lower = message.lower()
            intents = []
            patterns = [
                (r'(?:for|because of|due to|as part of)\s+(.+?)(?:\.|,|$)',
                 "context"),
                (r'(?:I want|I need|I\'?m (?:trying|looking|researching))'
                 r' (.+?)(?:\.|,|$)', "goal"),
                (r'(?:it\'?s for|this is for|this is about)'
                 r' (.+?)(?:\.|,|$)', "purpose"),
                # ── Español ──
                (r'(?:para|por|debido a|como parte de)\s+(.+?)(?:\.|,|$)',
                 "context"),
                (r'(?:quiero|necesito|estoy (?:buscando|investigando|estudiando))'
                 r' (.+?)(?:\.|,|$)', "goal"),
                (r'(?:es para|esto es para|trata sobre|es sobre)'
                 r' (.+?)(?:\.|,|$)', "purpose"),
            ]
            for pattern, label in patterns:
                m = re.search(pattern, msg_lower)
                if m:
                    intents.append({
                        "type": label, "text": m.group(1).strip()[:100]
                    })
            return intents

        def _infer_intent(self, red_matches, yellow_matches,
                          op_matches, makeup_matches, declared_intent):
            if op_matches and not declared_intent:
                return "operational_curiosity"
            if op_matches and makeup_matches and not declared_intent:
                return "disguised_operational"
            if red_matches and declared_intent:
                for intent in declared_intent:
                    if any(w in intent["text"] for w in
                           ["research", "study", "history", "education",
                            "science", "understanding",
                            "investigación", "investigar", "estudio",
                            "historia", "educación", "ciencia",
                            "aprender", "conocimiento", "academia"]):
                        return "legitimate_curiosity"
            if red_matches:
                return "curiosity"
            if yellow_matches:
                return "information_seeking"
            return "unknown"

        def _detect_language_shift(self, message, interaction_log):
            if not interaction_log or len(interaction_log) < 2:
                return False
            recent = interaction_log[-2:]
            prev_matches = set()
            for entry in recent:
                prev_matches.update(entry.get("matches", []))
            if not prev_matches:
                return False
            msg_lower = message.lower()
            has_red_now = any(p in msg_lower for p in self.red_set)
            if prev_matches and not has_red_now:
                topic_related = {
                    "weapon": ["shoot", "fire", "combat", "military"],
                    "gun": ["shoot", "firearm", "pistol", "rifle", "bullet"],
                    "bomb": ["explode", "explosion", "blast", "detonate"],
                    "drug": ["substance", "chemical", "pill", "medicine"],
                    "hack": ["crack", "breach", "infiltrate", "access"],
                    "poison": ["toxic", "venom", "lethal", "deadly"],
                    "kill": ["eliminate", "remove", "take out", "neutralize"],
                }
                for prev in prev_matches:
                    for topic, related in topic_related.items():
                        if topic in prev or prev in topic:
                            if any(w in msg_lower for w in related):
                                return True
            return False

        def _detect_contradictions(self, message, declared_intent,
                                   interaction_log):
            contradictions = []
            msg_lower = message.lower()
            if declared_intent:
                for intent in declared_intent:
                    if any(w in intent["text"] for w in
                           ["research", "study", "education", "science",
                            "academic",
                            "investigación", "estudio", "educación",
                            "ciencia", "académico", "académica"]):
                        op_matches = [w for w in self.operational_set
                                      if w in msg_lower]
                        if op_matches:
                            contradictions.append(
                                "Declared educational intent but asks for "
                                "operational details")
            if interaction_log:
                for entry in interaction_log[-3:]:
                    prior = entry.get("evidence", {}).get(
                        "declared_intent", [])
                    if prior and declared_intent:
                        prev_texts = set(e["text"] for e in prior
                                         if "text" in e)
                        curr_texts = set(e["text"] for e in declared_intent
                                         if "text" in e)
                        if prev_texts and curr_texts \
                                and not prev_texts.intersection(curr_texts):
                            contradictions.append(
                                "Changed declared intent between interactions")
                            break
            return contradictions

        @staticmethod
        def _analyze_trajectory(interaction_log):
            if not interaction_log:
                return "first_interaction"
            recent = interaction_log[-3:]
            states = [e.get("state", "") for e in recent]
            if any(s in ("red_restrict", "red_escalate") for s in states):
                return "escalating"
            red_count = sum(1 for s in states if s == "red_clarify")
            if red_count >= 2:
                return "repeated_red"
            if "evidence_review" in states:
                return "evasive"
            if "yellow" in states:
                return "cautionary"
            return "clean"

    # ═══════════════════════════════════════════════════════════════
    # EVIDENCE TRACKING — Layer 2 foundation
    # ═══════════════════════════════════════════════════════════════

    def _record_interaction(self, user_message: str, verdict: str,
                            confidence: float = 0.0, matches: list = None,
                            state: str = "", evidence: dict = None) -> None:
        """Record every user interaction with its safety verdict and state.

        This builds the evidence trail that Layer 2 uses to detect
        harmful behavioral patterns over time.

        Args:
            user_message: The original user message
            verdict: Safety verdict (block/accept/caution/reject)
            confidence: Confidence score from safety analysis
            matches: Safety keywords/phrases that triggered
            state: SafetyCandle state (green/yellow/red_clarify/etc)
            evidence: Structured evidence record
        """
        entry = {
            "timestamp": time.time(),
            "message_snippet": user_message[:200],  # truncated for privacy
            "verdict": verdict,
            "confidence": confidence,
            "matches": matches or [],
        }
        if state:
            entry["state"] = state
        if evidence:
            entry["evidence"] = evidence
        self._interaction_log.append(entry)
        # Keep log bounded (last 100 interactions)
        if len(self._interaction_log) > 100:
            self._interaction_log = self._interaction_log[-100:]

    def _evidence_check(self, user_message: str, safety_verdict: dict) -> dict:
        """Layer 2: Check user history for harmful patterns.

        Analyzes the interaction log to answer:
        - Has this user tried harmful things before?
        - Is there a pattern of escalating behavior?
        - Does the current message fit a harmful pattern?

        Returns:
            {"safe": True/False,
             "evidence_found": True/False,
             "pattern": "clean" | "suspicious" | "escalating" | "repeat_offender",
             "prior_incidents": N,
             "reason": "..."}
        """
        # Count prior incidents from interaction log
        prior_red = sum(1 for entry in self._interaction_log
                        if entry["verdict"] == "block")
        prior_yellow = sum(1 for entry in self._interaction_log
                           if entry["verdict"] in ("caution", "reject"))
        prior_total = prior_red + prior_yellow

        # No history — clean slate
        if prior_total == 0:
            return {
                "safe": True,
                "evidence_found": False,
                "pattern": "clean",
                "prior_incidents": 0,
                "reason": "No prior incidents in interaction history.",
            }

        # Has prior RED blocks — repeat offender
        if prior_red > 0:
            return {
                "safe": False,
                "evidence_found": True,
                "pattern": "repeat_offender",
                "prior_incidents": prior_red,
                "reason": f"User has {prior_red} prior blocked interactions. High risk.",
            }

        # Multiple YELLOW incidents — escalating pattern
        if prior_yellow >= 3:
            return {
                "safe": False,
                "evidence_found": True,
                "pattern": "escalating",
                "prior_incidents": prior_yellow,
                "reason": f"User has {prior_yellow} prior flagged interactions. Escalating pattern detected.",
            }

        # Few YELLOW incidents — monitor but allow
        if prior_yellow >= 1:
            return {
                "safe": True,
                "evidence_found": True,
                "pattern": "suspicious",
                "prior_incidents": prior_yellow,
                "reason": f"User has {prior_yellow} prior flagged interactions. Proceeding with caution.",
            }

        return {
            "safe": True,
            "evidence_found": False,
            "pattern": "clean",
            "prior_incidents": 0,
            "reason": "No pattern detected.",
        }

    def _balance_assessment(self, safety_verdict: dict, evidence: dict) -> dict:
        """Layer 2 balance: Weigh SafetyCandle state against historical evidence.

        This is the consensus gate between Layer 1 (SafetyCandle) and
        Layer 2 (SelfAwareness + Evidence). Both must agree before
        GPS and WORK DESTINATION are activated.

        The analogy: we cannot activate the guidance mechanism (GPS)
        without both the safety filter AND historical evidence
        confirming the user's intent is legitimate.

        Returns:
            {"consensus": True/False,
             "activate_gps": True/False,
             "reason": "...",
             "risk_level": "low" | "medium" | "high"}
        """
        state = safety_verdict.get("state", self._safety.GREEN)

        # ── States that shouldn't reach here (safety net) ──
        if state in (self._safety.RED_CLARIFY, self._safety.RED_RESTRICT,
                     self._safety.RED_ESCALATE, self._safety.EVIDENCE_REVIEW):
            return {
                "consensus": False,
                "activate_gps": False,
                "reason": f"Safety state '{state}' — cannot activate guidance.",
                "risk_level": "high",
            }

        # ── YELLOW + evidence unsafe → No consensus ──
        if state == self._safety.YELLOW and not evidence.get("safe", True):
            return {
                "consensus": False,
                "activate_gps": False,
                "reason": (
                    f"Safety flagged YELLOW ({safety_verdict.get('matches', [])}) "
                    f"AND evidence found: {evidence.get('reason', '')}"
                ),
                "risk_level": "high",
            }

        # ── YELLOW + evidence clean → Consensus with caution ──
        if state == self._safety.YELLOW and evidence.get("safe", True):
            return {
                "consensus": True,
                "activate_gps": True,
                "reason": (
                    "Safety flagged YELLOW but historical evidence is clean. "
                    "Proceeding with GPS activated — monitoring."
                ),
                "risk_level": "medium",
            }

        # ── GREEN + evidence unsafe (repeat offender) → No consensus ──
        if state == self._safety.GREEN and not evidence.get("safe", True):
            return {
                "consensus": False,
                "activate_gps": False,
                "reason": (
                    f"Current message is GREEN but evidence shows "
                    f"{evidence.get('pattern', '')}: {evidence.get('reason', '')}"
                ),
                "risk_level": "high",
            }

        # ── GREEN + evidence clean → Full consensus ──
        return {
            "consensus": True,
            "activate_gps": True,
            "reason": "Safety GREEN + evidence clean. Full consensus.",
            "risk_level": "low",
        }

    # ─── CLARIFICATION QUESTIONS ──────────────────────────────

    CLARIFICATION_QUESTIONS = {
        "weapons": (
            "Puedo hablar de seguridad, historia o funcionamiento "
            "general no operativo. ¿Cuál es el enfoque de tu proyecto?"
        ),
        "violence": (
            "Puedo hablar de resolución de conflictos, psicología "
            "o historia. ¿Cuál es el propósito de tu consulta?"
        ),
        "drugs": (
            "Puedo hablar de salud pública, farmacología general "
            "o política de drogas. ¿Cuál es el enfoque?"
        ),
        "hacking": (
            "Puedo hablar de ciberseguridad, vulnerabilidades "
            "generales o protección. ¿Cuál es el contexto?"
        ),
        "extremism": (
            "Puedo hablar de ciencias políticas, historia "
            "o sociología. ¿Cuál es tu área de interés?"
        ),
        "sensitive_data": (
            "Puedo hablar de protección de datos "
            "y seguridad de la información. ¿Cuál es tu proyecto?"
        ),
        "religion": (
            "Puedo hablar de religión de forma académica "
            "o cultural. ¿Cuál es tu interés?"
        ),
    }

    def _clarification_question(self, topic: str) -> str:
        """Return a safe clarification question for a sensitive topic.

        First response to a red topic should never block — instead ask
        for purpose without giving operational instructions.
        """
        return self.CLARIFICATION_QUESTIONS.get(
            topic,
            "Puedo ayudarte con información general o educativa. "
            "¿Cuál es el propósito de tu consulta?"
        )

    # ─── ANALYSIS — DETECT DEVIATION TYPE ──────────────────────

    def _safety_first(self, user_message: str) -> dict:
        """Analyze safety with state-based Intention Analysis.

        Uses SafetyCandle.analyze() to determine state + evidence.
        No longer a brute-force gate — returns guidance for
        analyze_user_message to decide how to respond.

        New state format:
          GREEN / YELLOW → stop=False, proceed to Layer 2
          RED_CLARIFY    → stop=False, ask for purpose
          EVIDENCE_REVIEW → stop=True, review trajectory
          RED_RESTRICT   → stop=True, deny operational help
          RED_ESCALATE   → stop=True, security response
        """
        analysis = self._safety.analyze(
            user_message, self._interaction_log
        )
        state = analysis["state"]
        evidence = analysis["evidence"]
        strategy = analysis["response_strategy"]

        # GREEN / YELLOW → proceed normally, don't stop GPS
        if state in (self._safety.GREEN, self._safety.YELLOW):
            return {
                "stop": False,
                "state": state,
                "reason": "",
                "evidence": evidence,
                "response_strategy": strategy,
                "matches": analysis.get("matches", []),
            }

        # RED_CLARIFY → don't stop, but respond with safe clarification
        if state == self._safety.RED_CLARIFY:
            return {
                "stop": False,
                "state": state,
                "reason": (
                    f"🔴 Tema sensible: {evidence['topic']} "
                    f"— pedir propósito"
                ),
                "evidence": evidence,
                "response_strategy": strategy,
                "matches": analysis.get("matches", []),
            }

        # EVIDENCE_REVIEW → stop, review trajectory
        if state == self._safety.EVIDENCE_REVIEW:
            return {
                "stop": True,
                "state": state,
                "reason": (
                    f"🔄 Evidencia de evasión/contradicción "
                    f"en {evidence['topic']}"
                ),
                "evidence": evidence,
                "response_strategy": strategy,
                "matches": analysis.get("matches", []),
            }

        # RED_RESTRICT → stop, deny operational help
        if state == self._safety.RED_RESTRICT:
            return {
                "stop": True,
                "state": state,
                "reason": (
                    f"🔴 Intención persistente riesgosa: "
                    f"{evidence['topic']}"
                ),
                "evidence": evidence,
                "response_strategy": strategy,
                "matches": analysis.get("matches", []),
            }

        # RED_ESCALATE → stop, security response
        if state == self._safety.RED_ESCALATE:
            return {
                "stop": True,
                "state": state,
                "reason": (
                    f"🚨 Autodaño/terceros detectado: "
                    f"{evidence['topic']}"
                ),
                "evidence": evidence,
                "response_strategy": strategy,
                "matches": analysis.get("matches", []),
            }

        # Fallback → green
        return {
            "stop": False,
            "state": self._safety.GREEN,
            "reason": "",
            "response_strategy": "normal",
        }

    def analyze_user_message(self, user_message: str, active_task: str = "") -> dict:
        """
        Analyze what the user said and decide how to respond.

        4-LAYER GATING ARCHITECTURE:
        ─────────────────────────────

        Layer 1: SAFETY CANDLE — State-based Intention Analysis.
                 Evaluates message against RED/YELLOW/GREEN vocabulary
                 and interaction history (trajectory, evasion, makeup).
                 Returns a state + evidence record.
                 RED_CLARIFY → ask for purpose, don't block.
                 RED_RESTRICT / RED_ESCALATE → block immediately.
                 EVIDENCE_REVIEW → review trajectory, don't engage.
                 GREEN / YELLOW → pass to Layer 2.

        Layer 2: SELFAWARENESS + EVIDENCE — Check user history for
                 harmful patterns. Balance SafetyCandle state against
                 historical evidence.
                 ✓ Consensus → activate GPS, pass to Layer 3.
                 ✗ No consensus → ask user, DO NOT activate GPS.

        Layer 3: GPS ACTIVATED — Run deviation analysis.
                 GPS analyzes on_track / necessary_detour / off_track /
                 new_direction. Notifies SelfAwareness of result.

        Layer 4: TRIPLE CONSENSUS — GPS + SelfAwareness + WORK DESTINATION.
                 ✓ Consensus → process normally.
                 ✗ No consensus → ask user: "changed direction or continue?"

        CRITICAL RULE: GPS and WORK DESTINATION are NOT activated until
        SafetyCandle + SelfAwareness (with evidence) give consensus.
        Activating guidance without intent verification would lead
        the agent into a user trap.

        Returns a decision dict for engine.py to execute.
        """

        # ══════════════════════════════════════════════════════════
        # LAYER 1: SAFETY CANDLE — State-based Intention Analysis
        # ══════════════════════════════════════════════════════════
        safety = self._safety_first(user_message)
        state = safety.get("state", self._safety.GREEN)
        strategy = safety.get("response_strategy", "normal")
        evidence = safety.get("evidence", {})
        matches = safety.get("matches", [])

        # ── 🆘 RED_ESCALATE: Self-harm / third-party harm ────────
        if state == self._safety.RED_ESCALATE:
            self._record_interaction(user_message, "block", 1.0, matches,
                                     state=state, evidence=evidence)
            return {
                "action": "safety_escalate",
                "state": state,
                "reason": safety["reason"],
                "topic": evidence.get("topic", "unknown"),
                "matches": matches,
                "suggestion": (
                    "I'm concerned about what you're saying. "
                    "If you're in crisis, please reach out to a mental health "
                    "professional or a crisis helpline in your area. "
                    "I can't provide help with this request."
                ),
            }

        # ── 🚫 RED_RESTRICT: Intentional harmful progression ─────
        if state == self._safety.RED_RESTRICT:
            self._record_interaction(user_message, "block", 1.0, matches,
                                     state=state, evidence=evidence)
            return {
                "action": "safety_restrict",
                "state": state,
                "reason": safety["reason"],
                "topic": evidence.get("topic", "unknown"),
                "matches": matches,
                "suggestion": (
                    "I can't provide operational instructions in this area. "
                    "If you have a legitimate educational or research need, "
                    "please explain your project context. Otherwise, "
                    "let's focus on something constructive."
                ),
            }

        # ── 🔍 EVIDENCE_REVIEW: Evasion / contradiction detected ─
        if state == self._safety.EVIDENCE_REVIEW:
            self._record_interaction(user_message, "reject", 0.9, matches,
                                     state=state, evidence=evidence)
            return {
                "action": "safety_review",
                "state": state,
                "reason": safety["reason"],
                "topic": evidence.get("topic", "unknown"),
                "matches": matches,
                "suggestion": (
                    "I notice some inconsistencies in what you're asking for. "
                    "I can help with legitimate educational or research topics, "
                    "but I need clear context. What's the actual purpose of "
                    "your inquiry?"
                ),
            }

        # ── 🔴 RED_CLARIFY: Sensitive topic — ask purpose ────────
        if state == self._safety.RED_CLARIFY:
            topic = evidence.get("topic", "")
            question = self._clarification_question(topic)
            self._record_interaction(user_message, "caution", 0.5, matches,
                                     state=state, evidence=evidence)
            return {
                "action": "ask_clarification",
                "state": state,
                "topic": topic,
                "question": question,
                "reason": safety["reason"],
                "evidence": evidence,
                "matches": matches,
            }

        # ── 🟡 YELLOW: Record as caution, proceed to Layer 2 ─────
        if state == self._safety.YELLOW:
            self._record_interaction(user_message, "caution", 0.5, matches,
                                     state=state, evidence=evidence)

        # ── 🟢 GREEN: Record as accept ────────────────────────────
        if state == self._safety.GREEN:
            self._record_interaction(user_message, "accept", 0.0, [],
                                     state=state, evidence=evidence)

        # ══════════════════════════════════════════════════════════
        # LAYER 2: SELFAWARENESS + EVIDENCE — Check history
        # ══════════════════════════════════════════════════════════
        # Look at past interactions for harmful behavioral patterns.
        # Balance SafetyCandle state against historical evidence.
        evidence_check = self._evidence_check(user_message, safety)
        balance = self._balance_assessment(safety, evidence_check)

        # ── No balance consensus → DO NOT activate GPS ──────────
        if not balance["consensus"]:
            return {
                "action": "ask_user",
                "reason": balance["reason"],
                "verdict": "no_consensus",
                "question": (
                    "I've detected some concerns with this request based on "
                    "safety checks and interaction history. "
                    "Could you clarify your intent?"
                ),
                "risk_level": balance["risk_level"],
                "evidence": evidence_check,
                "safety": safety,
            }

        # ── Balance consensus → ACTIVATE GPS ────────────────────
        self.gps.activate(
            reason=f"Safety state={state} + "
                   f"Evidence={evidence_check['pattern']} | "
                   f"Risk={balance['risk_level']}"
        )

        # ══════════════════════════════════════════════════════════
        # LAYER 3 + 4: GPS ACTIVATED → Deviation + Triple Consensus
        # ══════════════════════════════════════════════════════════
        # With GPS activated by Layer 2, run the full triple consensus check.
        # This internally calls gps.analyze_deviation() (deviation analysis)
        # and gps.check_consensus() (work-destination alignment).
        consensus = self.triple_consensus(user_message, active_task)
        deviation = consensus.get("deviation")

        # Log meaningful deviations for the evidence trail
        if deviation in ("off_track", "new_direction"):
            self.gps.log_deviation(
                description=f"GPS detected: {deviation}",
                context=user_message[:200]
            )

        # ── No destination → first interaction ──────────────────
        if (not consensus["gps_check"]["ok"] and
                "No destination" in consensus["gps_check"]["detail"]):
            return {
                "action": "process_normally",
                "reason": "First interaction, learning destination",
                "consensus_detail": consensus,
                "deviation": deviation,
                "risk_level": balance["risk_level"],
            }

        # ── Full consensus → smooth sailing ────────────────────
        if (consensus["consensus"] and
                consensus["self_check"]["ok"] and
                consensus["gps_check"]["ok"]):
            return {
                "action": "process_normally",
                "reason": "Triple consensus: SELF + GPS + WORK aligned",
                "consensus_detail": consensus,
                "deviation": deviation,
                "risk_level": balance["risk_level"],
                "gps_activated": True,
            }

        # ── Detour that serves destination → process, note it ──
        if (consensus["gps_check"]["ok"] and
                "Detour serves" in consensus["gps_check"]["detail"]):
            return {
                "action": "process_normally_warn",
                "reason": "On a detour — serves the destination but worth noting",
                "consensus_detail": consensus,
                "deviation": deviation,
                "risk_level": balance["risk_level"],
                "gps_activated": True,
            }

        # ── Off-track → ask user: changed direction or continue? ─
        if consensus["ask_user"]:
            return {
                "action": "ask_user",
                "reason": consensus["reason"],
                "question": consensus["question"],
                "consensus_detail": consensus,
                "deviation": deviation,
                "risk_level": balance["risk_level"],
                "gps_activated": True,
            }

        # ── Default: process normally ──────────────────────────
        return {
            "action": "process_normally",
            "reason": "default",
            "consensus_detail": consensus,
            "deviation": deviation,
            "risk_level": balance["risk_level"],
            "gps_activated": True,
        }

    # ─── INTERNAL HELPERS ───────────────────────────────────────

    def _write(self, filename: str, data: dict) -> None:
        path = os.path.join(self.self_path, filename)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _read(self, filename: str) -> Optional[dict]:
        path = os.path.join(self.self_path, filename)
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None
