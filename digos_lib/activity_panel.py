"""
DIGOS Activity Panel — Live terminal activity display.
=======================================================
Shows real-time agent activities with contextual emojis.
Auto-collapses when the agent finishes processing.

Features:
  • Rich emoji set for 20+ activity types grouped by context
  • Box-drawn terminal panel with ANSI escape codes
  • Live updates — only the panel changes, no scroll pollution
  • Auto-collapse — final response appears cleanly after panel closes
  • Thread-safe — callbacks can fire from any thread
  • Graceful fallback — no-op if stdout is not a TTY

Usage:
    panel = ActivityPanel()
    panel.open()
    panel.show("🔍", "Searching the internet")
    panel.show("📂", "Reading files...")
    panel.show("🐍", "Writing Python code")
    response = panel.close("Final answer here")
    # → panel vanishes, only the answer remains on screen

Override with panel.close(...) to wrap the final response.
Use panel.hide() + print(response) for split control.
"""

import re
import shutil
import signal as _signal
import sys
import threading
import time
from typing import Optional, Dict, List, Tuple, Callable


# ─────────────────────────────────────────────
# ANSI ESCAPE CODES
# ─────────────────────────────────────────────

_SAVE = "\033[s"        # Save cursor position
_RESTORE = "\033[u"      # Restore cursor position
_CLEAR_DOWN = "\033[J"   # Clear from cursor to end of screen
_CLEAR_LINE = "\033[K"   # Clear current line
_HIDE = "\033[?25l"      # Hide cursor
_SHOW = "\033[?25h"      # Show cursor
_RESET = "\033[0m"       # Reset all attributes
_BOLD = "\033[1m"        # Bold
_DIM = "\033[2m"         # Dim
_GREEN = "\033[38;5;40m" # Green text
_BLUE = "\033[38;5;33m"  # Blue text
_WHITE = "\033[38;5;15m" # White text
_GRAY = "\033[38;5;245m" # Gray text


# ─────────────────────────────────────────────
# ACTIVITY CONFIG — emoji + label for 20+ types
# ─────────────────────────────────────────────
# Each entry: (emoji, label_template, category)
# category is used for grouping in the panel

ACTIVITY_CONFIG: Dict[str, Tuple[str, str, str]] = {
    # ═══ TERMINAL & CODE ═══
    "terminal":        ("💻", "Ejecutando comando", "code"),
    "execute_code":    ("🐍", "Ejecutando código Python", "code"),
    "python":          ("🐍", "Escribiendo código Python", "code"),
    "code_generation": ("⚡", "Generando código", "code"),
    "write_file":      ("📝", "Escribiendo archivo", "code"),
    "patch":           ("🔧", "Modificando código", "code"),

    # ═══ SEARCH & DISCOVERY ═══
    "web_search":      ("🔍", "Buscando en internet", "search"),
    "search_files":    ("🔎", "Buscando en archivos", "search"),
    "glob":            ("📂", "Localizando archivos", "search"),
    "list_directory":  ("📁", "Explorando directorios", "search"),

    # ═══ WEB & BROWSER ═══
    "web_extract":     ("🌐", "Extrayendo página web", "web"),
    "web_scrape":      ("🕸️", "Analizando datos web", "web"),
    "browser_navigate": ("🧭", "Navegando sitio web", "web"),
    "browser_click":   ("🖱️", "Interactuando con página", "web"),
    "browser_type":    ("⌨️", "Escribiendo en navegador", "web"),
    "browser_snapshot": ("📃", "Capturando pantalla", "web"),
    "browser_vision":  ("👁️", "Analizando pantalla", "web"),

    # ═══ FILES & STORAGE ═══
    "read_file":       ("📄", "Leyendo archivo", "files"),
    "file_read":       ("📄", "Leyendo archivo", "files"),
    "file_write":      ("💾", "Guardando archivo", "files"),
    "file_search":     ("🔎", "Buscando en archivos", "files"),

    # ═══ FACTORY & CAPABILITIES ═══
    "factory":         ("🏗️", "Construyendo en la Fábrica", "factory"),
    "create_capability": ("🎫", "Solicitando nueva capacidad", "factory"),
    "skill_request":   ("📦", "Preparando skill", "factory"),
    "sandbox":         ("🧪", "Probando en Sandbox", "factory"),
    "sandbox_test":    ("🧪", "Probando en Sandbox", "factory"),
    "builder":         ("🤖", "Builder creando módulo", "factory"),
    "auditor":         ("🔍", "Auditor verificando calidad", "factory"),
    "reviewer":        ("✅", "Reviewer aprobando cambios", "factory"),
    "pipeline":        ("🔗", "Procesando pipeline", "factory"),

    # ═══ TOWER & SYSTEM ═══
    "tower":           ("🏰", "Consultando Torre de Control", "system"),
    "centinela":       ("🛡️", "Ejecutando check de seguridad", "system"),
    "engineer":        ("👷", "Procesando ticket", "system"),
    "cronjob":         ("⏰", "Programando tarea recurrente", "system"),
    "process":         ("⚙️", "Procesando solicitud", "system"),
    "deploy":          ("🚀", "Desplegando cambios", "system"),
    "rotation":        ("🔄", "Rotando credenciales", "system"),
    "disclosure":      ("🔑", "Recuperando credenciales", "system"),

    # ═══ KNOWLEDGE & MEMORY ═══
    "memory":          ("🧠", "Consultando memoria del agente", "knowledge"),
    "session_search":  ("📜", "Buscando en sesiones anteriores", "knowledge"),
    "skill_view":      ("📖", "Leyendo skill", "knowledge"),
    "skill_manage":    ("🛠️", "Gestionando skills", "knowledge"),

    # ═══ COMMUNICATION ═══
    "send_message":    ("📨", "Enviando mensaje", "comm"),
    "text_to_speech":  ("🎤", "Generando audio de voz", "comm"),
    "image_generate":  ("🎨", "Generando imagen", "comm"),
    "vision_analyze":  ("👁️", "Analizando imagen", "comm"),
    "delegate_task":   ("🤝", "Delegando tarea a agente", "comm"),
    "clarify":         ("💬", "Preguntando al usuario", "comm"),

    # ═══ PLANNING & ORGANIZATION ═══
    "plan":            ("📋", "Planificando pasos siguientes", "plan"),
    "todo":            ("✅", "Actualizando lista de tareas", "plan"),
    "think":           ("🤔", "Analizando información", "plan"),
}


def _get_activity(name: str) -> Tuple[str, str, str]:
    """Resolve an activity config by name, falling back to defaults."""
    if name in ACTIVITY_CONFIG:
        return ACTIVITY_CONFIG[name]
    # Try prefix match
    for key, val in ACTIVITY_CONFIG.items():
        if name.startswith(key):
            return val
    return ("⚡", f"{name.replace('_', ' ').title()}", "other")


# ─────────────────────────────────────────────
# ACTIVITY PANEL
# ─────────────────────────────────────────────

# ANSI escape pattern for stripping
_ANSI_RE = re.compile(r'\033\[[0-9;]*m')

# Default header with the original styling (bold title, blue subtitle)
_DEFAULT_HEADER = f"{_BOLD}\U0001f916 DIGOS{_RESET} \u2014 {_BLUE}Actividad en curso...{_RESET}"


class ActivityPanel:
    """Live terminal activity panel with auto-collapse.

    Thread-safe: all public methods acquire a lock before mutating state.
    No-op when stdout is not a TTY.

    Parameters
    ----------
    stream : IO, optional
        Output stream (default: sys.stdout).
    width : int
        Total panel width in characters (default: 52).
        Set to 0 to auto-detect from the terminal width at open time.
    max_visible : int
        Max activity lines before overflow truncation (default: 8).
    header : str, optional
        Custom header line. May include ANSI escape codes for styling.
        The visible length is automatically padded to align the right border.
        Default: bold "🤖 DIGOS" — blue "Actividad en curso...".
    animation_delay : float
        Seconds per line for the collapse animation (default: 0.03).
    collapse_style : str
        Collapse animation style: "line-by-line" (rolls up),
        "fade" (dims lines one by one), or "instant" (no animation).
    auto_resize : bool
        If True, listen for SIGWINCH (terminal resize) and
        re-render the panel at the new terminal width.
        Only available on Unix-like systems; no-op on Windows.
        Requires *width=0* to auto-detect the new width.

    Example
    -------
    panel = ActivityPanel()
    panel.open()
    panel.show("\U0001f50d", "Buscando en internet")
    panel.show("\U0001f4c2", "Leyendo archivos")
    final = panel.close("Aquí está la respuesta")
    # \u2192 panel hidden, only "Aquí está la respuesta" is visible
    """

    STYLES = {"line-by-line", "fade", "instant"}

    _SIGWINCH = getattr(_signal, "SIGWINCH", None)  # None on Windows

    def __init__(self, stream=None, width: int = 52, max_visible: int = 8, header: str = None,
                 animation_delay: float = 0.03, collapse_style: str = "line-by-line",
                 auto_resize: bool = False):
        self._stream = stream or sys.stdout
        self._is_tty = self._stream.isatty()
        self._lock = threading.Lock()
        self._opened = False
        self._lines: List[str] = []
        self._max_visible = max_visible
        self._panel_width = width
        self._header = header if header is not None else _DEFAULT_HEADER
        self._anim_delay = animation_delay  # seconds per line during collapse
        if collapse_style not in self.STYLES:
            raise ValueError(f"collapse_style must be one of {self.STYLES}, got {collapse_style!r}")
        self._collapse_style = collapse_style
        self._auto_resize = auto_resize and self._SIGWINCH is not None
        self._orig_sigwinch = None
        self._resize_pending = False

    # ── Lifecycle ────────────────────────────────

    def _install_sigwinch(self):
        """Register the SIGWINCH handler if auto_resize is enabled."""
        if not self._auto_resize or self._SIGWINCH is None:
            return
        if not threading.current_thread() is threading.main_thread():
            return  # signal.signal() requires main thread
        try:
            self._orig_sigwinch = _signal.signal(self._SIGWINCH, self._on_sigwinch)
        except (ValueError, OSError):
            self._orig_sigwinch = None

    def _restore_sigwinch(self):
        """Restore the previous SIGWINCH handler."""
        if self._orig_sigwinch is None or self._SIGWINCH is None:
            return
        if not threading.current_thread() is threading.main_thread():
            return
        try:
            _signal.signal(self._SIGWINCH, self._orig_sigwinch)
        except (ValueError, OSError):
            pass
        self._orig_sigwinch = None

    def _on_sigwinch(self, signum, frame):
        """Signal handler: flags a pending resize (thread-safe, no lock)."""
        self._resize_pending = True

    def _check_resize(self):
        """If a resize is pending, re-read terminal width.

        The caller (_render) will draw the panel after this returns,
        so we just update the width without triggering a draw.
        """
        if not self._resize_pending or not self._opened:
            return
        self._resize_pending = False
        if self._panel_width == 0:
            cols = shutil.get_terminal_size().columns
            self._panel_width = max(30, cols - 2)

    def open(self):
        """Open the panel: save cursor, draw initial frame, hide cursor.

        If *width* was set to 0 (auto-detect), the panel width is
        read from the terminal at open time.
        """
        if not self._is_tty:
            return
        with self._lock:
            if self._opened:
                return
            # Auto-detect terminal width if requested
            if self._panel_width == 0:
                cols = shutil.get_terminal_size().columns
                self._panel_width = max(30, cols - 2)
            self._opened = True
            self._lines = []
            self._install_sigwinch()
            self._stream.write(_SAVE)
            self._stream.write(_HIDE)
            self._render()
            self._stream.flush()

    def close(self, final_message: str = "") -> str:
        """Close the panel, erase it, show cursor, and return the final message.

        After calling close(), the terminal will appear as if the panel
        was never there — only the final_message remains on screen (if any).
        """
        if not self._is_tty:
            return final_message
        with self._lock:
            if not self._opened:
                return final_message
            self._animate_collapse()
            self._erase()
            self._stream.write(_SHOW)
            self._stream.flush()
            self._opened = False
            self._lines = []
            self._restore_sigwinch()
        return final_message

    def hide(self):
        """Same as close() but returns the captured lines for custom output."""
        if not self._is_tty:
            return
        with self._lock:
            if not self._opened:
                return
            self._animate_collapse()
            self._erase()
            self._stream.write(_SHOW)
            self._stream.flush()
            self._opened = False
            self._lines = []
            self._restore_sigwinch()

    # ── Content ──────────────────────────────────

    def show(self, tool_name: str, label: str = "", preview: str = ""):
        """Add or update a line in the panel.

        If *label* is empty, it is resolved from ACTIVITY_CONFIG.
        If *preview* is provided, it's appended after the label.
        """
        if not self._is_tty:
            return
        if not label:
            _emoji, label, _cat = _get_activity(tool_name)
        emoji, _, _cat = _get_activity(tool_name)
        text = f"{emoji} {label}"
        if preview:
            preview = preview.replace("\n", " ").strip()
            if len(preview) > 36:
                preview = preview[:33] + "..."
            text += f"  {_GRAY}{preview}{_RESET}"
        with self._lock:
            if not self._opened:
                return
            # Replace duplicate, otherwise append
            for i, line in enumerate(self._lines):
                if line.startswith(emoji[:2]):
                    self._lines[i] = text
                    self._render()
                    return
            self._lines.append(text)
            self._render()

    def update_message(self, text: str):
        """Show a brief assistant message in the panel (e.g., "Let me look that up...")."""
        if not self._is_tty or not text:
            return
        clean = text.strip()[:60]
        if len(text.strip()) > 60:
            clean += "..."
        with self._lock:
            if not self._opened:
                return
            # Replace any existing 💬 line, or add a new one
            for i, line in enumerate(self._lines):
                if line.startswith("💬"):
                    self._lines[i] = f"💬 {_GRAY}{clean}{_RESET}"
                    self._render()
                    return
            self._lines.append(f"💬 {_GRAY}{clean}{_RESET}")
            self._render()

    def _mark_as(self, tool_name: str, replacement_emoji: str):
        """Replace a tool's leading emoji with *replacement_emoji*.

        Shared helper for mark_done (✅) and mark_failed (❌).
        Falls back to *replacement_emoji* if the original emoji can't be
        stripped cleanly.
        """
        if not self._is_tty:
            return False
        emoji, _label, _cat = _get_activity(tool_name)
        with self._lock:
            if not self._opened:
                return False
            for i, line in enumerate(self._lines):
                if line.startswith(emoji[:2]):
                    rest = line[len(emoji):] if line.startswith(emoji) else line[2:]
                    self._lines[i] = f"{replacement_emoji}{rest}"
                    self._render()
                    return True
        return False

    def mark_done(self, tool_name: str):
        """Mark a tool as completed by replacing its emoji with ✅."""
        self._mark_as(tool_name, "✅")

    def mark_failed(self, tool_name: str):
        """Mark a tool as failed by replacing its emoji with ❌."""
        self._mark_as(tool_name, "❌")

    def set_header(self, header: str):
        """Update the header text after construction.

        If *header* is None, resets to the default header.
        If the panel is currently open, it re-renders immediately.
        Thread-safe.
        """
        if not self._is_tty:
            return
        with self._lock:
            self._header = header if header is not None else _DEFAULT_HEADER
            if self._opened:
                self._render()

    def set_collapse_style(self, style: str):
        """Change the collapse animation style after construction.

        Parameters
        ----------
        style : str
            One of "line-by-line", "fade", or "instant".

        Raises
        ------
        ValueError
            If *style* is not a valid style name.
        """
        if style not in self.STYLES:
            raise ValueError(f"collapse_style must be one of {self.STYLES}, got {style!r}")
        self._collapse_style = style

    def clear(self):
        """Clear all activity lines (keep panel open)."""
        if not self._is_tty:
            return
        with self._lock:
            self._lines = []
            self._render()

    # ── Rendering ────────────────────────────────

    def _render(self):
        """Redraw the panel at the saved cursor position.

        Checks for pending terminal resize first.
        """
        self._check_resize()
        self._stream.write(_RESTORE)
        self._stream.write(_CLEAR_DOWN)
        self._draw_box(self._lines)
        self._stream.flush()

    def _animate_collapse(self):
        """Animate the panel collapsing before erasing.

        Dispatches to the selected style:

        * **line-by-line** — pops content lines from bottom, box shrinks upward
        * **fade** — dims each content line in-place from bottom to top
        * **instant** — no animation, returns immediately

        Skips entirely if *animation_delay* is 0 or there are no content lines.
        """
        if self._anim_delay <= 0 or not self._lines or self._collapse_style == "instant":
            return
        if self._collapse_style == "line-by-line":
            self._animate_line_by_line()
        elif self._collapse_style == "fade":
            self._animate_fade()

    def _animate_line_by_line(self):
        """Roll-up: remove lines from bottom one at a time."""
        remaining = list(self._lines)
        while remaining:
            remaining.pop()
            self._stream.write(_RESTORE)
            self._stream.write(_CLEAR_DOWN)
            self._draw_box(remaining)
            self._stream.flush()
            time.sleep(self._anim_delay)

    def _animate_fade(self):
        """Fade: dim each content line in-place from bottom to top."""
        faded = list(self._lines)
        for idx in range(len(faded) - 1, -1, -1):
            # Strip existing ANSI codes, wrap with dim
            plain = _ANSI_RE.sub("", faded[idx]).strip()
            faded[idx] = f"{_DIM}{plain}{_RESET}"
            self._stream.write(_RESTORE)
            self._stream.write(_CLEAR_DOWN)
            self._draw_box(faded)
            self._stream.flush()
            time.sleep(self._anim_delay)

    def _erase(self):
        """Erase everything from the saved position down."""
        self._stream.write(_RESTORE)
        self._stream.write(_CLEAR_DOWN)
        self._stream.flush()

    def _draw_box(self, lines: List[str]):
        """Draw the panel border with content lines."""
        w = self._panel_width
        inner_w = w - 4  # 2 chars border + 2 padding

        # ── Cap lines ──
        if len(lines) > self._max_visible:
            overflow = len(lines) - self._max_visible + 1
            display = lines[:self._max_visible - 1] + [f"⋯ {_GRAY}+{overflow} más{_RESET}"]
        else:
            display = list(lines)

        self._stream.write(f"┌{'─' * (w - 2)}┐\n")
        # Header with dynamic padding
        plain_header = _ANSI_RE.sub('', self._header)
        header_pad = max(0, w - 4 - len(plain_header))
        self._stream.write(f"│  {self._header}{' ' * header_pad}│\n")
        self._stream.write(f"├{'─' * (w - 2)}┤\n")

        for line in display:
            # Strip ANSI codes for length calculation
            plain = line.replace(_GRAY, "").replace(_RESET, "").replace(_DIM, "")
            plain_len = len(plain)
            padding = max(0, inner_w - plain_len)
            self._stream.write(f"│  {line}{' ' * padding}│\n")

        self._stream.write(f"└{'─' * (w - 2)}┘\n")
