"""DIGOS Gateways — Plugin communication channels (CLI, Telegram)."""
import json
import os
import sys
import time
import threading
import signal
import queue
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

class BaseGateway:
    """Base gateway — communication plugin.
    Each gateway implements: start, stop, health_check, send_message.
    """

    def __init__(self, gw_id: str, name: str, gw_type: str):
        self.id = gw_id
        self.name = name
        self.type = gw_type
        self.status = "stopped"  # stopped, running, error, connecting
        self._running = False
        self._log = None

    def set_logger(self, log_keeper):
        self._log = log_keeper

    def start(self):
        raise NotImplementedError

    def stop(self):
        self._running = False
        self.status = "stopped"

    def health_check(self) -> bool:
        raise NotImplementedError

    def status_info(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type, "status": self.status}


class GatewayCLI(BaseGateway):
    """Terminal gateway — interactive stdin/stdout via background thread.

    Un daemon thread lee de stdin línea por línea y encola los mensajes
    en una cola thread-safe. TorreDeControl los recoge llamando a
    get_updates() en su loop principal.
    """

    def __init__(self):
        super().__init__("cli", "CLI Terminal", "terminal")
        self._poll_thread: Optional[threading.Thread] = None
        self._update_queue: queue.Queue = queue.Queue()

    def start(self):
        self._running = True
        self.status = "running"
        if self._log:
            self._log.info("gateway-cli", "Gateway CLI iniciado (thread de stdin activo)")
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="cli-poll",
            daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self):
        """Loop de lectura de stdin en thread separado.
        Lee línea por línea y encola como mensaje de texto.
        """
        import sys as _sys
        while self._running:
            try:
                _sys.stdout.write("→ ")
                _sys.stdout.flush()
                line = _sys.stdin.readline()
                if not line:  # EOF (Ctrl+D)
                    if self._log:
                        self._log.info("gateway-cli", "EOF en stdin — deteniendo")
                    break
                line = line.strip()
                if not line:
                    continue
                self._update_queue.put({
                    "type": "text",
                    "text": line,
                    "chat_id": "cli",
                    "date": time.time(),
                })
            except (EOFError, KeyboardInterrupt):
                break

    def get_updates(self) -> list:
        """Drena la cola de mensajes recibidos por el thread de stdin.
        Non-blocking: retorna lista vacía si no hay mensajes.
        """
        updates = []
        while not self._update_queue.empty():
            try:
                updates.append(self._update_queue.get_nowait())
            except queue.Empty:
                break
        return updates

    def health_check(self) -> bool:
        return self._running

    def send_message(self, msg: str, **kw):
        print(f"\n  {msg}\n")

    def stop(self):
        self._running = False
        self.status = "stopped"
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=3)
        if self._log:
            self._log.info("gateway-cli", "Gateway CLI detenido")


class GatewayTelegram(BaseGateway):
    """Telegram gateway via long-polling. stdlib only (urllib + json).

    En daemon mode, un thread interno hace long-polling cada ~10s y
    encola los mensajes en una cola thread-safe. TorreDeControl los
    recoge llamando a get_updates() en su loop principal.
    """

    def __init__(self, token: str = ""):
        super().__init__("telegram", "Telegram Bot", "telegram")
        self._token = token
        self._offset = 0
        self._base_url = f"https://api.telegram.org/bot{token}" if token else ""
        self._poll_thread: Optional[threading.Thread] = None
        self._update_queue: queue.Queue = queue.Queue()

    def start(self):
        if not self._token:
            self.status = "error"
            if self._log:
                self._log.error("gateway-tg", "Token vacío — no se puede iniciar")
            return
        self._running = True
        self.status = "running"
        # Lanzar thread de polling que hace long-polling a Telegram
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="tg-poll",
            daemon=True,
        )
        self._poll_thread.start()
        if self._log:
            self._log.info("gateway-tg", "Gateway Telegram iniciado (thread de polling activo)")
        print(f"  🤖 Telegram Gateway listo (token: ...{self._token[-6:]})")

    def health_check(self) -> bool:
        if not self._running or not self._token:
            return False
        try:
            import urllib.request
            url = self._base_url + "/getMe"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read())
                return data.get("ok", False)
        except Exception:
            return False

    def poll_updates(self) -> list:
        """Gets new messages from Telegram — text, voice, photo, audio, document, video.

        Each returned dict has:
          - chat_id, message_id, date (always)
          - type: "text" | "voice" | "photo" | "audio" | "document" | "video" | "video_note"
          - For text: "text" field with the message content
          - For media: "file_id", "mime_type", "caption" (optional), "duration" (audio/voice/video)
          - edited: True if this is an edited message (edit_date also present)
          - edit_date: unix timestamp of the edit (only present if edited)
        """
        if not self._running or not self._token:
            return []
        try:
            import urllib.request
            url = f"{self._base_url}/getUpdates?offset={self._offset}&timeout=10"
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            if not data.get("ok"):
                if self._log:
                    self._log.warn("gateway-tg", f"getUpdates respondió ok=false: {data.get('description', 'sin descripción')}")
                return []
            updates = []
            for upd in data.get("result", []):
                self._offset = upd["update_id"] + 1

                # Procesar tanto mensajes nuevos como editados
                is_edited = False
                if "message" in upd:
                    msg = upd["message"]
                elif "edited_message" in upd:
                    msg = upd["edited_message"]
                    is_edited = True
                else:
                    continue

                parsed = self._parse_message(msg)
                if parsed:
                    if is_edited:
                        parsed["edited"] = True
                    updates.append(parsed)
            return updates
        except HTTPError as e:
            if self._log:
                self._log.error("gateway-tg", f"HTTP {e.code} en getUpdates: {e.reason}")
            return []
        except URLError as e:
            if self._log:
                self._log.warn("gateway-tg", f"Red/timeout en getUpdates: {e.reason}")
            return []
        except json.JSONDecodeError as e:
            if self._log:
                self._log.error("gateway-tg", f"JSON inválido en getUpdates: {e}")
            return []
        except Exception as e:
            if self._log:
                self._log.error("gateway-tg", f"Error inesperado en getUpdates: {e}")
            return []

    @staticmethod
    def _parse_message(msg: dict) -> Optional[dict]:
        """Parses a raw Telegram message into a normalized dict.

        Extracts chat_id, message_id, date, and determines type + content.
        Returns None if the message has no processable content.
        """
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        message_id = str(msg.get("message_id", ""))
        date = msg.get("date", 0)

        if not chat_id:
            return None

        base = {
            "chat_id": chat_id,
            "message_id": message_id,
            "date": date,
        }

        # edit_date presente cuando el mensaje fue editado
        if "edit_date" in msg:
            base["edit_date"] = msg["edit_date"]

        # ── Text ──
        if "text" in msg and msg["text"]:
            base["type"] = "text"
            base["text"] = msg["text"]
            return base

        # ── Voice ──
        if "voice" in msg:
            voice = msg["voice"]
            base["type"] = "voice"
            base["file_id"] = voice.get("file_id", "")
            base["mime_type"] = voice.get("mime_type", "audio/ogg")
            base["duration"] = voice.get("duration", 0)
            base["file_size"] = voice.get("file_size", 0)
            if msg.get("caption"):
                base["caption"] = msg["caption"]
            return base

        # ── Audio ──
        if "audio" in msg:
            audio = msg["audio"]
            base["type"] = "audio"
            base["file_id"] = audio.get("file_id", "")
            base["mime_type"] = audio.get("mime_type", "audio/mpeg")
            base["duration"] = audio.get("duration", 0)
            base["file_size"] = audio.get("file_size", 0)
            if msg.get("caption"):
                base["caption"] = msg["caption"]
            return base

        # ── Photo ──
        if "photo" in msg:
            # Telegram sends multiple sizes — pick the largest (last one)
            photos = msg["photo"]
            largest = photos[-1] if photos else {}
            base["type"] = "photo"
            base["file_id"] = largest.get("file_id", "")
            base["file_size"] = largest.get("file_size", 0)
            base["width"] = largest.get("width", 0)
            base["height"] = largest.get("height", 0)
            if msg.get("caption"):
                base["caption"] = msg["caption"]
            return base

        # ── Document ──
        if "document" in msg:
            doc = msg["document"]
            base["type"] = "document"
            base["file_id"] = doc.get("file_id", "")
            base["mime_type"] = doc.get("mime_type", "application/octet-stream")
            base["file_name"] = doc.get("file_name", "")
            base["file_size"] = doc.get("file_size", 0)
            if msg.get("caption"):
                base["caption"] = msg["caption"]
            return base

        # ── Video ──
        if "video" in msg:
            video = msg["video"]
            base["type"] = "video"
            base["file_id"] = video.get("file_id", "")
            base["mime_type"] = video.get("mime_type", "video/mp4")
            base["duration"] = video.get("duration", 0)
            base["file_size"] = video.get("file_size", 0)
            if msg.get("caption"):
                base["caption"] = msg["caption"]
            return base

        # ── Video Note (circular video) ──
        if "video_note" in msg:
            vn = msg["video_note"]
            base["type"] = "video_note"
            base["file_id"] = vn.get("file_id", "")
            base["duration"] = vn.get("duration", 0)
            base["file_size"] = vn.get("file_size", 0)
            if msg.get("caption"):
                base["caption"] = msg["caption"]
            return base

        # ── Sticker, location, etc. — no processable ──
        return None

    def get_file(self, file_id: str) -> Optional[dict]:
        """Gets file metadata from Telegram.

        Returns dict with file_path, file_size, etc. on success.
        Returns None on failure.

        Example result:
          {"file_id": "...", "file_path": "voice/file_0.ogg", "file_size": 12345}
        """
        if not self._token or not file_id:
            return None
        try:
            import urllib.request
            url = f"{self._base_url}/getFile?file_id={file_id}"
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read())
            if data.get("ok") and "result" in data:
                return data["result"]
            return None
        except Exception:
            return None

    def download_file(self, file_path: str, dest_path: str) -> bool:
        """Downloads a file from Telegram's servers.

        Args:
            file_path: Telegram file path from get_file() (e.g., "voice/file_0.ogg")
            dest_path: Local path to save the file

        Returns True on success.
        """
        if not self._token or not file_path:
            return False
        try:
            import urllib.request
            from pathlib import Path

            download_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"

            # Ensure destination directory exists
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            with urllib.request.urlopen(download_url, timeout=60) as r:
                dest.write_bytes(r.read())

            return dest.exists() and dest.stat().st_size > 0
        except Exception:
            return False

    def send_message(self, msg: str, chat_id: str = "", **kw) -> str:
        """Sends a message. Returns message_id string if ok, '' if fails."""
        if not self._token or not chat_id:
            return ""
        try:
            import urllib.request
            payload = json.dumps({"chat_id": chat_id, "text": msg}).encode()
            req = urllib.request.Request(
                self._base_url + "/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
                if data.get("ok") and data.get("result", {}).get("message_id"):
                    return str(data["result"]["message_id"])
                return ""
        except Exception:
            return ""

    def edit_message(self, chat_id: str, message_id: str, text: str) -> bool:
        """Edits an existing message. Returns True if ok."""
        if not self._token or not chat_id or not message_id:
            return False
        try:
            import urllib.request
            payload = json.dumps({
                "chat_id": chat_id,
                "message_id": int(message_id),
                "text": text,
            }).encode()
            req = urllib.request.Request(
                self._base_url + "/editMessageText",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read()).get("ok", False)
        except Exception:
            return False

    def send_chat_action(self, chat_id: str, action: str = "typing") -> bool:
        """Envía indicador de actividad (typing, upload_photo, etc.)."""
        if not self._token or not chat_id:
            return False
        try:
            import urllib.request
            payload = json.dumps({"chat_id": chat_id, "action": action}).encode()
            req = urllib.request.Request(
                self._base_url + "/sendChatAction",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read()).get("ok", False)
        except Exception:
            return False

    def _poll_loop(self):
        """Loop de long-polling en thread separado.
        Hace getUpdates con timeout=10, parsea los mensajes,
        y los encola para que TorreDeControl los procese.

        Nota: poll_updates() maneja errores internamente (timeout, red,
        JSON) y retorna lista vacía — no necesita wrapper adicional.
        """
        while self._running:
            updates = self.poll_updates()  # bloquea ~10-15s, maneja errores
            for msg in updates:
                self._update_queue.put(msg)

    def get_updates(self) -> list:
        """Drena la cola de mensajes recibidos por el thread de polling.
        Non-blocking: retorna lista vacía si no hay mensajes.

        Úsalo en el loop principal de TorreDeControl en vez de
        poll_updates() para no bloquear el loop con HTTP.
        """
        updates = []
        while not self._update_queue.empty():
            try:
                updates.append(self._update_queue.get_nowait())
            except queue.Empty:
                break
        return updates

    def stop(self):
        self._running = False
        self.status = "stopped"
        if self._poll_thread and self._poll_thread.is_alive():
            # Esperar a que termine la petición HTTP actual (máx 20s)
            self._poll_thread.join(timeout=20)
        if self._log:
            self._log.info("gateway-tg", "Gateway Telegram detenido")
