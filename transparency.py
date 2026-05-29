#!/usr/bin/env python3
"""
DIGOS Transparency Layer — Fase 4
===================================
Transparency layer that shows in real time what the agent is doing.
3 decoupled sub-systems:

1. ToolProgressTracker — receives agent events, builds messages with emoji
2. Gateway with edit_message + send_chat_action — platform-specific
3. Integration via TorreDeControl — connects tracker + gateway + agent

Modes:
  off     → shows nothing
  new     → shows only when tool changes
  all     → shows each tool (default)
  verbose → muestra argumentos completos

No external dependencies. stdlib only.
"""

import json
import logging
import time
import threading
from typing import Optional, Callable, Dict, List, Any, Tuple

logger = logging.getLogger("transparency")

# ─────────────────────────────────────────────
# MAPA DE EMOJIS POR TOOL
# ─────────────────────────────────────────────

TOOL_EMOJIS: Dict[str, str] = {
    # Terminal y ejecución
    "terminal": "💻",
    "execute_code": "🐍",
    "process": "⚙️",
    # Web y búsqueda
    "web_search": "🔍",
    "web_extract": "🌐",
    "web_scrape": "🕸️",
    "browser_navigate": "🌐",
    "browser_click": "🖱️",
    "browser_type": "⌨️",
    "browser_snapshot": "📃",
    "browser_vision": "👁️",
    # Archivos
    "read_file": "📄",
    "write_file": "📝",
    "patch": "🔧",
    "search_files": "🔎",
    # Comunicación
    "send_message": "📨",
    "text_to_speech": "🎤",
    # Imágenes y video
    "image_generate": "🎨",
    "vision_analyze": "👁️",
    # Gestión
    "cronjob": "⏰",
    "todo": "📋",
    "skill_view": "📖",
    "skill_manage": "🛠️",
    # Delegación
    "delegate_task": "🤝",
    "clarify": "❓",
    # Memoria
    "memory": "🧠",
    "session_search": "📜",
    # Por defecto
}

# Primary argument for preview (like Hermes)
PRIMARY_ARGS: Dict[str, str] = {
    "terminal": "command",
    "web_search": "query",
    "web_extract": "urls",
    "read_file": "path",
    "write_file": "path",
    "patch": "path",
    "search_files": "pattern",
    "browser_navigate": "url",
    "browser_click": "ref",
    "browser_type": "text",
    "image_generate": "prompt",
    "text_to_speech": "text",
    "vision_analyze": "question",
    "execute_code": "code",
    "delegate_task": "goal",
    "clarify": "question",
    "skill_view": "name",
    "skill_manage": "name",
    "cronjob": "action",
    "todo": "action",
    "memory": "action",
    "session_search": "query",
    "process": "action",
    "send_message": "message",
}


# ─────────────────────────────────────────────
# TOOL PROGRESS TRACKER
# ─────────────────────────────────────────────

class ToolProgressTracker:
    """Receives agent events and builds live progress messages.

    Uso:
        tracker = ToolProgressTracker(
            send_fn=gateway.send_message,
            edit_fn=gateway.edit_message,
            action_fn=gateway.send_chat_action,
            chat_id="12345",
            mode="new",
        )
        tracker.on_tool_start("web_search", {"query": "precio bitcoin"})
        # → edits message: "🔍 Searching the internet: \"bitcoin price\""
        tracker.on_tool_start("read_file", {"path": "/etc/config"})
        # → edits message: "🔍 Searching the internet...\\n📄 Reading file..."
    """

    def __init__(
        self,
        send_fn: Callable,
        edit_fn: Optional[Callable] = None,
        action_fn: Optional[Callable] = None,
        chat_id: str = "",
        mode: str = "all",
        preview_length: int = 40,
        edit_interval: float = 1.5,
    ):
        self._send = send_fn
        self._edit = edit_fn
        self._action = action_fn
        self._chat_id = chat_id
        self.mode = mode          # off | new | all | verbose
        self._preview_len = preview_length
        self._edit_interval = edit_interval

        # Estado interno
        self._progress_lines: List[str] = []
        self._progress_msg_id: Optional[str] = None
        self._can_edit: bool = edit_fn is not None
        self._last_edit_ts: float = 0.0
        self._last_tool: Optional[str] = None
        self._last_msg: Optional[str] = None
        self._repeat_count: int = 0
        self._lock = threading.Lock()

    # ── Eventos del agente ────────────────────

    def on_tool_start(self, tool_name: str, args: Optional[Dict] = None) -> None:
        """Llamar ANTES de ejecutar un tool. Ej: on_tool_start('web_search', {'query': '...'})"""
        if self.mode == "off":
            return
        if self.mode == "new" and tool_name == self._last_tool:
            return
        self._last_tool = tool_name

        # Enviar typing indicator
        if self._action:
            try:
                self._action(self._chat_id, "typing")
            except Exception:
                pass  # typing indicator is cosmetic — safe to ignore

        # Build message
        msg = self._build_message(tool_name, args or {})
        if not msg:
            return

        with self._lock:
            # Dedup: same consecutive message
            if msg == self._last_msg:
                self._repeat_count += 1
                if self._progress_lines:
                    self._progress_lines[-1] = f"{msg} (×{self._repeat_count + 1})"
                self._flush()
                return
            self._last_msg = msg
            self._repeat_count = 0
            self._progress_lines.append(msg)

        self._flush()

    def on_tool_end(self, tool_name: str) -> None:
        """Llamar DESPUÉS de ejecutar un tool. Opcional."""
        pass

    def on_assistant_message(self, text: str) -> None:
        """Call when the model generates text between tools.
        Muestra un mensaje separado tipo 'Déjame buscar eso primero...'"""
        if self.mode == "off" or not text or not text.strip():
            return

        clean = text.strip()[:120]
        if len(text.strip()) > 120:
            clean += "..."

        with self._lock:
            self._progress_lines.append(f"💬 {clean}")
        self._flush()

    # ── Internals ─────────────────────────────

    def _build_message(self, tool_name: str, args: Dict) -> Optional[str]:
        """Construye una línea de progreso: \"🔍 Buscando en internet...\""""
        emoji = TOOL_EMOJIS.get(tool_name, "⚡")
        tool_label = self._tool_label(tool_name)

        if self.mode == "verbose" and args:
            # Modo verbose: muestra argumentos
            if tool_name in PRIMARY_ARGS:
                preview = json.dumps(args, ensure_ascii=False)
                if self._preview_len > 0 and len(preview) > self._preview_len:
                    preview = preview[:self._preview_len - 3] + "..."
                return f"{emoji} {tool_name}({list(args.keys())})\n{preview}"
            return f"{emoji} {tool_name}..."

        # Modo normal: preview corto del argumento primario
        if tool_name in PRIMARY_ARGS:
            key = PRIMARY_ARGS[tool_name]
            val = args.get(key)
            if val is not None:
                preview = str(val)[:self._preview_len]
                if len(str(val)) > self._preview_len:
                    preview += "..."
                # Limpiar saltos de línea
                preview = preview.replace("\n", " ").strip()
                return f"{emoji} {tool_label}: \"{preview}\""

        # Tool sin preview
        return f"{emoji} {tool_label}..."

    @staticmethod
    def _tool_label(tool_name: str) -> str:
        """Readable name for the tool."""
        labels = {
            "terminal": "Ejecutando comando",
            "execute_code": "Ejecutando código",
            "web_search": "Buscando en internet",
            "web_extract": "Extrayendo página web",
            "browser_navigate": "Navegando",
            "browser_click": "Haciendo clic",
            "browser_type": "Escribiendo texto",
            "read_file": "Leyendo archivo",
            "write_file": "Escribiendo archivo",
            "patch": "Editando archivo",
            "search_files": "Buscando archivos",
            "send_message": "Enviando mensaje",
            "text_to_speech": "Generando audio",
            "image_generate": "Generando imagen",
            "vision_analyze": "Analizando imagen",
            "delegate_task": "Delegando tarea",
            "clarify": "Preguntando al usuario",
            "memory": "Guardando memoria",
            "session_search": "Buscando en sesiones",
            "cronjob": "Programando tarea",
            "todo": "Actualizando tareas",
            "skill_view": "Leyendo skill",
            "skill_manage": "Gestionando skill",
            "process": "Gestionando proceso",
            "browser_snapshot": "Capturando pantalla",
            "browser_vision": "Analizando pantalla",
            "web_scrape": "Extrayendo datos",
        }
        return labels.get(tool_name, tool_name.replace("_", " ").title())

    def _flush(self) -> None:
        """Sends or edits the progress message on Telegram."""
        if not self._progress_lines or not self._chat_id:
            return

        # Throttle: no editar más rápido que el intervalo
        now = time.monotonic()
        elapsed = now - self._last_edit_ts
        if elapsed < self._edit_interval and self._progress_msg_id is not None:
            return
        self._last_edit_ts = now

        full_text = "\n".join(self._progress_lines)

        try:
            if self._can_edit and self._progress_msg_id is not None:
                # Editar mensaje existente
                ok = self._edit(self._chat_id, self._progress_msg_id, full_text)
                if not ok:
                    self._can_edit = False
                    self._send(self._progress_lines[-1], self._chat_id)
            elif self._can_edit:
                # First message: send new
                result = self._send(full_text, self._chat_id)
                if result and hasattr(result, "message_id"):
                    self._progress_msg_id = result.message_id
                elif isinstance(result, str) and result:
                    self._progress_msg_id = result
                elif isinstance(result, bool) and result:
                    pass  # no message_id available
            else:
                # No edit: send only the last line
                self._send(self._progress_lines[-1], self._chat_id)
        except Exception as e:
            logger.warning("Failed to flush progress message: %s", e)

    def reset(self) -> None:
        """Reinicia el estado para un nuevo turno."""
        with self._lock:
            self._progress_lines = []
            self._progress_msg_id = None
            self._last_tool = None
            self._last_msg = None
            self._repeat_count = 0
            self._can_edit = self._edit is not None
            self._last_edit_ts = 0.0