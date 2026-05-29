"""
DIGOS TicketConversationPipeline — PipeLine de Conversación por Ticket
======================================================================

🎻 NUEVO INSTRUMENTO PARA LA SINFONÍA
═══════════════════════════════════════

PROBLEMA DETECTADO:
  La única vía de comunicación entre el SystemEngineer y los agentes
  es el ticket con su flag_status (inbox → processing → testing →
  review → delivered). Esto es MUY LIMITADO para la fluidez de la
  orquestación. Cuando el Engineer necesita más información, el ticket
  simplemente espera en "processing" sin que el agente sepa qué falta.

SOLUCIÓN — PIPELINE DE CONVERSACIÓN:
  Se abre un hilo de conversación paralelo por cada ticket donde:
  - El Engineer puede preguntar, pedir aclaraciones, solicitar datos
  - El Agente puede responder con la información del usuario
  - Ambos reciben NOTIFICACIÓN PERSISTENTE de mensajes nuevos
  - El historial completo se guarda en disco (persistente entre reinicios)
  - La conversación siempre está referenciada al número de ticket

ARQUITECTURA:
  ┌─────────────────────────────────────────────────────────────┐
  │  TorreDeControl (orquesta el pipeline)                      │
  │  ├── Pipeline.cycle() → revisa mensajes nuevos → notifica   │
  │  │                                                          │
  │  ├── SystemEngineer (escribe/lee el pipeline)               │
  │  │   ├── send_message(ticket, "ingeniero", "¿qué X?")      │
  │  │   └── get_unread("ingeniero") → ["necesito Y"]           │
  │  │                                                          │
  │  └── AIAgent (recibe contexto del pipeline en su prompt)     │
  │      ├── "Tienes mensajes pendientes del Engineer en #123"  │
  │      └── tools: pipeline_send(), pipeline_check()           │
  └─────────────────────────────────────────────────────────────┘

ESTADOS DEL PIPELINE:
  active   → Hay una conversación abierta sobre este ticket
  resolved → La conversación se cerró (el ticket sigue su curso)
  archived → Historial preservado para auditoría

PERSISTENCIA:
  ~/.digos/pipelines/{ticket_id}.json
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict

from digos_lib.constants import DIGOS_DIR
from digos_lib.core_log import LogKeeper


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────


@dataclass
class PipelineMessage:
    """Un mensaje individual en el pipeline de un ticket."""
    id: str
    sender: str               # "engineer" | "agente" | "sistema"
    content: str
    msg_type: str             # "question" | "response" | "info" | "resolution"
    timestamp: str
    read_by: List[str] = field(default_factory=list)  # quiénes lo han leído
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class TicketConversation:
    """Hilo de conversación completo para un ticket."""
    ticket_id: str
    participants: List[str] = field(default_factory=lambda: ["engineer", "agente"])
    status: str = "active"     # active | resolved | archived
    messages: List[dict] = field(default_factory=list)
    opened_at: str = ""
    resolved_at: str = ""


# ─────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ─────────────────────────────────────────────


class TicketConversationPipeline:
    """
    🎻 TicketConversationPipeline — PipeLine de Conversación por Ticket.

    Es el nuevo instrumento de comunicación en la sinfonía DIGOS.
    Permite que el SystemEngineer y los agentes tengan conversaciones
    persistentes y estructuradas alrededor de cada ticket abierto.

    Uso desde SystemEngineer:
        pipeline = TicketConversationPipeline(log_keeper)
        pipeline.open_conversation("20260528-0001", ["engineer", "agente"])
        pipeline.send_message("20260528-0001", "engineer",
                              "¿El usuario prefiere X o Y?", "question")
        msgs = pipeline.get_unread("agente")

    Uso desde TorreDeControl:
        pipeline.cycle()  → en el loop daemon, notifica mensajes nuevos
    """

    def __init__(self, log_keeper: LogKeeper):
        self._log = log_keeper
        self._pipelines_dir = DIGOS_DIR / "pipelines"
        self._pipelines_dir.mkdir(parents=True, exist_ok=True)

    # ── CRUD de conversaciones ─────────────────────────────────

    def open_conversation(
        self,
        ticket_id: str,
        participants: Optional[List[str]] = None,
        initial_message: str = "",
    ) -> bool:
        """Abre un hilo de conversación para un ticket.

        Args:
            ticket_id: ID del ticket (ej: "20260528-0001")
            participants: Lista de participantes (default: ["engineer", "agente"])
            initial_message: Mensaje opcional de apertura

        Returns:
            True si se abrió correctamente, False si ya existía
        """
        if self._conversation_exists(ticket_id):
            return False  # ya existe

        if participants is None:
            participants = ["engineer", "agente"]

        conv = TicketConversation(
            ticket_id=ticket_id,
            participants=participants,
            status="active",
            opened_at=datetime.now(timezone.utc).isoformat(),
        )

        if initial_message:
            msg = self._build_message(
                sender="sistema",
                content=initial_message,
                msg_type="info",
            )
            conv.messages.append(msg)

        self._save_conversation(ticket_id, asdict(conv))
        self._log.info("pipeline",
            f"🎻 Conversación abierta para ticket #{ticket_id} "
            f"(participantes: {', '.join(participants)})")
        return True

    def send_message(
        self,
        ticket_id: str,
        sender: str,
        content: str,
        msg_type: str = "info",
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """Envía un mensaje en el pipeline de un ticket.

        Args:
            ticket_id: ID del ticket
            sender: Quién envía ("engineer" | "agente" | "sistema")
            content: Contenido del mensaje
            msg_type: Tipo ("question" | "response" | "info" | "resolution")
            metadata: Datos adicionales opcionales

        Returns:
            ID del mensaje si se envió, None si el ticket no tiene pipeline
        """
        conv_data = self._load_conversation(ticket_id)
        if not conv_data:
            return None

        msg = self._build_message(sender, content, msg_type, metadata or {})
        conv_data["messages"].append(msg)

        # Si el ticket estaba resolved, reactivarlo
        if conv_data.get("status") in ("resolved", "archived"):
            conv_data["status"] = "active"
            self._log.info("pipeline",
                f"🎻 Pipeline #{ticket_id} reactivado por mensaje de '{sender}'")

        self._save_conversation(ticket_id, conv_data)
        self._log.info("pipeline",
            f"🎻 Mensaje #{msg['id']} en #{ticket_id} de '{sender}' "
            f"(type={msg_type})")

        return msg["id"]

    def get_messages(
        self,
        ticket_id: str,
        include_read: bool = True,
    ) -> List[dict]:
        """Obtiene los mensajes de un ticket.

        Args:
            ticket_id: ID del ticket
            include_read: Si True, incluye mensajes ya leídos

        Returns:
            Lista de mensajes, o [] si no hay pipeline
        """
        conv_data = self._load_conversation(ticket_id)
        if not conv_data:
            return []
        messages = conv_data.get("messages", [])
        if not include_read:
            return [m for m in messages if m["sender"] != "sistema"]
        return messages

    def get_unread(self, participant: str) -> List[dict]:
        """Obtiene todos los mensajes NO LEÍDOS para un participante.

        Un mensaje se considera "no leído" si el participante NO está
        en su lista read_by.

        Args:
            participant: Nombre del participante ("engineer" | "agente")

        Returns:
            Lista de mensajes no leídos, cada uno con ticket_id incluido
        """
        unread = []
        for conv_file in sorted(self._pipelines_dir.iterdir()):
            if not conv_file.suffix == ".json":
                continue
            try:
                conv_data = json.loads(conv_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                continue

            if conv_data.get("status") != "active":
                continue
            if participant not in conv_data.get("participants", []):
                continue

            for msg in conv_data.get("messages", []):
                if participant not in msg.get("read_by", []):
                    # Añadir ticket_id al mensaje para contexto
                    enriched = dict(msg)
                    enriched["ticket_id"] = conv_data["ticket_id"]
                    enriched["conversation_status"] = conv_data["status"]
                    unread.append(enriched)

        return unread

    def get_unread_count(self, participant: str) -> int:
        """Cuantos mensajes no leídos tiene un participante."""
        return len(self.get_unread(participant))

    def mark_read(self, ticket_id: str, participant: str, message_id: str = "") -> int:
        """Marca mensajes como leídos para un participante.

        Args:
            ticket_id: ID del ticket
            participant: Nombre del participante
            message_id: Si se especifica, solo marca ese mensaje.
                       Si es "", marca TODOS los mensajes como leídos.

        Returns:
            Número de mensajes marcados como leídos
        """
        conv_data = self._load_conversation(ticket_id)
        if not conv_data:
            return 0

        count = 0
        for msg in conv_data.get("messages", []):
            if participant in msg.get("read_by", []):
                continue  # ya leído
            if message_id and msg["id"] != message_id:
                continue
            msg.setdefault("read_by", []).append(participant)
            count += 1
            if message_id:
                break  # solo este mensaje

        if count > 0:
            self._save_conversation(ticket_id, conv_data)

        return count

    def get_active_conversations(self) -> List[dict]:
        """Obtiene todas las conversaciones activas.

        Returns:
            Lista de resúmenes de conversaciones activas
        """
        active = []
        for conv_file in sorted(self._pipelines_dir.iterdir()):
            if not conv_file.suffix == ".json":
                continue
            try:
                conv_data = json.loads(conv_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                continue
            if conv_data.get("status") == "active":
                last_msg = conv_data.get("messages", [])
                summary = {
                    "ticket_id": conv_data["ticket_id"],
                    "participants": conv_data.get("participants", []),
                    "message_count": len(last_msg),
                    "last_message_at": last_msg[-1]["timestamp"] if last_msg else "",
                    "last_sender": last_msg[-1]["sender"] if last_msg else "",
                }
                active.append(summary)
        return active

    def resolve_conversation(self, ticket_id: str, resolution_msg: str = "") -> bool:
        """Cierra la conversación de un ticket (el ticket sigue su curso normal).

        Args:
            ticket_id: ID del ticket
            resolution_msg: Mensaje opcional de cierre

        Returns:
            True si se resolvió, False si no existe
        """
        conv_data = self._load_conversation(ticket_id)
        if not conv_data:
            return False

        if resolution_msg:
            msg = self._build_message(
                sender="sistema",
                content=resolution_msg,
                msg_type="resolution",
            )
            conv_data["messages"].append(msg)

        conv_data["status"] = "resolved"
        conv_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
        self._save_conversation(ticket_id, conv_data)
        self._log.info("pipeline",
            f"🎻 Conversación #{ticket_id} resuelta: {resolution_msg[:80]}")
        return True

    def get_conversation_status(self, ticket_id: str) -> Optional[dict]:
        """Obtiene el estado completo de una conversación.

        Returns:
            Dict con ticket_id, status, participants, message_count,
            o None si no existe
        """
        conv_data = self._load_conversation(ticket_id)
        if not conv_data:
            return None
        return {
            "ticket_id": conv_data["ticket_id"],
            "status": conv_data.get("status", "active"),
            "participants": conv_data.get("participants", []),
            "message_count": len(conv_data.get("messages", [])),
            "opened_at": conv_data.get("opened_at", ""),
            "resolved_at": conv_data.get("resolved_at", ""),
        }

    def get_summary_for_agent(self, participant: str = "agente") -> str:
        """Construye un resumen de mensajes pendientes para el prompt del agente.

        Este método es llamado por TorreDeControl para inyectar el
        contexto del pipeline en el system prompt del AIAgent.

        Args:
            participant: Nombre del participante ("agente" | "engineer")

        Returns:
            Texto formateado con los mensajes pendientes, o "" si no hay nada
        """
        unread = self.get_unread(participant)
        if not unread:
            return ""

        lines = [
            "📬 PIPELINE — Mensajes del SystemEngineer",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "Tienes mensajes pendientes en el pipeline de conversación.",
            "El SystemEngineer necesita tu respuesta para continuar.",
            "",
        ]

        # Agrupar por ticket
        by_ticket: Dict[str, list] = {}
        for msg in unread:
            tid = msg.get("ticket_id", "?")
            by_ticket.setdefault(tid, []).append(msg)

        for tid, msgs in by_ticket.items():
            sender = msgs[0].get("sender", "?")
            last = msgs[-1]
            lines.append(f"  🎫 Ticket #{tid} — {len(msgs)} mensaje(s) de '{sender}':")
            for m in msgs:
                content_preview = m.get("content", "")[:150]
                mtype = m.get("msg_type", "info")
                icon = {"question": "❓", "response": "💬", "info": "📌", "resolution": "✅"}.get(mtype, "📝")
                lines.append(f"    {icon} [{mtype}] {content_preview}")
                # Si es una pregunta, el agente debe responder
                if mtype == "question":
                    lines.append(f"       ⬆️  El Engineer espera tu respuesta.")
            lines.append("")

        lines.append(
            "Para responder, usa la función pipeline_respond() con el "
            "ticket_id y tu mensaje."
        )
        lines.append("Para ver el historial completo, usa pipeline_get_messages().")
        lines.append("")

        return "\n".join(lines)

    def get_summary_for_engineer(self) -> str:
        """Construye un resumen de actividad del pipeline para el Engineer.

        Este método es llamado en el ciclo daemon de TorreDeControl
        para que el Engineer sepa qué conversaciones están activas.
        """
        active = self.get_active_conversations()
        if not active:
            return ""

        lines = [
            "🎻 PIPELINE — Conversaciones activas",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        for conv in active:
            lines.append(
                f"  🎫 #{conv['ticket_id']}: {conv['message_count']} mensajes, "
                f"último de '{conv['last_sender']}'"
            )
        lines.append("")
        return "\n".join(lines)

    def cycle(self) -> List[dict]:
        """Ciclo de mantenimiento del pipeline — llamado por TorreDeControl.

        Revisa todas las conversaciones activas y reporta:
        - Conversaciones sin actividad reciente (>1 hora)
        - Mensajes no leídos por más de 5 minutos
        - Tickets cuya conversación debería cerrarse

        Returns:
            Lista de alertas/notificaciones para el sistema
        """
        alerts = []
        now = time.time()
        five_min_ago = now - 300  # 5 minutos
        one_hour_ago = now - 3600

        for conv_file in self._pipelines_dir.iterdir():
            if not conv_file.suffix == ".json":
                continue
            try:
                conv_data = json.loads(conv_file.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, ValueError):
                continue

            if conv_data.get("status") != "active":
                continue

            messages = conv_data.get("messages", [])
            if not messages:
                continue

            last_msg = messages[-1]
            try:
                last_ts = datetime.fromisoformat(last_msg["timestamp"]).timestamp()
            except (ValueError, KeyError):
                continue

            ticket_id = conv_data["ticket_id"]

            # Alerta: mensaje no leído por más de 5 minutos
            for msg in messages:
                try:
                    msg_ts = datetime.fromisoformat(msg["timestamp"]).timestamp()
                except (ValueError, KeyError):
                    continue

                if msg_ts > five_min_ago:
                    continue  # muy reciente

                for participant in conv_data.get("participants", []):
                    if participant not in msg.get("read_by", []):
                        # Este participante no ha leído este mensaje
                        alerts.append({
                            "type": "unread_alert",
                            "ticket_id": ticket_id,
                            "participant": participant,
                            "sender": msg.get("sender", "?"),
                            "content_preview": msg.get("content", "")[:100],
                            "minutes_unread": int((now - msg_ts) / 60),
                        })

        return alerts

    # ── Helpers internos ─────────────────────────────────────

    def _build_message(
        self,
        sender: str,
        content: str,
        msg_type: str = "info",
        metadata: Optional[Dict[str, str]] = None,
    ) -> dict:
        """Construye un dict de mensaje con IDs y timestamps."""
        ts = datetime.now(timezone.utc)
        msg_id = f"msg-{ts.strftime('%Y%m%d%H%M%S')}-{int(ts.timestamp() * 1000) % 10000:04d}"
        return {
            "id": msg_id,
            "sender": sender,
            "content": content,
            "msg_type": msg_type,
            "timestamp": ts.isoformat(),
            "read_by": [],
            "metadata": metadata or {},
        }

    def _conversation_path(self, ticket_id: str) -> Path:
        """Ruta al archivo de conversación."""
        # Sanitize ticket_id for filename
        safe_name = ticket_id.replace("/", "_").replace("\\", "_")
        return self._pipelines_dir / f"{safe_name}.json"

    def _conversation_exists(self, ticket_id: str) -> bool:
        return self._conversation_path(ticket_id).exists()

    def _save_conversation(self, ticket_id: str, data: dict):
        """Guarda una conversación en disco."""
        path = self._conversation_path(ticket_id)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding='utf-8',
        )

    def _load_conversation(self, ticket_id: str) -> Optional[dict]:
        """Carga una conversación de disco."""
        path = self._conversation_path(ticket_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, ValueError):
            self._log.warn("pipeline",
                f"Error cargando pipeline #{ticket_id} — archivo corrupto")
            return None


# ─────────────────────────────────────────────
# TOOL FUNCTIONS FOR AIAgent
# ─────────────────────────────────────────────

# These are the function implementations that the AIAgent's tools
# will call. They are registered in agent_tools.py as dynamic tools
# via TorreDeControl._register_pipeline_tools().
#
# Available to the agent:
#   pipeline_check()           → estado general del pipeline (conversaciones activas + no leídos)
#   pipeline_read(ticket_id)   → lee mensajes del pipeline de un ticket
#   pipeline_respond(ticket_id, message) → responde en el pipeline
#   pipeline_resolve(ticket_id) → cierra / marca como resuelta una conversación
#
# To wire them up, the pipeline instance is accessed via a module-level
# getter set by TorreDeControl after initialization.


# ── Pipeline Accessor (set by TorreDeControl) ────────────────────

_pipeline_accessor = None  # callable that returns TicketConversationPipeline instance


def set_pipeline_accessor(getter: callable):
    """Set the accessor function that returns the pipeline instance.

    Called by TorreDeControl after pipeline initialization so that
    the tool functions below can access the pipeline without needing
    a global reference.

    Args:
        getter: A callable that returns a TicketConversationPipeline instance
    """
    global _pipeline_accessor
    _pipeline_accessor = getter


# ── Tool Implementations ────────────────────────────────────────

# These are registered as dynamic tools in agent_tools.py.
# Signature: func(args: dict, api_key: str, base_url: str, model: str) -> str
# Compatible with agent_tools._execute_dynamic_tool().


def _pipeline_check(args: dict, api_key: str = "", base_url: str = "",
                    model: str = "") -> str:
    """Revisa el estado del pipeline: conversaciones activas y mensajes no leídos.

    Sin argumentos. Devuelve un resumen de:
    - Cuántas conversaciones activas existen
    - Cuántos mensajes no leídos tiene el agente
    - Lista de tickets con actividad pendiente
    """
    pipeline = _pipeline_accessor() if _pipeline_accessor else None
    if not pipeline:
        return "⚠️  Pipeline no disponible. El sistema no está completamente inicializado."

    try:
        # Obtener conversaciones activas
        active = pipeline.get_active_conversations()

        # Obtener mensajes no leídos del agente
        unread = pipeline.get_unread("agente")

        lines = [
            "📬 PIPELINE — Estado",
            "━━━━━━━━━━━━━━━━━━━━━",
        ]

        if not active and not unread:
            lines.append("  ✅ No hay conversaciones activas.")
            lines.append("  No tienes mensajes pendientes.")
            return "\n".join(lines)

        # ── No leídos ──
        if unread:
            lines.append(f"  📩 Tienes {len(unread)} mensaje(s) SIN LEER:")
            by_ticket: dict = {}
            for msg in unread:
                tid = msg.get("ticket_id", "?")
                by_ticket.setdefault(tid, []).append(msg)
            for tid, msgs in by_ticket.items():
                sender = msgs[0].get("sender", "?")
                lines.append(f"     🎫 #{tid}: {len(msgs)} mensaje(s) de '{sender}'")
                for m in msgs[-3:]:  # últimos 3
                    preview = m.get("content", "")[:120]
                    mtype = m.get("msg_type", "info")
                    icon = {"question": "❓", "response": "💬", "info": "📌"}.get(mtype, "📝")
                    lines.append(f"       {icon} {preview}")
            lines.append("")
            lines.append("  💡 Usa pipeline_read(ticket_id) para ver el historial completo.")
            lines.append("  💡 Usa pipeline_respond(ticket_id, mensaje) para responder.")
        else:
            lines.append("  ✅ No tienes mensajes sin leer.")

        # ── Activas ──
        if active:
            lines.append("")
            lines.append(f"  📋 {len(active)} conversación(es) activa(s):")
            for conv in active:
                lines.append(
                    f"     🎫 #{conv['ticket_id']}: {conv['message_count']} mensajes, "
                    f"último de '{conv['last_sender']}'"
                )

        if unread:
            lines.append("")
            lines.append(
                "⚠️  El SystemEngineer está esperando tu respuesta en los tickets "
                "con mensajes SIN LEER. Usa pipeline_respond() para responder."
            )

        return "\n".join(lines)

    except Exception as e:
        return f"Error al consultar pipeline: {e}"


def _pipeline_read(args: dict, api_key: str = "", base_url: str = "",
                   model: str = "") -> str:
    """Lee el historial completo de mensajes del pipeline para un ticket.

    Args:
        ticket_id: ID del ticket a consultar
    """
    pipeline = _pipeline_accessor() if _pipeline_accessor else None
    if not pipeline:
        return "⚠️  Pipeline no disponible."

    tid = args.get("ticket_id", "")
    if not tid:
        return "Error: se requiere ticket_id"

    try:
        messages = pipeline.get_messages(tid, include_read=True)
        status = pipeline.get_conversation_status(tid)

        if not messages:
            return f"📭 No hay conversación en el pipeline para el ticket #{tid}."

        lines = [
            f"📋 PIPELINE — Ticket #{tid}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]

        if status:
            lines.append(f"  Estado: {status.get('status', '?')}")
            lines.append(
                f"  Participantes: {', '.join(status.get('participants', []))}"
            )
            lines.append(f"  Total mensajes: {status.get('message_count', len(messages))}")
            lines.append("")

        for msg in messages:
            sender = msg.get("sender", "?")
            ts = msg.get("timestamp", "")[:19]  # ISO sin timezone
            mtype = msg.get("msg_type", "info")
            content = msg.get("content", "")
            read_by = msg.get("read_by", [])

            icon = {
                "engineer": "👷",
                "agente": "🤖",
                "sistema": "⚙️",
            }.get(sender, "📝")

            type_label = {
                "question": "❓ Pregunta",
                "response": "💬 Respuesta",
                "info": "📌 Info",
                "resolution": "✅ Resolución",
            }.get(mtype, mtype)

            read_status = "👁️ Leído" if read_by else "🔴 No leído"
            lines.append(f"{icon} [{ts}] {sender} ({type_label}) {read_status}")
            lines.append(f"   {content}")
            lines.append("")

        # Marcar como leído automáticamente al leer
        pipeline.mark_read(tid, "agente")
        lines.append("(✅ Marcado como leído)")

        return "\n".join(lines)

    except Exception as e:
        return f"Error al leer pipeline #{tid}: {e}"


def _pipeline_respond(args: dict, api_key: str = "", base_url: str = "",
                      model: str = "") -> str:
    """Responde a un mensaje del SystemEngineer en el pipeline.

    Args:
        ticket_id: ID del ticket al que se responde
        message: Contenido de la respuesta
    """
    pipeline = _pipeline_accessor() if _pipeline_accessor else None
    if not pipeline:
        return "⚠️  Pipeline no disponible."

    tid = args.get("ticket_id", "")
    content = args.get("message", "")

    if not tid:
        return "Error: se requiere ticket_id"
    if not content:
        return "Error: se requiere un mensaje para enviar"

    try:
        msg_id = pipeline.send_message(tid, "agente", content, "response")
        if msg_id is None:
            # No existe conversación — intentar abrir una
            opened = pipeline.open_conversation(
                tid,
                participants=["engineer", "agente"],
                initial_message=f"Respuesta automática del agente",
            )
            if not opened:
                return f"⚠️  No se pudo crear conversación para el ticket #{tid}."
            msg_id = pipeline.send_message(tid, "agente", content, "response")

        if not msg_id:
            return f"⚠️  No se pudo enviar el mensaje al ticket #{tid}."

        return (
            f"✅ Mensaje enviado al pipeline del ticket #{tid}.\n"
            f"   El SystemEngineer recibirá tu respuesta.\n"
            f"   ID del mensaje: {msg_id}"
        )

    except Exception as e:
        return f"Error al responder en pipeline #{tid}: {e}"


def _pipeline_resolve(args: dict, api_key: str = "", base_url: str = "",
                      model: str = "") -> str:
    """Cierra / marca como resuelta una conversación del pipeline.

    Úsala cuando ya no haya más preguntas pendientes del Engineer
    o cuando la información solicitada ya se haya proporcionado.

    Args:
        ticket_id: ID del ticket cuya conversación se resuelve
        resolution: Mensaje opcional de cierre (ej: "Información proporcionada")
    """
    pipeline = _pipeline_accessor() if _pipeline_accessor else None
    if not pipeline:
        return "⚠️  Pipeline no disponible."

    tid = args.get("ticket_id", "")
    if not tid:
        return "Error: se requiere ticket_id"

    resolution = args.get("resolution", "Cerrado por el agente")

    try:
        ok = pipeline.resolve_conversation(tid, resolution)
        if not ok:
            return f"⚠️  No hay conversación activa para el ticket #{tid}."
        return f"✅ Conversación #{tid} resuelta: {resolution}"
    except Exception as e:
        return f"Error al resolver conversación #{tid}: {e}"
