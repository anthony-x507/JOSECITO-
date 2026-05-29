#!/usr/bin/env python3
"""
DIGOS Message Bus — Multi-Agent Communication via Unix Sockets
================================================================
Local messaging system between DIGOS agents using Unix Domain Sockets.
No TCP ports required, no external dependencies.

Two operation modes:   🔒 ISOLATED — The agent only sees TorreDeControl. Does not know others exist.
  🤝 COLLABORATIVE — The agent sees the agent directory and can communicate.

The USER decides the mode. TorreDeControl only activates/deactivates based on what
the user orders through their agent.

Arquitectura:
  TorreDeControl (broker central)
    ├── Socket principal: /tmp/digos/tower.sock
    ├── josecito:   /tmp/digos/josecito.sock   [colaborativo]
    ├── alex:       /tmp/digos/alex.sock       [colaborativo]
    ├── freya:      /tmp/digos/freya.sock      [aislado]
    └── yarimae:    /tmp/digos/yarimae.sock    [aislado]

Protocol (JSON over Unix socket):
  {"cmd": "send",    "to": "alex", "content": "..."}
  {"cmd": "broadcast","topic": "alerta", "content": "..."}
  {"cmd": "list",    "filter": "collaborative"}
  Respuesta: {"type": "message", "from": "josecito", "content": "..."}

No external dependencies. stdlib only (socket, json, os, threading).
"""

import json
import os
import select
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable, Set


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

BUS_DIR = Path("/tmp/digos")
TOWER_SOCKET = BUS_DIR / "tower.sock"

AGENT_MODES = {"isolated": "🔒", "collaborative": "🤝"}


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────


@dataclass
class AgentEndpoint:
    """Represents an agent connected to the bus."""
    name: str
    socket_path: str
    mode: str               # "isolated" | "collaborative"
    connected: bool = False
    subscribed_topics: Set[str] = field(default_factory=lambda: {"system"})
    last_seen: float = 0.0


@dataclass
class BusMessage:
    """Message on the bus."""
    msg_type: str           # "message" | "broadcast" | "command" | "response"
    sender: str
    recipient: str = ""     # "" para broadcast
    content: str = ""
    topic: str = ""
    timestamp: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(data: dict) -> "BusMessage":
        return BusMessage(
            msg_type=data.get("type", "message"),
            sender=data.get("from", ""),
            recipient=data.get("to", ""),
            content=data.get("content", ""),
            topic=data.get("topic", ""),
            timestamp=time.time(),
        )


# ─────────────────────────────────────────────
# AGENT CONNECTION (lado del agente)
# ─────────────────────────────────────────────


class AgentBusClient:
    """Bus client — connects to the agent socket from within the agent.

    Uso (modo colaborativo):
        client = AgentBusClient("alex", mode="collaborative")
        client.connect()
        client.send("josecito", "Hola hermano!")
        messages = client.poll()

    Uso (modo aislado):
        client = AgentBusClient("freya", mode="isolated")
        client.connect()
        # Can only receive from TorreDeControl
        client.send_to_supervisor("Usuario pide X")
    """

    MAX_MESSAGE_SIZE = 1_000_000  # 1MB max per message

    def __init__(self, agent_name: str, mode: str = "isolated"):
        self._name = agent_name
        self._mode = mode
        self._socket_path = BUS_DIR / f"{agent_name}.sock"
        self._sock: Optional[socket.socket] = None
        self._connected = False
        self._buffer = b""
        self._buffer_lock = threading.Lock()

    def connect(self) -> bool:
        """Connects to the agent socket."""
        try:
            BUS_DIR.mkdir(parents=True, exist_ok=True)
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(5.0)
            self._sock.connect(str(self._socket_path))
            self._connected = True
            self._sock.settimeout(0.1)  # no-blocking después de conectar

            # Registrar modo
            self._send_raw({
                "cmd": "register",
                "name": self._name,
                "mode": self._mode,
            })
            return True
        except (socket.error, FileNotFoundError) as e:
            self._connected = False
            return False

    def disconnect(self):
        """Disconnects from the bus."""
        if self._sock:
            try:
                self._send_raw({"cmd": "unregister"})
                self._sock.close()
            except Exception:
                pass
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._sock is not None

    def send(self, to: str, content: str) -> bool:
        """Sends a message to another agent (collaborative mode only)."""
        if self._mode == "isolated" and to != "tower":
            return False
        return self._send_raw({
            "cmd": "send",
            "to": to,
            "content": content,
        })

    def send_to_supervisor(self, content: str) -> bool:
        """Sends a message to the supervisor (TorreDeControl). Available in both modes."""
        return self._send_raw({
            "cmd": "send",
            "to": "tower",
            "content": content,
        })

    def broadcast(self, topic: str, content: str) -> bool:
        """Broadcasts to all agents subscribed to the topic."""
        return self._send_raw({
            "cmd": "broadcast",
            "topic": topic,
            "content": content,
        })

    def list_agents(self, filter_mode: str = "") -> Optional[list]:
        """Requests list of connected agents. Collaborative mode only."""
        if self._mode == "isolated":
            return None
        # Enviar request con ID único
        req_id = str(uuid.uuid4())[:8]
        self._send_raw({"cmd": "list", "filter": filter_mode, "req_id": req_id})
        # Wait for response with timeout
        deadline = time.time() + 3.0
        while time.time() < deadline:
            resp = self._read_line()
            if resp:
                try:
                    data = json.loads(resp)
                    if data.get("type") == "agent_list":
                        return data.get("agents", [])
                except json.JSONDecodeError:
                    continue
            time.sleep(0.05)
        return None

    def poll(self, timeout: float = 0.5) -> List[BusMessage]:
        """Reads pending messages."""
        messages = []
        if not self._connected or not self._sock:
            return messages
        try:
            deadline = time.time() + timeout
            self._sock.settimeout(min(timeout, 0.5))
            with self._buffer_lock:
                while time.time() < deadline:
                    try:
                        data = self._sock.recv(4096)
                    except socket.timeout:
                        break
                    if not data:
                        break
                    if len(self._buffer) + len(data) > self.MAX_MESSAGE_SIZE:
                        self._buffer = b""
                        break
                    self._buffer += data
                    while b"\n" in self._buffer:
                        line, self._buffer = self._buffer.split(b"\n", 1)
                        if line.strip():
                            try:
                                msg_data = json.loads(line.decode())
                                msg = BusMessage.from_json(msg_data)
                                messages.append(msg)
                            except (json.JSONDecodeError, KeyError):
                                continue
        except Exception:
            self._connected = False
        return messages

    def switch_mode(self, new_mode: str):
        """Changes the agent's mode (requested by the user).
        Waits for server confirmation before changing."""
        if new_mode not in AGENT_MODES:
            return
        self._send_raw({
            "cmd": "switch_mode",
            "mode": new_mode,
        })
        # Esperar confirmacion del servidor
        deadline = time.time() + 3.0
        while time.time() < deadline:
            resp = self._read_line()
            if resp:
                try:
                    data = json.loads(resp)
                    if data.get("type") == "mode_changed":
                        self._mode = new_mode
                        return
                except Exception:
                    pass
            time.sleep(0.05)

    # ── Internals ──

    def _send_raw(self, data: dict) -> bool:
        if not self._connected or not self._sock:
            return False
        try:
            payload = json.dumps(data) + "\n"
            self._sock.sendall(payload.encode())
            return True
        except Exception:
            self._connected = False
            return False

    def _read_line(self) -> str:
        if not self._sock:
            return ""
        with self._buffer_lock:
            try:
                while b"\n" not in self._buffer:
                    chunk = self._sock.recv(4096)
                    if not chunk:
                        break
                    if len(self._buffer) + len(chunk) > self.MAX_MESSAGE_SIZE:
                        self._buffer = b""
                        break
                    self._buffer += chunk
                if b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    return line.decode().strip()
            except Exception:
                pass
        return ""


# ─────────────────────────────────────────────
# MESSAGE BUS (lado de TorreDeControl)
# ─────────────────────────────────────────────


class MessageBus:
    """Message Bus central — corre dentro de TorreDeControl.

    TorreDeControl creates a bus instance and then:
      bus.register_agent("josecito", "collaborative")
      bus.register_agent("freya", "isolated")
      bus.start()  # empieza a escuchar

    When an agent connects, the bus handles message routing.
    """

    def __init__(self):
        self._agents: Dict[str, AgentEndpoint] = {}
        self._connections: Dict[str, socket.socket] = {}
        self._conn_to_name: Dict[int, str] = {}  # O(1) lookup por conexion
        self._conn_write_locks: Dict[int, threading.Lock] = {}  # lock por conexion
        self._agent_sockets: Dict[str, socket.socket] = {}
        self._tower_sock: Optional[socket.socket] = None
        self._running = False
        self._lock = threading.Lock()
        self._on_message: Optional[Callable] = None
        self._thread: Optional[threading.Thread] = None
        # Semáforo: máximo 8 conexiones concurrentes de agentes
        # Sin esto, cada conexión crea un hilo sin límite → fuga de hilos
        self._connection_semaphore = threading.Semaphore(8)

    MAX_MESSAGE_SIZE = 1_000_000  # 1MB max per connection buffer

    def set_message_callback(self, callback: Callable):
        """Callback when a message arrives. TorreDeControl uses it for logging."""
        self._on_message = callback

    def register_agent(self, name: str, mode: str = "isolated"):
        """Registers an agent in the bus and creates its socket immediately."""
        socket_path = BUS_DIR / f"{name}.sock"
        agent = AgentEndpoint(
            name=name,
            socket_path=str(socket_path),
            mode=mode,
        )
        with self._lock:
            self._agents[name] = agent
        # Create socket immediately (do not wait for _run)
        sock = self._create_agent_socket(name)
        if sock:
            with self._lock:
                self._agent_sockets[name] = sock
        return agent

    def unregister_agent(self, name: str):
        """Removes an agent from the bus and closes its connection."""
        with self._lock:
            self._agents.pop(name, None)
            sock = self._connections.pop(name, None)
            if sock:
                conn_id = id(sock)
                self._conn_to_name.pop(conn_id, None)
                self._conn_write_locks.pop(conn_id, None)
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        socket_path = BUS_DIR / f"{name}.sock"
        try:
            socket_path.unlink(missing_ok=True)
        except Exception:
            pass

    def get_mode(self, name: str) -> str:
        """Returns an agent's mode."""
        with self._lock:
            agent = self._agents.get(name)
            return agent.mode if agent else "isolated"

    def switch_mode(self, name: str, new_mode: str) -> bool:
        """Changes an agent's mode."""
        if new_mode not in AGENT_MODES:
            return False
        with self._lock:
            agent = self._agents.get(name)
            if not agent:
                return False
            agent.mode = new_mode
        return True

    def list_agents(self, filter_mode: str = "") -> List[dict]:
        """Lists connected agents. If filter_mode, only those of that mode."""
        with self._lock:
            agents = []
            for name, agent in self._agents.items():
                if filter_mode and agent.mode != filter_mode:
                    continue
                agents.append({
                    "name": name,
                    "mode": agent.mode,
                    "connected": agent.connected,
                    "last_seen": agent.last_seen,
                })
            return agents

    # ── Iniciar/Detener ──

    def start(self):
        """Inicia el bus en un hilo separado."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Detiene el bus."""
        self._running = False
        # Close agent connections
        for name in list(self._connections.keys()):
            self.unregister_agent(name)
        # El semáforo se recupera solo cuando los handler threads
        # terminan y llaman release(). No crear uno nuevo — eso
        # permitiría que threads viejos inflen el contador > 8.

    def _run(self):
        """Main bus loop."""
        BUS_DIR.mkdir(parents=True, exist_ok=True)

        # Limpiar sockets huérfanos de ejecuciones anteriores
        # (only sockets that do not belong to registered agents)
        active_sockets = set(str(p) for p in self._agent_sockets.keys())
        for f in sorted(BUS_DIR.iterdir()):
            if f.suffix == ".sock":
                sock_name = f.stem  # nombre sin .sock
                if sock_name not in active_sockets:
                    try:
                        f.unlink()
                    except Exception:
                        pass

        # The bus uses per-agent sockets (not the tower socket)
        self._tower_sock = None

        while self._running:
            try:
                # Reconstruir lista de sockets en cada iteración
                # to capture agents registered after start()
                with self._lock:
                    all_sockets = list(self._agent_sockets.values())

                readable, _, _ = self._select_wrapper(all_sockets, timeout=1.0)
                if not readable:
                    continue

                for sock in readable:
                    try:
                        conn, _ = sock.accept()
                        # Semáforo: adquirir antes de crear hilo
                        # Si no hay slot disponible, rechazar conexión
                        if not self._connection_semaphore.acquire(blocking=False):
                            conn.close()
                            self._notify(
                                "Conexión rechazada: máximo de conexiones simultáneas alcanzado (8)")
                            continue
                        # try/finally: si la creación del thread falla, liberar semáforo
                        try:
                            t = threading.Thread(
                                target=self._handle_agent_connection,
                                args=(conn,),
                                daemon=True,
                            )
                            t.start()
                        except Exception:
                            self._connection_semaphore.release()
                            conn.close()
                            continue
                    except BlockingIOError:
                        continue
                    except Exception:
                        continue

            except Exception as e:
                self._notify(f"Error en loop del bus: {e}")
                continue

        # Limpieza
        with self._lock:
            for sock in self._agent_sockets.values():
                try:
                    sock.close()
                except Exception:
                    pass

    def _create_agent_socket(self, name: str) -> Optional[socket.socket]:
        """Creates a Unix socket for an agent."""
        socket_path = BUS_DIR / f"{name}.sock"
        try:
            socket_path.unlink(missing_ok=True)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.bind(str(socket_path))
            sock.listen(5)
            os.chmod(str(socket_path), 0o600)
            return sock
        except Exception:
            return None

    def _handle_agent_connection(self, conn: socket.socket):
        """Handles an incoming connection from an agent."""
        conn.settimeout(30.0)  # 30s timeout para evitar bloqueos largos
        buffer = b""

        try:
            while self._running:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    # Timeout largo permite mantener conexion idle
                    continue
                if not data:
                    break
                if len(buffer) + len(data) > self.MAX_MESSAGE_SIZE:
                    buffer = b""
                    self._notify("Buffer overflow en conexión de agente")
                    break
                buffer += data

                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue

                    try:
                        msg = json.loads(line.decode())
                        self._process_message(msg, conn)
                    except json.JSONDecodeError:
                        continue

        except (socket.timeout, ConnectionError):
            pass
        except Exception as e:
            self._notify(f"Error en conexión de agente: {e}")
        finally:
            # Liberar slot del semáforo (ocurra lo que ocurra con la conexión)
            try:
                self._connection_semaphore.release()
            except ValueError:
                pass  # Semaphore liberado sin acquire (no debería pasar)
            try:
                conn.close()
            except Exception:
                pass
            # Clean stale connection — también limpiar write locks
            stale_name = self._find_agent_by_conn_real(conn)
            if stale_name:
                with self._lock:
                    self._connections.pop(stale_name, None)
                    self._conn_to_name.pop(id(conn), None)
            # Siempre limpiar el write lock del socket (aunque no haya nombre)
            with self._lock:
                self._conn_write_locks.pop(id(conn), None)

    def _process_message(self, msg: dict, conn: socket.socket):
        """Processes an incoming message."""
        cmd = msg.get("cmd", "")

        if cmd == "register":
            name = msg.get("name", "")
            mode = msg.get("mode", "isolated")
            with self._lock:
                agent = self._agents.get(name)
                if agent:
                    agent.connected = True
                    agent.last_seen = time.time()
                    # Inline _register_conn dentro del mismo lock
                    # para evitar race condition: otro hilo podría
                    # eliminar el agente entre el unlock y _register_conn.
                    # threading.Lock no es reentrante, pero aquí no
                    # hay llamada anidada — todo es trabajo directo.
                    self._connections[name] = conn
                    self._conn_to_name[id(conn)] = name
                    self._conn_write_locks[id(conn)] = threading.Lock()
            self._notify(f"Agent '{name}' registered ({mode})")

        elif cmd == "unregister":
            name = self._find_agent_by_conn(conn)
            if name:
                self.unregister_agent(name)
                self._notify(f"Agent '{name}' unregistered")

        elif cmd == "send":
            self._route_message(msg, conn)

        elif cmd == "broadcast":
            self._broadcast(msg)

        elif cmd == "list":
            filter_mode = msg.get("filter", "")
            agents = self.list_agents(filter_mode)
            self._send_to_conn(conn, {
                "type": "agent_list",
                "agents": agents,
            })

        elif cmd == "switch_mode":
            name = self._find_agent_by_conn(conn)
            new_mode = msg.get("mode", "")
            if name and self.switch_mode(name, new_mode):
                self._notify(f"Agent '{name}' switched to {new_mode}")
                self._send_to_conn(conn, {
                    "type": "mode_changed",
                    "mode": new_mode,
                })
                # Notificar a los demás agentes colaborativos
                self._broadcast({
                    "topic": "system",
                    "content": f"Agent '{name}' is now {new_mode}",
                })

    def _route_message(self, msg: dict, conn: socket.socket):
        """Enruta un mensaje al destinatario."""
        sender = self._find_agent_by_conn(conn)
        recipient = msg.get("to", "")
        content = msg.get("content", "")

        if not sender:
            return

        # If sender is in isolated mode, can only send to tower
        sender_agent = self._agents.get(sender)
        if sender_agent and sender_agent.mode == "isolated" and recipient != "tower":
            self._send_to_conn(conn, {
                "type": "error",
                "content": "Isolated agents can only message TorreDeControl",
            })
            return

        if recipient == "tower":
            # Message for TorreDeControl
            self._notify(f"From {sender}: {content[:100]}")
            return

        # Enrutar al destinatario
        recipient_conn = self._connections.get(recipient)
        if recipient_conn:
            self._send_to_conn(recipient_conn, {
                "type": "message",
                "from": sender,
                "content": content,
            })
            self._notify(f"Routed: {sender} → {recipient}")
        else:
            self._send_to_conn(conn, {
                "type": "error",
                "content": f"Agent '{recipient}' not connected",
            })

    def _broadcast(self, msg: dict):
        """Broadcast a todos los agentes colaborativos."""
        topic = msg.get("topic", "general")
        content = msg.get("content", "")
        sender = msg.get("from", "tower")

        with self._lock:
            for name, agent in self._agents.items():
                if not agent.connected:
                    continue
                if topic not in agent.subscribed_topics and topic != "system":
                    continue
                sock = self._connections.get(name)
                if sock:
                    try:
                        self._send_to_conn(sock, {
                            "type": "broadcast",
                            "from": sender,
                            "topic": topic,
                            "content": content,
                        })
                    except Exception as e:
                        self._notify(f"Error enviando broadcast a {name}: {e}")

    def _send_to_conn(self, conn: socket.socket, data: dict):
        """Sends JSON data to a connection with per-connection lock.
        Uses a short send timeout to prevent blocking the bus.
        """
        # Save original timeout and set a short send timeout
        orig_timeout = None
        try:
            orig_timeout = conn.gettimeout()
            conn.settimeout(5.0)  # 5s max for sending
        except Exception:
            pass

        try:
            lock = self._conn_write_locks.get(id(conn))
            if lock:
                with lock:
                    try:
                        payload = json.dumps(data) + "\n"
                        conn.sendall(payload.encode())
                    except Exception as e:
                        self._notify(f"Error enviando datos (lock): {e}")
            else:
                try:
                    payload = json.dumps(data) + "\n"
                    conn.sendall(payload.encode())
                except Exception as e:
                        self._notify(f"Error enviando datos: {e}")

        finally:
            # Restore original timeout
            if orig_timeout is not None:
                try:
                    conn.settimeout(orig_timeout)
                except Exception:
                    pass

    def _register_conn(self, name: str, conn: socket.socket):
        """Registra conexion O(1)."""
        with self._lock:
            self._connections[name] = conn
            self._conn_to_name[id(conn)] = name
            self._conn_write_locks[id(conn)] = threading.Lock()

    def _find_agent_by_conn(self, conn: socket.socket) -> Optional[str]:
        """O(1) lookup por id de socket."""
        with self._lock:
            return self._conn_to_name.get(id(conn))

    def _find_agent_by_conn_real(self, conn: socket.socket) -> Optional[str]:
        """Fallback O(n)."""
        with self._lock:
            for name, sock in self._connections.items():
                if sock == conn:
                    return name
        return None

    def _notify(self, message: str):
        """Notifica a TorreDeControl via callback."""
        if self._on_message:
            try:
                self._on_message(message)
            except Exception:
                pass

    @staticmethod
    def _select_wrapper(sockets: list, timeout: float = 1.0):
        """Wrapper para select.select con manejo de errores."""
        try:
            return select.select(sockets, [], [], timeout)
        except (ValueError, TypeError):
            return [], [], []

    # ── Estado ──

    def status(self) -> dict:
        """Estado completo del bus."""
        with self._lock:
            return {
                "running": self._running,
                "agents": [
                    {
                        "name": agent.name,
                        "mode": agent.mode,
                        "connected": agent.connected,
                        "icon": AGENT_MODES.get(agent.mode, "❓"),
                    }
                    for agent in self._agents.values()
                ],
            }

    def print_status(self):
        """Imprime estado del bus."""
        status = self.status()
        print()
        print("  📡 MESSAGE BUS — Estado")
        print(f"  {'─' * 45}")
        print(f"  {'🟢' if status['running'] else '🔴'} Bus: {'Activo' if status['running'] else 'Detenido'}")
        print(f"  Agentes: {len(status['agents'])}")
        for agent in status['agents']:
            icon = agent['icon']
            conn = "🟢" if agent['connected'] else "⚫"
            print(f"    {icon} {conn} {agent['name']} ({agent['mode']})")
        print()