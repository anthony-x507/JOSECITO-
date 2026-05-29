"""DIGOS AIAgent Core — LLM interaction loop with tool calling + transparency."""
import json
import re
from typing import Optional, Dict, List, Any, Callable
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# Security
from security import SecurityGate, EXTERNAL_TOOLS

# Tools
from digos_lib.agent_tools import (
    AVAILABLE_TOOLS, DANGEROUS_TOOLS, _execute_tool,
    DYNAMIC_TOOL_DEFS,
)

# Intent Classification (Camino B — natural language → capability gap)
from digos_lib.intent_classifier import classify_intent, IntentClassification

# MASTER Risk Pattern Layer
from digos_lib.master_risk import MasterRiskPatternLayer, MasterVerdict


class AIAgent:
    """Agent that processes messages with LLM + tools + transparency.

    Uso:
        agent = AIAgent(
            base_url="https://api.openai.com/v1",
            api_key="sk-...",
            model="gpt-4o",
            progress_cb=tower.emit_tool_progress,
            assistant_cb=tower.emit_assistant_message,
        )
        response = agent.process_message("Hola, ¿qué hora es?")
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o",
        system_prompt: str = "Eres un asistente útil. Puedes usar herramientas para ayudar al usuario.",
        progress_cb: Optional[Callable] = None,
        assistant_cb: Optional[Callable] = None,
        error_cb: Optional[Callable] = None,
        approval_cb: Optional[Callable] = None,
        disclosure_cb: Optional[Callable] = None,
        rotation_cb: Optional[Callable] = None,
        creation_cb: Optional[Callable] = None,
        capability_cb: Optional[Callable] = None,
        master: Optional[MasterRiskPatternLayer] = None,
        max_iterations: int = 15,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt
        self._progress_cb = progress_cb or (lambda n, a: None)
        self._assistant_cb = assistant_cb or (lambda t: None)
        self._error_cb = error_cb or (lambda n, e: None)
        self._approval_cb = approval_cb
        self._disclosure_cb = disclosure_cb
        self._rotation_cb = rotation_cb
        self._creation_cb = creation_cb
        self._capability_cb = capability_cb
        self._max_iterations = max_iterations

        # Historial de conversación
        self._messages: List[dict] = [{"role": "system", "content": system_prompt}]
        self._tools_enabled = True
        self._pending_rotation: Optional[str] = None  # credential_type when user is mid-rotation
        self._pending_intent: Optional[IntentClassification] = None  # intent waiting for user confirmation
        self._pending_intent_msg: str = ""  # original message that triggered the intent

        # Pipeline — notificaciones del TicketConversationPipeline
        self._pipeline_notification: str = ""

        # Security Gate
        self._gate = SecurityGate()

        # MASTER Risk Pattern Layer — recibir instancia existente (Tower) o crear nueva
        self._master = master if master is not None else MasterRiskPatternLayer()

        # Identity responses (from DIGOS system)
        self._identity_responses = []
        try:
            from digos_lib.constants import IDENTITY_RESPONSES
            self._identity_responses = IDENTITY_RESPONSES
        except Exception:
            self._identity_responses = {"es": [], "en": []}

    def _check_identity_question(self, message: str) -> str:
        """Detects if the message asks about the system identity.
        Responds without calling the LLM to save time and tokens."""
        msg_lower = message.lower().strip()
        for lang, pairs in self._identity_responses.items():
            for question, answer in pairs:
                if question in msg_lower:
                    return answer
        return ""

    # ── Credential Disclosure ────────────────────

    CREDENTIAL_REQUEST_PATTERNS_ES = [
        "mi api key", "mi apikey", "mi api_key", "mi llave",
        "mi token", "mis credenciales", "mi clave",
        "ver mi api", "ver mi token", "dame mi api", "dame mi token",
        "mostrar mi api", "mostrar mi token", "muéstrame mi api",
        "cual es mi api", "cuál es mi api", "cual es mi token",
        "qué api key", "que api key", "qué token", "que token",
        "quiero ver mi", "quiero saber mi", "enséñame mi",
        "donde esta mi api", "dónde está mi api",
        "ver credenciales", "mostrar credenciales", "dame credenciales",
        "api key que tengo", "token que tengo", "proveedor que uso",
        "cual es mi proveedor", "qué proveedor", "que proveedor",
    ]

    CREDENTIAL_REQUEST_PATTERNS_EN = [
        "my api key", "my apikey", "my api_key",
        "my token", "my credentials", "my key",
        "show my api", "show my token", "give me my api", "give me my token",
        "what is my api", "what's my api", "what is my token",
        "want to see my", "want my api", "want my token",
        "where is my api", "tell me my", "display my",
    ]

    def _check_credential_request(self, message: str) -> str:
        """Detects if the user is asking for THEIR OWN credentials.

        Credentials belong to the user. The Tower only guards them.
        This method:
          1. Detects if the message is a credential request
          2. Determines WHICH credential is being asked for
          3. Calls the disclosure_cb to retrieve it from the Engineer
          4. Returns a formatted response without exposing the credential value
        """
        msg_lower = message.lower().strip()

        # Check if this is a credential request
        all_patterns = self.CREDENTIAL_REQUEST_PATTERNS_ES + self.CREDENTIAL_REQUEST_PATTERNS_EN
        matched = False
        for pattern in all_patterns:
            if pattern in msg_lower:
                matched = True
                break

        if not matched:
            return ""

        # No disclosure_cb available → can't retrieve credentials
        if not self._disclosure_cb:
            return (
                "No tengo acceso a la CajaSeguraInfo en este momento. "
                "El sistema no está completamente inicializado. "
                "Usa `digos --status` para verificar el estado."
            )

        # Determine WHICH credential the user is asking for
        credential_type = self._infer_credential_type(msg_lower)

        # Call the disclosure callback → routes through TorreDeControl → Engineer → CajaSeguraInfo
        try:
            result = self._disclosure_cb(credential_type, "agente")
        except Exception as e:
            # If the disclosure chain is broken, fall through to LLM for graceful response
            self._assistant_cb(f"⚠️ Credential disclosure falló: {e}")
            return ""

        return self._format_disclosure_response(result)

    def _infer_credential_type(self, msg_lower: str) -> str:
        """Infers which credential the user is asking about."""
        # Check "all" FIRST — compound requests like "token y credenciales"
        all_patterns = ["credenciales", "credentials", "todo", "all", "everything", "todas"]
        for p in all_patterns:
            if p in msg_lower:
                return "all"

        # Provider patterns (before token, since "proveedor" is more specific)
        provider_patterns = ["proveedor", "provider", "qué proveedor", "que proveedor",
                           "cual es mi proveedor", "cuál es mi proveedor"]
        for p in provider_patterns:
            if p in msg_lower:
                return "provider_id"

        # Token patterns
        token_patterns = ["token", "gateway", "telegram", "bot"]
        for p in token_patterns:
            if p in msg_lower:
                return "gateway_token"

        # Default: API key
        return "api_key"

    def _format_disclosure_response(self, result: dict) -> str:
        """Formats the disclosure result into a user-friendly message."""
        if not result.get("ok"):
            return f"🔒 {result.get('message', 'No se pudo recuperar la credencial.')}"

        cred_type = result.get("credential_type", "")
        ticket_id = result.get("ticket_id", "?")

        if cred_type == "all":
            value = result.get("value", {})
            lines = [
                "🔑 RESUMEN DE CREDENCIALES",
                "━━━━━━━━━━━━━━━━━━",
                "Estas credenciales te pertenecen. La Torre solo las custodia.",
                "Por seguridad no muestro credenciales completas en el chat.",
                "",
            ]
            if value.get("provider_id"):
                pid = value["provider_id"]
                pname = self._provider_name(pid)
                lines.append(f"  Proveedor:     {pname} (ID: {pid})")
            if value.get("api_key"):
                lines.append(f"  API Key:       guardada ({self._mask_secret(value['api_key'])})")
            if value.get("gateway_token"):
                lines.append(f"  Gateway Token: guardado ({self._mask_secret(value['gateway_token'])})")
            if value.get("model"):
                lines.append(f"  Modelo:        {value['model']}")
            lines.append("")
            lines.append(f"📋 Ticket de auditoría: #{ticket_id}")
            return "\n".join(lines)

        value = result.get("value", "")

        if cred_type == "provider_id":
            pname = self._provider_name(value)
            return (
                f"🔑 Proveedor: {pname} (ID: {value})\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Esta información te pertenece. La Torre solo la custodia.\n"
                f"📋 Ticket de auditoría: #{ticket_id}"
            )

        label_map = {
            "api_key": "API Key",
            "gateway_token": "Gateway Token",
        }
        label = label_map.get(cred_type, cred_type)

        return (
            f"🔑 {label}: guardada ({self._mask_secret(value)})\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Esta credencial te pertenece. La Torre solo la custodia.\n"
            f"Por seguridad no muestro el valor completo en el chat.\n"
            f"📋 Ticket de auditoría: #{ticket_id}"
        )

    @staticmethod
    def _mask_secret(value: str) -> str:
        """Returns a short, non-sensitive marker for a stored secret."""
        text = str(value or "")
        if not text:
            return "sin valor"
        suffix = text[-4:] if len(text) >= 4 else text[-1:]
        return f"••••{suffix}"

    @staticmethod
    def _provider_name(provider_id: str) -> str:
        """Resolves provider ID to human-readable name."""
        try:
            from digos_lib.constants import PROVIDERS
            return PROVIDERS.get(provider_id, {}).get("name", provider_id)
        except Exception:
            return provider_id

    # ── Credential Rotation ────────────────────

    ROTATION_PATTERNS_ES = [
        "cambia mi api key a ", "cambia mi api key por ",
        "cambiar mi api key a ", "cambiar mi api key por ",
        "cambia mi token a ", "cambia mi token por ",
        "cambiar mi token a ", "cambiar mi token por ",
        "nueva api key", "nuevo token", "nuevo api key",
        "actualiza mi api key", "actualiza mi token",
        "actualizar mi api key", "actualizar mi token",
        "rota mi api key", "rota mi token",
        "rotar mi api key", "rotar mi token",
        "renovar mi api key", "renovar mi token",
        "poner nueva api key", "poner nuevo token",
    ]

    ROTATION_PATTERNS_EN = [
        "change my api key to ", "change my api key",
        "change my token to ", "change my token",
        "new api key", "new token",
        "update my api key", "update my token",
        "rotate my api key", "rotate my token",
        "replace my api key", "replace my token",
        "switch my api key", "switch my token",
    ]

    def _check_credential_rotation(self, message: str) -> str:
        """Detects if the user wants to CHANGE their credential.

        The Tower is the ONLY one that stores. The Agent only passes the key
        through a ticket. The Centinela only monitors.

        This method:
          1. Detects rotation intent
          2. Determines WHICH credential is being changed
          3. Extracts the NEW value from the message
          4. Calls rotation_cb → Tower validates → stores → closes tickets
          5. Returns a formatted response
        """
        msg_lower = message.lower().strip()

        # Check rotation intent
        all_patterns = self.ROTATION_PATTERNS_ES + self.ROTATION_PATTERNS_EN
        matched = False
        for pattern in all_patterns:
            if pattern in msg_lower:
                matched = True
                break

        if not matched:
            return ""

        # No rotation_cb available
        if not self._rotation_cb:
            return (
                "No tengo acceso al sistema de rotación de credenciales. "
                "El sistema no está completamente inicializado. "
                "Usa `digos --status` para verificar el estado."
            )

        # Determine WHAT is being changed
        credential_type = self._infer_rotation_type(msg_lower)

        # Extract the NEW value — pasar message ORIGINAL (con mayúsculas) aparte de msg_lower
        new_value = self._extract_new_credential(message, msg_lower, credential_type)
        if not new_value:
            # Can't extract — set pending state for two-step flow
            self._pending_rotation = credential_type
            hints = {
                "api_key": "API key (ej: sk-...)",
                "gateway_token": "token de Telegram (ej: 123:abc...)",
            }
            hint = hints.get(credential_type, "nueva credencial")
            return (
                f"🔑 Entendido, quieres cambiar tu {credential_type}.\n"
                f"¿Cuál es tu nueva {hint}?\n"
                f"Escríbela en tu próximo mensaje."
            )

        # Call rotation callback → Tower validates → stores → closes Centinela tickets
        try:
            result = self._rotation_cb(credential_type, new_value, "agente")
        except Exception as e:
            self._assistant_cb(f"⚠️ Credential rotation falló: {e}")
            return ""

        return self._format_rotation_response(result)

    def _infer_rotation_type(self, msg_lower: str) -> str:
        """Infers WHICH credential type is being rotated."""
        if "token" in msg_lower or "gateway" in msg_lower or "telegram" in msg_lower:
            return "gateway_token"
        return "api_key"

    def _extract_new_credential(self, message: str, msg_lower: str, credential_type: str) -> str:
        """Extracts the NEW credential value from the message.

        message:    mensaje ORIGINAL del usuario (con mayúsculas preservadas)
        msg_lower:  mensaje en minúsculas (para patrones de texto)

        Los regex de búsqueda de keys/tokens usan `message` (original)
        para no destruir mayúsculas. Los patrones de texto usan `msg_lower`.

        Looks for patterns like:
          "cambia mi api key a sk-abc123XYZ"
          "nueva api key: sk-ABC123"
          "cambiar a 123:abc..."
        """
        # Patrones de extracción ("a/por/con" es opcional para soportar "cambia mi api key sk-xxx")
        extractors_es = [
            r"(?:cambia|cambiar|actualiza|actualizar|rota|rotar|renovar|poner)\s+(?:mi\s+)?(?:api\s*key|token|api_key)(?:\s*(?:a|por|con))?\s+(\S+)",
            r"(?:nueva|nuevo)\s+(?:api\s*key|token)\s*[:\s]+(\S+)",
            r"(?:api\s*key|token)\s*(?:nueva|nuevo)\s*[:\s]+(\S+)",
        ]

        extractors_en = [
            r"(?:change|update|rotate|replace|switch)\s+(?:my\s+)?(?:api\s*key|token)\s*(?:to|with)\s+(\S+)",
            r"(?:new)\s+(?:api\s*key|token)\s*[:\s]+(\S+)",
        ]

        for pattern in extractors_es + extractors_en:
            match = re.search(pattern, msg_lower)
            if match:
                # Extraer del mensaje ORIGINAL para preservar mayúsculas
                original_match = re.search(pattern, message)
                if original_match:
                    return original_match.group(1).strip()
                return match.group(1).strip()

        # Si no hay patrón claro, buscar algo que parezca una key
        # API keys típicamente empiezan con sk- o tienen formato de API key
        # Usar `message` ORIGINAL para preservar mayúsculas/minúsculas
        if credential_type == "api_key":
            key_match = re.search(r'(sk-[a-zA-Z0-9_-]{10,})', message)
            if key_match:
                return key_match.group(1)

        # Tokens de Telegram: formato 123456789:ABC...
        # Usar `message` ORIGINAL para preservar mayúsculas
        if credential_type == "gateway_token":
            token_match = re.search(r'(\d{8,10}:[a-zA-Z0-9_-]{20,})', message)
            if token_match:
                return token_match.group(1)

        return ""

    def _format_rotation_response(self, result: dict) -> str:
        """Formats the rotation result into a user-friendly message."""
        if not result.get("ok"):
            return f"❌ {result.get('message', 'No se pudo rotar la credencial.')}"

        cred_type = result.get("credential_type", "")
        ticket_id = result.get("ticket_id", "?")
        closed = result.get("closed_related", 0)
        provider = result.get("provider_name", "")

        label_map = {
            "api_key": "API Key",
            "gateway_token": "Gateway Token",
        }
        label = label_map.get(cred_type, cred_type)

        lines = [
            f"✅ {label} ROTADA EXITOSAMENTE",
            "━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"La Torre guardó la nueva credencial en CajaSeguraInfo.",
        ]
        if provider:
            lines.append(f"Proveedor: {provider}")
        if closed:
            lines.append(f"{closed} ticket(s) del Centinela cerrado(s).")
        lines.extend([
            "El Centinela continúa su monitoreo regular.",
            f"📋 Ticket de rotación: #{ticket_id}",
        ])
        return "\n".join(lines)

    # ── Internal Agent Creation ────────────────────

    CREATION_PATTERNS_ES = [
        "crea un builder", "crea un auditor", "crea un reviewer",
        "crea builder", "crea auditor", "crea reviewer",
        "crear un builder", "crear un auditor", "crear un reviewer",
        "crear builder", "crear auditor", "crear reviewer",
        "crea 2 builders", "crea 3 builders", "crea agentes",
        "crea un agente", "crear un agente", "crear agente",
        "necesito un builder", "necesito un auditor", "necesito un reviewer",
        "necesito builder", "necesito auditor", "necesito reviewer",
        "dame un builder", "dame un auditor", "dame un reviewer",
        "dame builder", "dame auditor", "dame reviewer",
        "creame un builder", "creame un auditor", "creame un reviewer",
        "creame builder", "creame auditor", "creame reviewer",
        "fabrica un builder", "fabrica un auditor", "fabrica un reviewer",
        "genera un builder", "genera un auditor", "genera un reviewer",
        "crea agente interno", "crear agente interno",
        "puedo tener otro agente", "puedo tener un agente",
        "puedes hacer otro agente", "puedes crear otro agente",
        "puedes generar otro agente", "puedes hacer un agente interno",
        "puedes crear un agente interno", "hacer otro agente interno",
        "crear otro agente interno", "generar otro agente interno",
        "la fabrica puede hacer mas agentes",
        "la fábrica puede hacer más agentes",
        "la factoria puede hacer mas agentes",
        "la factoría puede hacer más agentes",
        "la fabrica no puede hacer mas agentes",
        "la fábrica no puede hacer más agentes",
    ]

    CREATION_PATTERNS_EN = [
        "create a builder", "create an auditor", "create a reviewer",
        "create builder", "create auditor", "create reviewer",
        "make a builder", "make an auditor", "make a reviewer",
        "make builder", "make auditor", "make reviewer",
        "i need a builder", "i need an auditor", "i need a reviewer",
        "give me a builder", "give me an auditor", "give me a reviewer",
        "spawn a builder", "spawn an auditor", "spawn a reviewer",
        "spawn builder", "spawn auditor", "spawn reviewer",
        "new agent", "create agent", "internal agent",
        "can i have another agent", "can you create another agent",
        "can you make another agent", "can the factory create agents",
        "make an internal agent", "create an internal agent",
    ]

    def _check_internal_agent_request(self, message: str) -> str:
        """Detects if the user wants to CREATE internal agents.

        The user controls which mode each agent uses:
          ☑️ collaborative — conoce hermanos, usa MessageBus
          ☑️ isolated     — solo ve a SuperiorAgent + Tower

        The Agent opens a ticket → SystemEngineer → Factory creates the agent.
        """
        msg_lower = message.lower().strip()

        # Check creation intent — first try static patterns
        all_patterns = self.CREATION_PATTERNS_ES + self.CREATION_PATTERNS_EN
        matched = False
        for pattern in all_patterns:
            if pattern in msg_lower:
                matched = True
                break

        # Also try regex for number-prefixed requests like "crea 3 auditors"
        if not matched:
            number_match = re.search(
                r'(?:crea|crear|necesito|dame|creame|fabrica|genera|puedo tener|puedes (?:hacer|crear|generar)|hacer|create|make|spawn|give me|i need|can (?:i have|you create|you make))\s+(?:\d+\s+)?(?:builders?|auditors?|reviewers?|agentes?(?:\s+internos?)?|internal agents?)',
                msg_lower
            )
            if number_match:
                matched = True

        if not matched:
            return ""

        # No creation_cb available
        if not self._creation_cb:
            return (
                "No tengo acceso a la Factoría de agentes internos. "
                "El sistema no está completamente inicializado. "
                "Usa `digos --status` para verificar el estado."
            )

        # Determine agent type
        agent_type = "builder"  # default
        if "auditor" in msg_lower:
            agent_type = "auditor"
        elif "reviewer" in msg_lower:
            agent_type = "reviewer"

        # Determine mode — user explicitly says "modo aislado" or "isolated"
        mode = "collaborative"  # default
        if "aislado" in msg_lower or "isolated" in msg_lower:
            mode = "isolated"

        # Determine count — "crea 2 builders"
        count = 1
        count_match = re.search(r'(\d+)\s*(?:builders?|auditors?|reviewers?|agentes?)', msg_lower)
        if count_match:
            count = int(count_match.group(1))
            if count > 10:
                count = 10  # max 10 per request

        # Special name?
        name_match = re.search(r'(?:llamado|named?|con nombre)\s+"?(\w+)"?', msg_lower)
        custom_name = name_match.group(1) if name_match else ""

        # Create agents
        created = []
        for i in range(count):
            try:
                agent_name = custom_name if count == 1 and custom_name else ""
                result = self._creation_cb(agent_type, mode, agent_name, "", "agente")
            except Exception as e:
                self._assistant_cb(f"⚠️ Agent creation falló: {e}")
                continue

            if result.get("ok"):
                created.append(result)

        if not created:
            return "❌ No se pudo crear ningún agente interno."

        # Format response
        if len(created) == 1:
            r = created[0]
            mode_label = "🤝 colaborativo" if mode == "collaborative" else "🔒 aislado"
            return (
                f"✅ AGENTE INTERNO CREADO\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"  Nombre:  {r['agent_name']}\n"
                f"  Tipo:    {r['agent_type']}\n"
                f"  Modo:    {mode_label}\n"
                f"  Ticket:  #{r['ticket_id']}\n"
                f"\n"
                f"La Torre le ha inyectado:\n"
                f"  🧭 GPS + 🧠 SelfAwareness + 📋 Work + 🔥 SafetyKendo"
            )

        mode_label = "🤝 colaborativo" if mode == "collaborative" else "🔒 aislado"
        names = ", ".join(r['agent_name'] for r in created)
        return (
            f"✅ {len(created)} AGENTES INTERNOS CREADOS\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  Nombres: {names}\n"
            f"  Tipo:    {created[0]['agent_type']}\n"
            f"  Modo:    {mode_label}\n"
            f"  Ticket:  #{created[0]['ticket_id']}\n"
            f"\n"
            f"La Torre les ha inyectado:\n"
            f"  🧭 GPS + 🧠 SelfAwareness + 📋 Work + 🔥 SafetyKendo"
        )

    def inject_pipeline_context(self, context: str):
        """Inyecta contexto del TicketConversationPipeline.

        Llamado por TorreDeControl cuando hay mensajes pendientes
        del SystemEngineer en el pipeline de algún ticket.
        El contexto se inyecta en el system prompt en el próximo
        process_message().
        """
        if context and context.strip():
            self._pipeline_notification = context

    def process_message(self, user_message: str) -> str:
        """Processes a user message. Returns the final response."""
        # ── Input Gate: check message before processing ──
        gate_result = self._gate.check_input(user_message)
        if gate_result["blocked"]:
            return gate_result["response"]

        clean_msg = gate_result["clean_message"]

        # ── MASTER Risk Layer: classify risk + pattern trajectory ──
        # Get the intent classification first (for context-aware risk analysis)
        intent = self._classify_intent(clean_msg)
        master_verdict = self._master.analyze_with_intent(
            clean_msg,
            intent.family if intent.matched else "CONVERSATION",
            intent.sub_intent_id if intent.matched else "GENERAL_CHAT",
        )

        # 🔴 RED: block immediately — NO provider, NO Factory
        if master_verdict.risk_level == "red":
            self._messages.append({"role": "user", "content": clean_msg})
            response = master_verdict.suggestion or "I cannot process this request."
            self._messages.append({"role": "assistant", "content": response})
            return response

        # 🟡 YELLOW escalated: firm caution — limited safe scope
        if master_verdict.risk_level == "yellow" and master_verdict.trajectory_escalated:
            self._messages.append({"role": "user", "content": clean_msg})
            response = master_verdict.suggestion or "This request contains repeated sensitive topics. Could you clarify what you're looking for?"
            self._messages.append({"role": "assistant", "content": response})
            return response

        # 🟡 YELLOW first-time: allow, log, proceed with caution
        # 🟢 GREEN: normal flow

        # ── Pending Rotation: user is mid-rotation (two-step flow) ──
        if self._pending_rotation:
            cred_type = self._pending_rotation
            self._pending_rotation = None  # consume the pending state
            new_value = clean_msg.strip()
            if new_value and self._rotation_cb:
                try:
                    result = self._rotation_cb(cred_type, new_value, "agente")
                    response = self._format_rotation_response(result)
                except Exception as e:
                    self._assistant_cb(f"⚠️ Credential rotation falló: {e}")
                    response = ""
                if response:
                    self._messages.append({"role": "user", "content": clean_msg})
                    self._messages.append({"role": "assistant", "content": response})
                    return response

        # ── Identity Check: respond without LLM if asked who you are ──
        identity_response = self._check_identity_question(clean_msg)
        if identity_response:
            self._messages.append({"role": "user", "content": clean_msg})
            self._messages.append({"role": "assistant", "content": identity_response})
            return identity_response

        # ── Credential Disclosure: user asks for THEIR credentials ──
        credential_response = self._check_credential_request(clean_msg)
        if credential_response:
            # ⚠️ NO append the real credential to _messages history
            # (it would leak to the LLM provider on the next call)
            # Instead, store a redacted record
            self._messages.append({"role": "user", "content": clean_msg})
            self._messages.append({"role": "assistant", "content": "🔑 [Credencial entregada al usuario — ver respuesta anterior]"})
            return credential_response

        # ── Credential Rotation: user provides a NEW credential ──
        rotation_response = self._check_credential_rotation(clean_msg)
        if rotation_response:
            self._messages.append({"role": "user", "content": clean_msg})
            self._messages.append({"role": "assistant", "content": rotation_response})
            return rotation_response

        # ── Internal Agent Creation: user asks to create builders/auditors/reviewers ──
        creation_response = self._check_internal_agent_request(clean_msg)
        if creation_response:
            self._messages.append({"role": "user", "content": clean_msg})
            self._messages.append({"role": "assistant", "content": creation_response})
            return creation_response

        # ── Intent Confirmation Check: user said "sí"/"dale" to a pending capability request ──
        if self._pending_intent is not None:
            confirmation = self._check_intent_confirmation(clean_msg)
            if confirmation == "yes":
                pending = self._pending_intent
                original = self._pending_intent_msg
                self._pending_intent = None
                self._pending_intent_msg = ""
                response = self._handle_confirmed_intent(pending, original)
                self._messages.append({"role": "user", "content": clean_msg})
                self._messages.append({"role": "assistant", "content": response})
                return response
            elif confirmation == "no":
                self._pending_intent = None
                self._pending_intent_msg = ""
                response = "Entendido. Cuando quieras agregar esa capacidad, solo dímelo."
                self._messages.append({"role": "user", "content": clean_msg})
                self._messages.append({"role": "assistant", "content": response})
                return response
            # else: ambiguous — let it fall through to normal processing

        # ── Camino B: Intent Classification (natural language → capability gap) ──
        intent = self._classify_intent(clean_msg)
        if intent.matched and intent.has_gap:
            # Capability gap detected — user wants something we can't do yet.
            # Only set pending_intent if there's a factory_action (SKILL_REQUEST).
            # For info-only responses (e.g., VOICE_INPUT_NOW), just show the message.
            if intent.factory_action:
                self._pending_intent = intent
                self._pending_intent_msg = clean_msg
            full_response = intent.gap_response
            self._messages.append({"role": "user", "content": clean_msg})
            self._messages.append({"role": "assistant", "content": full_response})
            return full_response

        # ── Pipeline Notification: contexto pendiente del SystemEngineer ──
        if self._pipeline_notification:
            self._messages.append({
                "role": "system",
                "content": self._pipeline_notification,
            })
            self._pipeline_notification = ""

        self._messages.append({"role": "user", "content": clean_msg})

        iterations = 0
        while iterations < self._max_iterations:
            iterations += 1

            # 1. Llamar al LLM
            assistant_text, tool_calls = self._call_llm()

            # 2. Si el LLM generó texto interino, reportarlo
            if assistant_text:
                self._assistant_cb(assistant_text[:200])

            # 3. Si no hay tool calls, terminamos
            if not tool_calls:
                if assistant_text:
                    self._messages.append({"role": "assistant", "content": assistant_text})
                    # ── Output Gate: review and redact final response ──
                    output_check = self._gate.check_output(assistant_text)
                    safe_response = assistant_text
                    if not output_check["safe"]:
                        # Redactar credenciales en la respuesta
                        from security import CREDENTIAL_PATTERN
                        safe_response = CREDENTIAL_PATTERN.sub("***REDACTED***", assistant_text)
                        self._assistant_cb(f"⚠️ Credenciales redactadas de la respuesta")
                    return safe_response
                else:
                    return "No pude procesar tu mensaje."

            # 4. Add assistant response (with tool calls) to history
            assistant_msg = {"role": "assistant", "content": assistant_text or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}
                    }
                    for tc in tool_calls
                ]
            self._messages.append(assistant_msg)

            # 5. Execute each tool
            for tc in tool_calls:
                name = tc["name"]
                args = tc["args"]

                # Reportar progreso
                self._progress_cb(name, args)

                # Consultar a la Torre de Control si la operacion esta permitida
                if self._approval_cb:
                    approved = self._approval_cb(name, args)
                    if not approved:
                        result = f"⛔ Operacion no permitida por la Torre de Control: {name}"
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result[:2000],
                        })
                        self._assistant_cb(result)
                        continue
                elif name in DANGEROUS_TOOLS:
                    # No callback: fail-closed, deny dangerous tools
                    result = f"⛔ Tool '{name}' bloqueada por seguridad. Sin aprobacion disponible."
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result[:2000],
                    })
                    self._assistant_cb(result)
                    continue

                # Ejecutar
                try:
                    result = _execute_tool(name, args, api_key=self._api_key, base_url=self._base_url, model=self._model)
                except Exception as exc:
                    # Tool failed — mark as ❌ in Activity Panel and continue
                    error_msg = str(exc)
                    self._error_cb(name, error_msg)
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": f"Error executing {name}: {error_msg[:2000]}",
                    })
                    self._assistant_cb(f"⚠️ Tool '{name}' falló: {error_msg[:80]}")
                    continue

                # ── Tool Output Gate: for external sources only ──
                tool_check = self._gate.check_tool_output(name, result)
                safe_result = tool_check["output"]

                # Add result to history
                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": safe_result[:2000],
                })

        return "Lo siento, no pude completar la tarea en el número máximo de iteraciones."

    def _call_llm(self) -> tuple:
        """Llama al LLM con retry exponencial (Séptimo Movimiento: Resiliencia).

        Retry strategy:
          - Max 3 intentos
          - Backoff exponencial: 1s → 2s → 4s
          - Retry en: URLError, timeout, HTTP 429, HTTP 5xx
          - No retry en: HTTP 4xx (excepto 429)
        """
        import time as _time

        MAX_RETRIES = 3
        BASE_DELAY = 1.0  # segundos

        if not self._base_url or not self._api_key:
            return "LLM no configurado. Usa --setup para configurar API key.", []

        endpoint = self._base_url + "/chat/completions"

        body = {
            "model": self._model,
            "messages": self._messages[-20:],  # últimos 20 mensajes
            "max_tokens": 2048,
            "temperature": 0.7,
        }

        if self._tools_enabled:
            # Combine static tools with dynamically-built Factory tools
            all_tools = list(AVAILABLE_TOOLS)
            if DYNAMIC_TOOL_DEFS:
                all_tools.extend(DYNAMIC_TOOL_DEFS)
            body["tools"] = all_tools
            body["tool_choice"] = "auto"

        last_error = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                payload = json.dumps(body).encode()
                req = Request(
                    endpoint,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self._api_key}",
                    },
                )
                with urlopen(req, timeout=60) as r:
                    data = json.loads(r.read())

                # Success — parse response
                choices = data.get("choices", [])
                if not choices:
                    return "El LLM no devolvió respuestas.", []

                msg = choices[0].get("message", {})
                content = msg.get("content") or ""
                raw_tool_calls = msg.get("tool_calls") or []

                tool_calls = []
                for tc in raw_tool_calls:
                    if tc.get("type") == "function":
                        try:
                            func = tc.get("function", {})
                            name = func.get("name", "")
                            args = json.loads(func.get("arguments", "{}"))
                            tool_calls.append({
                                "id": tc["id"],
                                "name": name,
                                "args": args,
                            })
                        except (json.JSONDecodeError, KeyError):
                            continue

                return content, tool_calls

            except HTTPError as e:
                last_error = f"HTTP {e.code}"
                # 429 Rate Limit → retry with backoff
                if e.code == 429:
                    if attempt < MAX_RETRIES:
                        delay = BASE_DELAY * (2 ** (attempt - 1))
                        self._assistant_cb(f"⚠️ Rate limit (HTTP 429) — reintentando en {delay:.0f}s (intento {attempt}/{MAX_RETRIES})...")
                        _time.sleep(delay)
                        continue
                    return f"Error de rate limit (HTTP 429) tras {MAX_RETRIES} intentos.", []
                # 5xx Server Error → retry
                if 500 <= e.code < 600:
                    if attempt < MAX_RETRIES:
                        delay = BASE_DELAY * (2 ** (attempt - 1))
                        self._assistant_cb(f"⚠️ Error del servidor (HTTP {e.code}) — reintentando en {delay:.0f}s (intento {attempt}/{MAX_RETRIES})...")
                        _time.sleep(delay)
                        continue
                    return f"Error del servidor (HTTP {e.code}) tras {MAX_RETRIES} intentos.", []
                # 4xx Client Error (except 429) — no retry
                return f"Error del cliente LLM (HTTP {e.code}): verifica tu API key y configuración.", []

            except URLError as e:
                last_error = f"Red: {e.reason}"
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** (attempt - 1))
                    self._assistant_cb(f"⚠️ Error de conexión — reintentando en {delay:.0f}s (intento {attempt}/{MAX_RETRIES})...")
                    _time.sleep(delay)
                    continue
                return f"Error de conexión con LLM tras {MAX_RETRIES} intentos: {e.reason}", []

            except json.JSONDecodeError:
                # JSON decode error — might be transient, retry
                last_error = "JSON inválido"
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** (attempt - 1))
                    _time.sleep(delay)
                    continue
                return "Error: respuesta inválida del LLM tras varios intentos", []

            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** (attempt - 1))
                    _time.sleep(delay)
                    continue
                return f"Error llamando al LLM tras {MAX_RETRIES} intentos: {e}", []

        return f"Error: {last_error} (agotados {MAX_RETRIES} reintentos)", []

    # ── Intent Confirmation (two-step) ────────────────────────

    CONFIRMATION_YES = [
        "sí", "si", "dale", "claro", "ok", "okay", "vale", "bueno",
        "prepárala", "preparala", "prepáralo", "preparalo",
        "prepara la solicitud", "prepara solicitud", "prepárame la solicitud",
        "envíala", "enviala", "envíalo", "envialo", "mándala", "mandala",
        "adelante", "procede", "hazlo", "hazla",
        "yes", "yeah", "yep", "sure", "go ahead", "do it", "please",
        "perfecto", "genial", "excelente", "confirmado", "confirmar",
        "enviar", "envía", "envia", "crea", "crear",
    ]

    CONFIRMATION_NO = [
        "no", "nope", "nah", "no gracias", "ahora no", "luego",
        "después", "despues", "cancel", "cancela", "cancelar",
        "no quiero", "paso", "deja", "déjalo", "dejalo",
        "no hace falta", "no es necesario",
    ]

    def _check_intent_confirmation(self, message: str) -> str:
        """Check if the user is confirming or rejecting a pending capability request.

        Returns 'yes', 'no', or '' (ambiguous — treat as normal conversation).
        """
        msg_lower = message.lower().strip()

        # Check explicit confirmations
        for pattern in self.CONFIRMATION_YES:
            if pattern == msg_lower or msg_lower.startswith(pattern + " ") or msg_lower.startswith(pattern + ","):
                return "yes"

        # Check explicit rejections
        for pattern in self.CONFIRMATION_NO:
            if pattern == msg_lower or msg_lower.startswith(pattern + " ") or msg_lower.startswith(pattern + ","):
                return "no"

        return ""

    def _handle_confirmed_intent(self, intent: IntentClassification, original_message: str) -> str:
        """User confirmed the capability request — route to Factory.

        The Factory pipeline (FactoryManager.request_new_capability):
          1. Creates a specialized Builder agent
          2. Creates a Factory ticket with all checkmarks
          3. Enters skill into Sandbox
          4. Routes through Builder→Auditor→Reviewer→Release
          5. Promotes skill to superior
        """
        if not self._capability_cb:
            return intent.gap_response + "\n\n(La Factoría no está disponible en este momento.)"

        try:
            result = self._capability_cb(
                capability=intent.capability,
                family=intent.family,
                sub_intent=intent.sub_intent_id,
                user_message=original_message,
                requester="agente",
            )
        except Exception as e:
            return intent.gap_response + f"\n\n❌ Error al preparar la solicitud: {e}"

        if result.get("ok"):
            ticket_id = result.get("ticket_id", "?")
            ticket_number = result.get("ticket_number", ticket_id)
            agent_name = result.get("agent_name", "")
            tool_name = result.get("tool_name", intent.capability)
            sandbox_id = result.get("sandbox_id", "")
            revision = result.get("revision", "")
            audit_ticket_id = result.get("audit_ticket_id", "")

            lines = [
                f"✅ SOLICITUD ENVIADA A LA FACTORÍA",
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"📦 Capacidad: {intent.capability}",
                f"🏷️  Skill:     {tool_name}",
                f"📋 Ticket:    #{ticket_number}",
            ]
            if agent_name:
                lines.append(f"🤖 Builder:   {agent_name}")
            if sandbox_id:
                lines.append(f"🧪 Sandbox:   #{sandbox_id}")
            if revision:
                lines.append(f"📌 Revisión:  v{revision}")
            if audit_ticket_id and audit_ticket_id != ticket_id:
                lines.append(f"📋 Auditoría: #{audit_ticket_id}")
            lines.extend([
                "",
                "🏭 Pipeline de la Factoría:",
                "   🔐 Caja Segura → ⚡ Eficiencia → 🧬 Evolución",
                "   → 🤖 Builder → 🔍 Auditor → ✅ Reviewer → 🚀 Release",
                "",
                "Te avisaré cuando la capacidad esté lista. "
                "Mientras tanto, sigamos con lo que necesites.",
            ])
            return "\n".join(lines)
        else:
            return f"❌ {result.get('message', 'No se pudo preparar la solicitud.')}"

    # ── Intent Classification (Camino B — híbrido) ────────────

    def _classify_intent(self, message: str) -> IntentClassification:
        """Classify user message into intent family + sub-intent using LLM.

        This is Camino B of the hybrid architecture:
        - Camino A (regex): structured commands like api_key, credentials, agent creation
        - Camino B (LLM): natural language like "quiero que me escuches"

        Only called when all regex checks have failed.
        Uses a lightweight LLM call for classification.
        """
        if not self._base_url or not self._api_key:
            return IntentClassification(
                matched=False,
                family="CONVERSATION",
                sub_intent_id="GENERAL_CHAT",
                gap_response="",
                factory_action="",
                confidence=0.0,
            )

        return classify_intent(
            user_message=message,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            timeout=10,  # fast classification, don't block
        )

    def reset_conversation(self):
        """Reinicia el historial de conversación."""
        self._messages = [{"role": "system", "content": self._system_prompt}]
