"""DIGOS SystemEngineer — Ticket system with mailbox architecture."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from dataclasses import asdict

from digos_lib.constants import DIGOS_DIR, PROVIDERS
from digos_lib.core_models import Ticket
from digos_lib.core_log import LogKeeper
from digos_lib.core_vault import CajaSeguraInfo
from digos_lib.provider_api import _provider_api_request
from digos_lib.core_pipeline import TicketConversationPipeline

class SystemEngineer:
    """Receives reports, creates tickets in mailboxes per profile.

    Each profile has its own mailbox:
      ~/.digos/profiles/{perfil}/MAILBOX/{timestamp}-{seq}.json

    Los tickets se ordenan por timestamp (FIFO).
    Each agent writes to its own mailbox — no contention.
    The Engineer reads all mailboxes in order.
    No global index: the filesystem IS the index.
    """

    def __init__(self, log_keeper: LogKeeper):
        self.log = log_keeper
        self._profiles_dir = DIGOS_DIR / "profiles"
        self._pipeline: Optional[TicketConversationPipeline] = None

    def _mailbox_dir(self, profile: str) -> Path:
        return self._profiles_dir / profile / "MAILBOX"

    def _ensure_mailbox(self, profile: str):
        self._mailbox_dir(profile).mkdir(parents=True, exist_ok=True)

    def _next_ticket_id(self, profile: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        seq = 0
        mailbox = self._mailbox_dir(profile)
        if mailbox.exists():
            for f in mailbox.iterdir():
                if f.name.endswith(".json"):
                    seq += 1
        return f"{ts}-{seq:04d}"

    def _save_ticket(self, profile: str, tid: str, ticket: dict):
        self._ensure_mailbox(profile)
        tf = self._mailbox_dir(profile) / f"{tid}.json"
        tf.write_text(json.dumps(ticket, indent=2))

    def _load_ticket(self, profile: str, tid: str) -> Optional[dict]:
        tf = self._mailbox_dir(profile) / f"{tid}.json"
        if not tf.exists():
            return None
        try:
            return json.loads(tf.read_text(encoding='utf-8'))
        except Exception:
            return None

    def _iter_tickets(self, profile: str) -> List[dict]:
        mailbox = self._mailbox_dir(profile)
        if not mailbox.is_dir():
            return []
        tickets = []
        for f in sorted(mailbox.iterdir()):
            if f.name.endswith(".json"):
                try:
                    t = json.loads(f.read_text(encoding='utf-8'))
                    tickets.append(t)
                except Exception:
                    continue
        return tickets

    def receive_report(self, report: dict) -> str:
        profile = report.get("profile", "system")
        tid = self._next_ticket_id(profile)
        target = report.get("target", "")
        sev = "high" if ("api_key" in target or "telegram" in target) else "medium"
        reason = report.get('reason', 'desconocido')
        problem = f"{report.get('strikes', 3)} fallos: {reason}"
        ticket = Ticket(id=tid, profile=profile, source="centinela",
            target=target,
            problem=problem,
            severity=sev, status="open",
            created_at=datetime.now(timezone.utc).isoformat(),
            requester="centinela", flag_status="inbox")
        self._save_ticket(profile, tid, asdict(ticket))
        self.log.warn("engineer", f"🚩 Ticket #{tid} en buzón de '{profile}' (flag=inbox, centinela): {target}", {"severity": sev})

        # 🎻 Pipeline: abrir conversación automáticamente (igual que en create_ticket)
        if self._pipeline is not None:
            try:
                self.pipeline_open_for_ticket(
                    profile, tid,
                    initial_question=(
                        f"🚩 Ticket #{tid} creado por Centinela: {target}.\n"
                        f"📝 {problem[:200]}"
                    ),
                )
                self.log.info("engineer",
                    f"🎻 Pipeline abierto para ticket Centinela #{tid}")
            except Exception as e:
                self.log.warn("engineer",
                    f"⚠️ No se pudo abrir pipeline para #{tid}: {e}")

        self._diagnose(profile, tid)
        return tid

    def create_ticket(self, profile: str, target: str, problem: str,
                      severity: str = "medium", source: str = "manual",
                      requester: str = "system",
                      auto_pipeline: bool = True) -> str:
        """Crea un ticket y opcionalmente abre un pipeline de conversación.

        auto_pipeline=True:
           Al crear el ticket, también se abre un hilo de conversación
           en el TicketConversationPipeline para que el Engineer y el
           Agente puedan comunicarse fluidamente sobre este ticket.

           El agente recibe una notificación persistente de que hay un
           nuevo ticket con pipeline abierto, y puede iniciar la
           conversación directamente desde el chat.

        auto_pipeline=False:
           Solo crea el ticket. Sin pipeline. Útil para tickets masivos
           o de sistemas donde no se necesita interacción bidireccional.
        """
        tid = self._next_ticket_id(profile)
        ticket = Ticket(id=tid, profile=profile, source=source,
            target=target, problem=problem, severity=severity,
            status="open", created_at=datetime.now(timezone.utc).isoformat(),
            requester=requester, flag_status="inbox")
        self._save_ticket(profile, tid, asdict(ticket))
        self.log.info("engineer", f"🚩 Ticket #{tid} en buzón de '{profile}' (flag=inbox, requester={requester}): {target}")

        # 🎻 Pipeline: abrir conversación automáticamente
        if auto_pipeline and self._pipeline is not None:
            try:
                self.pipeline_open_for_ticket(
                    profile, tid,
                    initial_question=(
                        f"🎫 Ticket #{tid} creado por {requester}: {target}.\n"
                        f"📝 {problem[:200]}"
                    ),
                )
                self.log.info("engineer",
                    f"🎻 Pipeline abierto automáticamente para ticket #{tid}")
            except Exception as e:
                self.log.warn("engineer",
                    f"⚠️ No se pudo abrir pipeline para #{tid}: {e}")

        return tid

    def _diagnose(self, profile: str, tid: str):
        ticket = self._load_ticket(profile, tid)
        if not ticket: return
        ticket["status"] = "diagnosing"
        target = ticket["target"]
        if target.startswith("api_key:"):
            ticket["diagnosis"] = f"API key de {target.split(':')[1]} rechazada — expirada, sin saldo o revocada"
        elif target.startswith("telegram"):
            ticket["diagnosis"] = "Token de Telegram rechazado — revocado o inválido"
        else:
            ticket["diagnosis"] = "Fallo desconocido — requiere revisión manual"
        ticket["needs_human"] = True
        self._save_ticket(profile, tid, ticket)
        self.log.info("engineer", f"Ticket #{tid} diagnóstico: {ticket['diagnosis']}")

    def assign_ticket(self, profile: str, tid: str, assignee: str) -> bool:
        """Asigna un ticket a un agente de fábrica.

        ═══════════════════════════════════════════════════════
        🏭 DELEGACIÓN EXCLUSIVA DEL ENGINEER
        ═══════════════════════════════════════════════════════
        Solo el SystemEngineer puede asignar tickets a los
        agentes de fábrica (builder, auditor, reviewer).

        Los agentes NO pueden auto-asignarse tickets ni
        delegar trabajo entre sí. El Engineer es el ÚNICO
        punto de distribución.

        Una vez asignado, el agente trabaja, y el Engineer
        revisa el resultado antes de entregarlo al creador.
        ═══════════════════════════════════════════════════════
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket: return False
        ticket["assignee"] = assignee
        ticket["status"] = "assigned"
        ticket["flag_status"] = "processing"
        self._save_ticket(profile, tid, ticket)
        self.log.info("engineer", f"🏭 Ticket #{tid} asignado a {assignee} (flag=processing)")
        return True

    def update_status(self, profile: str, tid: str, status: str) -> bool:
        ticket = self._load_ticket(profile, tid)
        if not ticket: return False
        ticket["status"] = status
        # Si el agente de fábrica terminó, subir flag a review
        if status in ("review", "completed"):
            ticket["flag_status"] = "review"
        self._save_ticket(profile, tid, ticket)
        return True

    def add_note(self, profile: str, tid: str, note: str) -> bool:
        ticket = self._load_ticket(profile, tid)
        if not ticket: return False
        ticket.setdefault("notes", []).append({"text": note, "timestamp": datetime.now(timezone.utc).isoformat()})
        self._save_ticket(profile, tid, ticket)
        return True

    def close_ticket(self, profile: str, tid: str, resolution: str = "", force: bool = False) -> bool:
        """Cierra un ticket.

        ═══════════════════════════════════════════════════════
        🧪 S&D GUARD: No se puede cerrar sin pasar por testing
        ═══════════════════════════════════════════════════════
        Por defecto, solo tickets con flag_status = 'review'
        o 'delivered' pueden cerrarse (han pasado por testing).

        Usa force=True para bypass (sistema, auditoría, etc.).

        📖 Ver operations-manual.md — Sección 5: S&D Guards
          para el protocolo completo de cierre con testing.
        ═══════════════════════════════════════════════════════
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket: return False

        # ── S&D Guard: validar que el ticket pasó por testing ──
        flag = ticket.get("flag_status", "")
        if not force and flag not in ("review", "delivered"):
            self.log.warn("engineer",
                f"🚫 S&D: Ticket #{tid} no puede cerrarse sin pasar por testing "
                f"(flag={flag}). Usa submit_for_testing() + test_ticket() "
                f"primero, o force=True para bypass.")
            return False

        ticket["status"] = "closed"
        ticket["resolution"] = resolution
        ticket["closed_at"] = datetime.now(timezone.utc).isoformat()
        self._save_ticket(profile, tid, ticket)
        self.log.info("engineer", f"Ticket #{tid} cerrado: {resolution}")
        return True

    # ── Flag Persistente: S&D (Send & Deliver) ────────────────

    def submit_for_testing(self, profile: str, tid: str, work_result: str) -> bool:
        """El Engineer envía el trabajo completado a la fase de testing.

        ═══════════════════════════════════════════════════════
        🧪 S&D: SUBMIT FOR TESTING
        ═══════════════════════════════════════════════════════
        El Engineer ha terminado de procesar el ticket y lo envía
        al agente para que lo pruebe.

        flag_status: processing → testing

        Precondición: flag_status == 'processing'
        Postcondición: flag_status == 'testing', se guarda work_result

        📖 Ver operations-manual.md — Sección 3: Protocolo de Testing
          para las reglas completas de envío a testing.
        ═══════════════════════════════════════════════════════
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket:
            return False
        if ticket.get("flag_status") != "processing":
            self.log.warn("engineer",
                f"Ticket #{tid} no está en processing (flag={ticket.get('flag_status')})")
            return False
        ticket["flag_status"] = "testing"
        ticket["work_result"] = work_result
        ticket["submitted_for_testing_at"] = datetime.now(timezone.utc).isoformat()
        self._save_ticket(profile, tid, ticket)
        self.log.info("engineer",
            f"🧪 Ticket #{tid} enviado a TESTING (flag=testing)")
        return True

    def test_ticket(self, profile: str, tid: str, test_notes: str, passed: bool) -> bool:
        """El agente reporta el resultado de la prueba del ticket.

        ═══════════════════════════════════════════════════════
        🧪 S&D: TEST TICKET
        ═══════════════════════════════════════════════════════
        El agente prueba el trabajo recibido:

        ✅ PASSED (passed=True):
           flag_status: testing → review
           El Engineer revisa y entrega al creador.

        ❌ FAILED (passed=False):
           flag_status: testing → processing
           Se guardan las instrucciones de por qué falló.
           El ticket queda abierto para que el Engineer
           lo procese de nuevo con las correcciones.

        📖 Ver operations-manual.md — Sección 4: Reglas de Aceptación/Rechazo
          para los criterios de PASS/FAIL y política de reintentos.
        ═══════════════════════════════════════════════════════
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket:
            return False
        if ticket.get("flag_status") != "testing":
            self.log.warn("engineer",
                f"Ticket #{tid} no está en testing (flag={ticket.get('flag_status')})")
            return False

        # Guardar resultado de la prueba
        ticket.setdefault("test_results", []).append({
            "test_notes": test_notes,
            "passed": passed,
            "tested_at": datetime.now(timezone.utc).isoformat(),
        })

        if passed:
            # ✅ Pasó → pasar a revisión
            ticket["flag_status"] = "review"
            ticket["status"] = "review"
            self._save_ticket(profile, tid, ticket)
            self.log.info("engineer",
                f"🧪✅ Ticket #{tid} PASÓ TESTING (flag=review). Listo para entregar.")
        else:
            # ❌ Falló → regresar a processing con instrucciones
            ticket["flag_status"] = "processing"
            ticket["status"] = "in_progress"
            ticket["last_failure"] = test_notes
            self._save_ticket(profile, tid, ticket)
            self.log.info("engineer",
                f"🧪❌ Ticket #{tid} FALLÓ TESTING (flag=processing). "
                f"Razón: {test_notes[:100]}...")

        return True

    def get_profile_tickets(self, profile: str, status: str = "") -> List[dict]:
        tickets = self._iter_tickets(profile)
        if status: return [t for t in tickets if t.get("status") == status]
        return tickets

    def get_all_open(self) -> List[dict]:
        open_tickets = []
        if not self._profiles_dir.is_dir(): return []
        for p_dir in sorted(self._profiles_dir.iterdir()):
            if p_dir.is_dir() and not p_dir.name.startswith("."):
                for t in self._iter_tickets(p_dir.name):
                    if t.get("status") not in ("closed", "resolved", "cancelled"):
                        open_tickets.append(t)
        return open_tickets

    def get_by_source(self, source: str) -> List[dict]:
        results = []
        if not self._profiles_dir.is_dir(): return []
        for p_dir in sorted(self._profiles_dir.iterdir()):
            if p_dir.is_dir() and not p_dir.name.startswith("."):
                for t in self._iter_tickets(p_dir.name):
                    if t.get("source") == source: results.append(t)
        return results

    def get_by_assignee(self, assignee: str) -> List[dict]:
        results = []
        if not self._profiles_dir.is_dir(): return []
        for p_dir in sorted(self._profiles_dir.iterdir()):
            if p_dir.is_dir() and not p_dir.name.startswith("."):
                for t in self._iter_tickets(p_dir.name):
                    if t.get("assignee") == assignee: results.append(t)
        return results

    def get_ticket(self, tid: str) -> Optional[dict]:
        if not self._profiles_dir.is_dir(): return None
        for p_dir in sorted(self._profiles_dir.iterdir()):
            if p_dir.is_dir() and not p_dir.name.startswith("."):
                t = self._load_ticket(p_dir.name, tid)
                if t: return t
        return None

    def get_all_tickets(self) -> List[dict]:
        all_tickets = []
        if not self._profiles_dir.is_dir(): return []
        for p_dir in sorted(self._profiles_dir.iterdir()):
            if p_dir.is_dir() and not p_dir.name.startswith("."):
                all_tickets.extend(self._iter_tickets(p_dir.name))
        return all_tickets

    def get_open(self) -> List[dict]:
        return self.get_all_open()

    def summary(self) -> str:
        all_tickets = self.get_all_tickets()
        total = len(all_tickets)
        open_count = sum(1 for t in all_tickets if t.get("status") not in ("closed", "resolved", "cancelled"))
        profiles = set(t.get("profile", "?") for t in all_tickets)
        return f"{total} tickets, {open_count} abiertos, en {len(profiles)} perfil(es)"

    # ── Flag Persistente: Ciclo de Vida ──────────────────────────

    def pickup_ticket(self, profile: str, tid: str) -> bool:
        """El Engineer recoge un ticket de la bandeja de entrada.

        flag_status cambia de 'inbox' → 'processing'.
        El creador del ticket puede ver que ya está siendo procesado.
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket:
            return False
        if ticket.get("flag_status") != "inbox":
            self.log.warn("engineer", f"Ticket #{tid} no está en inbox (flag={ticket.get('flag_status')})")
            return False
        ticket["flag_status"] = "processing"
        ticket["picked_up_at"] = datetime.now(timezone.utc).isoformat()
        ticket["status"] = "in_progress"
        self._save_ticket(profile, tid, ticket)
        self.log.info("engineer", f"👷 Ticket #{tid} recogido por Engineer (flag=processing)")
        return True

    def deliver_ticket(self, profile: str, tid: str, result: str, resolution: str = "",
                        force: bool = False) -> bool:
        """El Engineer entrega el resultado al creador del ticket.

        🚩 FLAG SE APAGA: flag_status → 'delivered'
        El creador puede ver el resultado y el ticket se cierra.

        ═══════════════════════════════════════════════════════
        🧪 S&D GUARD: No se puede entregar sin pasar por testing
        ═══════════════════════════════════════════════════════
        Por defecto, solo tickets con flag_status = 'review'
        pueden entregarse (han pasado por testing y están listos).

        Usa force=True para bypass (sistema, auditoría, etc.).

        📖 Ver operations-manual.md — Sección 5: S&D Guards
          para el protocolo completo entrega con testing.
        ═══════════════════════════════════════════════════════
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket:
            return False

        # ── S&D Guard: validar que el ticket pasó por testing ──
        flag = ticket.get("flag_status", "")
        if not force and flag != "review":
            self.log.warn("engineer",
                f"🚫 S&D: Ticket #{tid} no puede entregarse sin pasar por testing "
                f"(flag={flag}). Usa submit_for_testing() + test_ticket() "
                f"primero, o force=True para bypass.")
            return False

        ticket["flag_status"] = "delivered"
        ticket["result"] = result
        ticket["delivered_at"] = datetime.now(timezone.utc).isoformat()
        ticket["status"] = "closed"
        if resolution:
            ticket["resolution"] = resolution
        ticket["closed_at"] = datetime.now(timezone.utc).isoformat()
        self._save_ticket(profile, tid, ticket)
        requester = ticket.get("requester", "?")
        self.log.info("engineer",
            f"🚩✅ Ticket #{tid} ENTREGADO a '{requester}' (flag=delivered → OFF)")
        return True

    def get_inbox(self, profile: str = "") -> list:
        """Devuelve tickets con flag_status = 'inbox' (trabajo esperando).

        Si se especifica un profile, solo de ese perfil.
        Si no, de todos los perfiles.
        """
        results = []
        if profile:
            tickets = self._iter_tickets(profile)
            results = [t for t in tickets if t.get("flag_status") == "inbox"]
        else:
            if not self._profiles_dir.is_dir():
                return []
            for p_dir in sorted(self._profiles_dir.iterdir()):
                if p_dir.is_dir() and not p_dir.name.startswith("."):
                    for t in self._iter_tickets(p_dir.name):
                        if t.get("flag_status") == "inbox":
                            results.append(t)
        return results

    def get_my_tickets(self, requester: str, status_filter: str = "") -> list:
        """Devuelve los tickets creados por un agente específico.

        El agente (Principal o Interno) puede ver el estado de sus
        tickets: procesando, en revisión, entregado, etc.

        requester: nombre del agente que creó el ticket
        status_filter: opcional, filtrar por flag_status
        """
        results = []
        if not self._profiles_dir.is_dir():
            return results
        for p_dir in sorted(self._profiles_dir.iterdir()):
            if p_dir.is_dir() and not p_dir.name.startswith("."):
                for t in self._iter_tickets(p_dir.name):
                    if t.get("requester") == requester:
                        if status_filter and t.get("flag_status") != status_filter:
                            continue
                        results.append(t)
        return results

    def flag_summary(self, profile: str = "") -> str:
        """Resumen de flags activos para el Engineer.

        ═══════════════════════════════════════════════════════
        🧪 S&D Pipeline completo:
           📥 Inbox → 🔧 Processing → 🧪 Testing
           → (✅ Pass → 🔍 Review) / (❌ Fail → 🔧 Processing)
           → 🚀 Delivered

        📖 Ver operations-manual.md — Sección 2: Ciclo de Vida
          para el diagrama completo y reglas del pipeline S&D.
        ═══════════════════════════════════════════════════════
        """
        inbox = self.get_inbox(profile)
        processing = []
        testing = []
        review = []
        delivered = []
        if profile:
            tickets = self._iter_tickets(profile)
        else:
            tickets = self.get_all_tickets()
        for t in tickets:
            fs = t.get("flag_status", "")
            if fs == "processing":
                processing.append(t)
            elif fs == "testing":
                testing.append(t)
            elif fs == "review":
                review.append(t)
            elif fs == "delivered":
                delivered.append(t)
        lines = [
            f"  🚩 FLAGS S&D:",
            f"     📥 Inbox (pendientes):        {len(inbox)}",
            f"     🔧 Processing (en trabajo):   {len(processing)}",
            f"     🧪 Testing (en prueba):       {len(testing)}",
            f"     🔍 Review (listo para revisar): {len(review)}",
            f"     🚀 Delivered (entregados):    {len(delivered)}",
        ]
        if inbox:
            lines.append("     ───")
            for t in inbox[:5]:
                lines.append(
                    f"     📬 #{t['id']} [{t.get('requester','?')}] {t.get('target','?')}"
                )
        return "\n".join(lines)

    def disclose_credential(self, credential_type: str, requester: str = "agente") -> dict:
        """Credential Disclosure — the user asks for THEIR credentials.

        The Tower only guards — the credentials belong to the user.
        This method:
          1. Creates a ticket documenting WHO asked and WHAT was requested
          2. Reads the credential from CajaSeguraInfo (the vault)
          3. Returns the credential to the requester
          4. Logs the disclosure for audit

        credential_type: 'api_key' | 'gateway_token' | 'provider_id' | 'all'
        Returns: {ok, credential_type, value, ticket_id, message}
        """
        vault = CajaSeguraInfo.read_slot("principal")
        if not vault:
            return {
                "ok": False,
                "credential_type": credential_type,
                "value": None,
                "ticket_id": None,
                "message": "No hay credenciales guardadas en la CajaSeguraInfo."
            }

        # Crear ticket de auditoría
        tid = self.create_ticket(
            profile="system",
            target=f"credential_disclosure:{credential_type}",
            problem=f"Usuario ({requester}) solicita ver su {credential_type}",
            severity="low",
            source="credential_disclosure",
            auto_pipeline=False,
        )
        self.add_note("system", tid, f"Disclosure solicitado por {requester} para {credential_type}")
        self.close_ticket("system", tid, f"Credencial {credential_type} entregada al usuario", force=True)

        # Leer la credencial de la caja fuerte
        if credential_type == "all":
            # Devolver todo excepto datos internos
            safe_vault = {k: v for k, v in vault.items()
                         if not k.startswith("_")}
            # Redactar parcialmente para seguridad en logs
            if "api_key" in safe_vault:
                raw = safe_vault["api_key"]
                safe_vault["api_key"] = raw  # el usuario lo ve completo
            self.log.info("engineer",
                f"Credential disclosure #{tid}: all credentials entregadas a {requester}")
            return {
                "ok": True,
                "credential_type": "all",
                "value": safe_vault,
                "ticket_id": tid,
                "message": f"Todas las credenciales entregadas. Ticket #{tid}."
            }

        if credential_type == "provider_id":
            value = vault.get("provider_id", "")
        elif credential_type in vault:
            value = vault[credential_type]
        else:
            self.log.warn("engineer",
                f"Credential disclosure #{tid}: {credential_type} no encontrado en vault")
            return {
                "ok": False,
                "credential_type": credential_type,
                "value": None,
                "ticket_id": tid,
                "message": f"No se encontró '{credential_type}' en la CajaSeguraInfo."
            }

        self.log.info("engineer",
            f"Credential disclosure #{tid}: {credential_type} entregado a {requester}")
        return {
            "ok": True,
            "credential_type": credential_type,
            "value": value,
            "ticket_id": tid,
            "message": f"Credencial '{credential_type}' entregada. Ticket #{tid}."
        }

    def rotate_credential(self, credential_type: str, new_value: str, requester: str = "agente") -> dict:
        """Credential Rotation — the user provides a NEW credential.

        The Tower is the ONLY one that stores credentials. The Agent only
        passes the key through a ticket. The Centinela only monitors.

        This method:
          1. Creates a rotation ticket for audit
          2. Validates the new credential (test connection)
          3. Stores it in CajaSeguraInfo (LA TOWER guarda)
          4. Closes the rotation ticket AND any related open tickets
          5. Resets Centinela strikes so monitoring starts fresh

        credential_type: 'api_key' | 'gateway_token'
        Returns: {ok, credential_type, ticket_id, message, provider_name}
        """
        vault = CajaSeguraInfo.read_slot("principal")
        if not vault:
            return {
                "ok": False,
                "credential_type": credential_type,
                "ticket_id": None,
                "message": "No hay CajaSeguraInfo — ejecuta el setup primero."
            }

        # Crear ticket de rotación
        tid = self.create_ticket(
            profile="system",
            target=f"credential_rotation:{credential_type}",
            problem=f"Usuario ({requester}) solicita cambiar su {credential_type}",
            severity="medium",
            source="credential_rotation",
            auto_pipeline=False,
        )
        self.add_note("system", tid, f"Rotación iniciada por {requester}")

        # Validar la nueva credencial
        if credential_type == "api_key":
            provider_id = vault.get("provider_id", "")
            ok, msg, status = _provider_api_request(provider_id, new_value)
            if not ok:
                self.add_note("system", tid, f"Validación fallida: {msg} (HTTP {status})")
                self.close_ticket("system", tid, f"Rotación cancelada — nueva API key inválida: {msg}", force=True)
                return {
                    "ok": False,
                    "credential_type": credential_type,
                    "ticket_id": tid,
                    "message": f"La nueva API key no es válida: {msg}"
                }
            self.add_note("system", tid, f"Conexión validada: {msg}")
        elif credential_type == "gateway_token":
            from urllib.request import Request, urlopen
            from urllib.error import URLError, HTTPError
            try:
                url = f"https://api.telegram.org/bot{new_value}/getMe"
                req = Request(url)
                with urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())
                    if not data.get("ok"):
                        self.add_note("system", tid, "Validación fallida: token rechazado")
                        self.close_ticket("system", tid, "Rotación cancelada — token inválido", force=True)
                        return {
                            "ok": False,
                            "credential_type": credential_type,
                            "ticket_id": tid,
                            "message": "El token de Telegram no es válido."
                        }
                    bot_name = data["result"].get("first_name", "Bot")
                    self.add_note("system", tid, f"Bot '{bot_name}' validado")
            except (HTTPError, URLError, Exception) as e:
                self.add_note("system", tid, f"Validación fallida: {e}")
                self.close_ticket("system", tid, f"Rotación cancelada — error: {e}", force=True)
                return {
                    "ok": False,
                    "credential_type": credential_type,
                    "ticket_id": tid,
                    "message": f"No se pudo validar el token: {e}"
                }
        else:
            self.close_ticket("system", tid, f"Rotación cancelada — tipo desconocido: {credential_type}", force=True)
            return {
                "ok": False,
                "credential_type": credential_type,
                "ticket_id": tid,
                "message": f"Tipo de credencial no soportado: {credential_type}"
            }

        # ── GUARDAR en CajaSeguraInfo (LA TOWER guarda, nadie más) ──
        vault[credential_type] = new_value
        vault["rotated_at"] = datetime.now(timezone.utc).isoformat()
        vault["rotated_by"] = requester
        if credential_type == "api_key":
            provider_id = vault.get("provider_id", "")
            vault["provider_name"] = PROVIDERS.get(provider_id, {}).get("name", provider_id)
        ok = CajaSeguraInfo.write_slot("principal", vault)

        if not ok:
            self.add_note("system", tid, "Error al guardar en CajaSeguraInfo")
            self.close_ticket("system", tid, "Rotación fallida — error al guardar", force=True)
            return {
                "ok": False,
                "credential_type": credential_type,
                "ticket_id": tid,
                "message": "Error al guardar la nueva credencial en CajaSeguraInfo."
            }

        # Cerrar ticket de rotación
        self.close_ticket("system", tid,
            f"Rotación exitosa: {credential_type} actualizado en CajaSeguraInfo",
            force=True)

        # ── Cerrar tickets RELACIONADOS abiertos por el Centinela ──
        related = self._find_related_credential_tickets(credential_type)
        for rt in related:
            rt_profile = rt.get("profile", "system")
            rt_tid = rt["id"]
            self.add_note(rt_profile, rt_tid,
                f"Resuelto por rotación de credencial (ticket #{tid})")
            self.close_ticket(rt_profile, rt_tid,
                f"Credencial {credential_type} rotada exitosamente",
                force=True)
            self.log.info("engineer",
                f"Ticket relacionado #{rt_tid} cerrado por rotación")

        provider_name = vault.get("provider_name", "")
        self.log.info("engineer",
            f"Credential rotation #{tid}: {credential_type} actualizado en CajaSeguraInfo")

        return {
            "ok": True,
            "credential_type": credential_type,
            "ticket_id": tid,
            "closed_related": len(related),
            "provider_name": provider_name,
            "message": f"{credential_type} actualizado correctamente en CajaSeguraInfo. "
                       f"Ticket #{tid}. El Centinela continúa su monitoreo."
        }

    def _find_related_credential_tickets(self, credential_type: str) -> List[dict]:
        """Finds open tickets related to a credential (created by Centinela)."""
        related = []
        if credential_type == "api_key":
            search_terms = ["api_key:"]
        elif credential_type == "gateway_token":
            search_terms = ["telegram"]
        else:
            return related
        open_tickets = self.get_all_open()
        for t in open_tickets:
            target = t.get("target", "")
            if t.get("source") == "centinela" and t.get("needs_human"):
                for term in search_terms:
                    if term in target:
                        related.append(t)
                        break
        return related

    def get_credential_tickets_needing_user(self) -> List[dict]:
        """Returns open tickets from Centinela that need user input.

        These are tickets where the Centinela detected:
          - API key invalid/expired
          - Telegram token invalid/revoked
        And the ticket has needs_human=True, waiting for the user.

        The Agent receives these and asks the user for a new credential.
        """
        tickets = []
        open_tickets = self.get_all_open()
        for t in open_tickets:
            if (t.get("source") == "centinela"
                    and t.get("needs_human")
                    and t.get("status") not in ("closed", "resolved", "cancelled")):
                target = t.get("target", "")
                if "api_key" in target or "telegram" in target:
                    tickets.append(t)
        return tickets

    def create_internal_agent(
        self,
        agent_type: str,
        mode: str = "collaborative",
        name: str = "",
        mission: str = "",
        requester: str = "agente",
        factory_create_fn: callable = None,
    ) -> dict:
        """Create an internal agent through the Factory.

        This is the bridge between the DIGOS ticket system and the Factory.
        The user says "crea 2 builders en modo aislado" and the Agent routes
        the request here. The SystemEngineer creates an audit ticket, then
        delegates to the Factory (via factory_create_fn callback).

        agent_type: 'builder' | 'auditor' | 'reviewer'
        mode: ☑️ 'collaborative' | ☑️ 'isolated'
        factory_create_fn: callback that does the actual creation in the Factory

        Returns: {ok, agent_name, agent_type, mode, ticket_id, message}
        """
        if agent_type not in ("builder", "auditor", "reviewer"):
            return {
                "ok": False,
                "agent_name": None,
                "agent_type": agent_type,
                "mode": mode,
                "ticket_id": None,
                "message": f"Tipo de agente desconocido: {agent_type}. Usa builder, auditor, o reviewer."
            }

        if mode not in ("collaborative", "isolated"):
            return {
                "ok": False,
                "agent_name": None,
                "agent_type": agent_type,
                "mode": mode,
                "ticket_id": None,
                "message": f"Modo desconocido: {mode}. Usa 'collaborative' o 'isolated'."
            }

        # Crear ticket de auditoría
        tid = self.create_ticket(
            profile="system",
            target=f"internal_agent:{agent_type}",
            problem=f"Usuario ({requester}) solicita crear agente interno: {agent_type} ({mode})",
            severity="low",
            source="agent_creation",
            auto_pipeline=False,
        )

        agent_name = name or f"{agent_type}_{tid.split('-')[0]}"

        # Delegar a la Factoría (via callback)
        if factory_create_fn is None:
            self.add_note("system", tid, "Factory no disponible — callback no configurado")
            return {
                "ok": False,
                "agent_name": agent_name,
                "agent_type": agent_type,
                "mode": mode,
                "ticket_id": tid,
                "message": "La Factoría no está disponible en este momento."
            }

        try:
            agent = factory_create_fn(agent_type, mode, agent_name, mission)
        except Exception as e:
            self.add_note("system", tid, f"Error creando agente en Factory: {e}")
            self.close_ticket("system", tid, f"Fallo — Factory no pudo crear el agente: {e}", force=True)
            return {
                "ok": False,
                "agent_name": agent_name,
                "agent_type": agent_type,
                "mode": mode,
                "ticket_id": tid,
                "message": f"Error al crear el agente en la Factoría: {e}"
            }

        if agent is None:
            self.add_note("system", tid, "Factory devolvió None — tipo de agente no soportado")
            self.close_ticket("system", tid, "Fallo — tipo de agente no soportado", force=True)
            return {
                "ok": False,
                "agent_name": agent_name,
                "agent_type": agent_type,
                "mode": mode,
                "ticket_id": tid,
                "message": f"No se pudo crear el agente tipo '{agent_type}'."
            }

        # Éxito
        actual_name = agent.name
        self.add_note("system", tid,
            f"Agente '{actual_name}' ({agent_type}, {mode}) creado en la Factoría")
        self.close_ticket("system", tid,
            f"Agente '{actual_name}' ({agent_type}, {mode}) creado exitosamente",
            force=True)
        self.log.info("engineer",
            f"Internal agent created: {actual_name} ({agent_type}, {mode}), ticket #{tid}")

        return {
            "ok": True,
            "agent_name": actual_name,
            "agent_type": agent_type,
            "mode": mode,
            "ticket_id": tid,
            "message": f"Agente '{actual_name}' ({agent_type}) creado en modo {mode}. Ticket #{tid}."
        }

    def create_capability_request(
        self,
        capability: str,
        family: str,
        sub_intent: str,
        user_message: str,
        requester: str = "agente",
        factory_create_fn=None,
    ) -> dict:
        """Create a ticket for a new capability detected via intent classification.

        When the AIAgent detects a capability gap (e.g., user wants voice but we
        don't have STT), this method creates an audit ticket and records the
        request for the Factory to process.

        capability: e.g., "stt_audio_input", "web_browsing"
        family: e.g., "VOICE", "WEB", "NEW_TOOL"
        sub_intent: e.g., "VOICE_INPUT_CAPABILITY_REQUEST"
        user_message: the original user message that triggered this
        factory_create_fn: optional callback that receives the capability name
            and returns the corresponding CapabilitySkillDefinition from
            CAPABILITY_SKILL_MAP. Simulates the Factory's role in mapping
            capability gaps to skills.

        Returns: {ok, ticket_id, capability, skill, message}
                  skill is None if no factory_create_fn is provided
        """
        tid = self.create_ticket(
            profile="system",
            target=f"capability_request:{capability}",
            problem=(
                f"Usuario ({requester}) quiere una capacidad que no existe.\n"
                f"Familia: {family}\n"
                f"Sub-intención: {sub_intent}\n"
                f"Mensaje original: {user_message[:200]}"
            ),
            severity="medium",
            source="intent_classifier",
            auto_pipeline=True,
        )
        self.add_note("system", tid,
            f"Capability gap detectado: {capability} ({family}/{sub_intent})")

        # 🏭 Factory callback: simula que la Factoría recibe la capability
        # y devuelve el skill correspondiente de CAPABILITY_SKILL_MAP
        skill_result = None
        if factory_create_fn is not None:
            try:
                skill_result = factory_create_fn(capability)
                if skill_result is not None:
                    skill_name = getattr(skill_result, 'skill_name', str(skill_result))
                    self.add_note("system", tid,
                        f"🏭 Factory recibió capability '{capability}' → skill '{skill_name}'")
                    self.log.info("engineer",
                        f"🏭 Factory processó capability '{capability}': {skill_name}")
                else:
                    self.add_note("system", tid,
                        f"🏭 Factory no encontró skill para '{capability}'")
                    self.log.warn("engineer",
                        f"🏭 Factory sin skill para capability '{capability}'")
            except Exception as e:
                self.add_note("system", tid, f"⚠️ Factory callback error: {e}")
                self.log.warn("engineer",
                    f"⚠️ Factory callback falló para capability '{capability}': {e}")

        self.log.info("engineer",
            f"Capability request #{tid}: {capability} ({family}) — {sub_intent}")

        return {
            "ok": True,
            "ticket_id": tid,
            "capability": capability,
            "family": family,
            "sub_intent": sub_intent,
            "skill": skill_result,
            "message": f"Solicitud de capacidad '{capability}' registrada. Ticket #{tid}."
        }

    # ── PIPELINE DE CONVERSACIÓN (TicketConversationPipeline) ──────
    # Bridge methods — delegan al TicketConversationPipeline
    # que se inicializa en TorreDeControl y se asigna aquí.

    def pipeline_open(self, ticket_id: str, participants=None,
                      initial_message: str = "") -> bool:
        """Abre un hilo de conversación para un ticket."""
        if not self._pipeline:
            return False
        return self._pipeline.open_conversation(
            ticket_id, participants, initial_message)

    def pipeline_send(self, ticket_id: str, sender: str, content: str,
                      msg_type: str = "info", metadata=None) -> str:
        """Envía un mensaje en el pipeline de un ticket."""
        if not self._pipeline:
            return ""
        return self._pipeline.send_message(
            ticket_id, sender, content, msg_type, metadata)

    def pipeline_get_messages(self, ticket_id: str,
                              include_read: bool = True) -> list:
        """Obtiene los mensajes del pipeline de un ticket."""
        if not self._pipeline:
            return []
        return self._pipeline.get_messages(ticket_id, include_read)

    def pipeline_get_unread(self, participant: str = "agente") -> list:
        """Obtiene mensajes no leídos para un participante."""
        if not self._pipeline:
            return []
        return self._pipeline.get_unread(participant)

    def pipeline_get_unread_count(self, participant: str = "agente") -> int:
        """Cuenta mensajes no leídos para un participante."""
        if not self._pipeline:
            return 0
        return self._pipeline.get_unread_count(participant)

    def pipeline_mark_read(self, ticket_id: str, participant: str,
                           message_id: str = "") -> int:
        """Marca mensajes como leídos."""
        if not self._pipeline:
            return 0
        return self._pipeline.mark_read(ticket_id, participant, message_id)

    def pipeline_resolve(self, ticket_id: str,
                         resolution_msg: str = "") -> bool:
        """Cierra la conversación de un ticket."""
        if not self._pipeline:
            return False
        return self._pipeline.resolve_conversation(
            ticket_id, resolution_msg)

    def pipeline_get_status(self, ticket_id: str) -> dict:
        """Obtiene estado de la conversación de un ticket."""
        if not self._pipeline:
            return {"error": "pipeline no disponible"}
        return self._pipeline.get_conversation_status(ticket_id) or {}

    def pipeline_get_active(self) -> list:
        """Obtiene todas las conversaciones activas."""
        if not self._pipeline:
            return []
        return self._pipeline.get_active_conversations()

    def pipeline_get_summary_for_agent(self) -> str:
        """Resumen de mensajes pendientes para el agente principal."""
        if not self._pipeline:
            return ""
        return self._pipeline.get_summary_for_agent("agente")

    def pipeline_get_summary_for_engineer(self) -> str:
        """Resumen de actividad del pipeline para el Engineer."""
        if not self._pipeline:
            return ""
        return self._pipeline.get_summary_for_engineer()

    def pipeline_cycle(self) -> list:
        """Ciclo de mantenimiento del pipeline."""
        if not self._pipeline:
            return []
        return self._pipeline.cycle()

    def pipeline_open_for_ticket(self, profile: str, tid: str,
                                 initial_question: str = "") -> bool:
        """Abre automáticamente un pipeline para un ticket existente.

        Conveniencia: cuando el Engineer recoge un ticket y necesita
        hacer preguntas al agente, este método abre el hilo de
        conversación y envía la primera pregunta.
        """
        ticket = self._load_ticket(profile, tid)
        if not ticket:
            return False

        # Abrir conversación
        opened = self.pipeline_open(
            tid,
            participants=["engineer", "agente"],
            initial_message=initial_question or (
                f"Ticket #{tid}: {ticket.get('target', '')} — "
                f"{ticket.get('problem', '')[:100]}"
            ),
        )
        if opened:
            self.log.info("engineer",
                f"🎻 Pipeline abierto para ticket #{tid}")
        return opened

    def resolve(self, tid: str, resolution: str):
        ticket = self.get_ticket(tid)
        if ticket:
            profile = ticket.get("profile", "")
            if profile: self.close_ticket(profile, tid, resolution, force=True)
