#!/usr/bin/env python3
"""
DIGOS Adoption Engine — Phase 5: Multi-Agent
=============================================
Migrates existing profiles from Hermes or OpenClaw to DIGOS.

Flow:
  1. detect()       → looks for ~/.hermes/ and ~/.openclaw/
  2. discover()     → lists migrable profiles and resources
  3. preview()      → shows what will be migrated (dry-run)
  4. migrate()      → executes the migration
  5. report()       → what was migrated, what was skipped

No external dependencies. stdlib only.
"""

import json
import os
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

DIGOS_HOME = Path.home() / ".digos"
HERMES_HOME = Path.home() / ".hermes"
OPENCLAW_HOME = Path.home() / ".openclaw"

# Secrets that can be safely migrated
MIGRABLE_SECRETS = {
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "ELEVENLABS_API_KEY",
    "GROQ_API_KEY",
    "MISTRAL_API_KEY",
    "COHERE_API_KEY",
    "TOGETHER_API_KEY",
    "FIREWORKS_API_KEY",
    "XAI_API_KEY",
    "GOOGLE_API_KEY",
    "FAL_KEY",
    "EXA_API_KEY",
    "TAVILY_API_KEY",
    "FIRECRAWL_API_KEY",
    "PARALLEL_API_KEY",
    "BROWSERBASE_API_KEY",
    "BROWSER_USE_API_KEY",
    "CAMOFOX_URL",
    "USER_TIMEZONE",
    "HERMES_LOCAL_STT_COMMAND",
}

# High-impact items that require warning
HIGH_IMPACT_KINDS: Dict[str, str] = {
    "telegram_token": "⚠️ Telegram — apuntará DIGOS a tu bot de Telegram existente",
    "gateway_config": "⚠️ Gateway — configuración de mensajería será transferida",
    "api_key": "🔑 API ...adas",
    "skills": "📚 Skills — habilidades del agente migradas",
    "memory": "🧠 Memoria — recuerdos del agente migrados",
    "config": "⚙️ Config — ajustes del agente migrados",
    "profile": "👤 Perfil — perfil de usuario completo migrado",
}


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────


@dataclass
class MigrableItem:
    """An individual item that can be migrated."""
    source: str             # "hermes" | "openclaw"
    profile: str            # nombre del perfil (ej: "josecito", "alex")
    kind: str               # "config", "env", "skill", "memory", "telegram_token", etc.
    source_path: str        # ruta de origen
    dest_path: str          # ruta de destino en DIGOS
    size_bytes: int = 0     # tamaño del archivo
    warning: str = ""       # advertencia de alto impacto


@dataclass
class AdoptionReport:
    """Complete adoption report."""
    source: str
    profiles_found: List[str] = field(default_factory=list)
    items_migrated: List[MigrableItem] = field(default_factory=list)
    items_skipped: List[MigrableItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: float = 0.0

    def summary(self) -> str:
        total = len(self.items_migrated)
        skipped = len(self.items_skipped)
        err = len(self.errors)
        return f"{total} migrado(s), {skipped} omitido(s), {err} error(es)"


# ─────────────────────────────────────────────
# ADOPTION ENGINE
# ─────────────────────────────────────────────


class AdoptionEngine:
    """Adoption engine — detects, previews and migrates from Hermes/OpenClaw."""

    def __init__(self, digos_home: Path = DIGOS_HOME):
        self._digos = digos_home
        self._report = AdoptionReport(source="", timestamp=time.time())

    # ── 1. DETECT ─────────────────────────────

    def detect_sources(self) -> List[str]:
        """Detects which systems exist on this machine.
        Returns: ["hermes"], ["openclaw"], ["hermes", "openclaw"], or [].
        """
        found = []
        if HERMES_HOME.is_dir():
            found.append("hermes")
        if OPENCLAW_HOME.is_dir():
            found.append("openclaw")
        return found

    # ── 2. DISCOVER ───────────────────────────

    def discover(self, source: str) -> AdoptionReport:
        """Discovers which profiles and resources are migrable from a source."""
        self._report = AdoptionReport(source=source, timestamp=time.time())

        if source == "hermes":
            self._discover_hermes()
        elif source == "openclaw":
            self._discover_openclaw()

        return self._report

    def _discover_hermes(self):
        """Discovers Hermes profiles."""
        profiles_dir = HERMES_HOME / "profiles"

        # Found profiles
        if profiles_dir.is_dir():
            profiles = sorted([
                p.name for p in profiles_dir.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            ])
        else:
            profiles = []

        self._report.profiles_found = profiles

        # Global Hermes profile (main config)
        self._add_item("hermes", "global", "config",
                       HERMES_HOME / "config.yaml",
                       self._digos / "imported" / "hermes" / "config.yaml")

        # Global .env (API keys, tokens)
        env_file = HERMES_HOME / ".env"
        if env_file.exists():
            secrets = self._parse_env(env_file)
            self._add_item("hermes", "global", "env",
                           env_file, self._digos / "imported" / "hermes" / ".env")
            for key in secrets:
                if key in MIGRABLE_SECRETS:
                    kind = "api_key" if "KEY" in key else "telegram_token" if "TOKEN" in key else "env"
                    self._add_item("hermes", "global", kind,
                                   f".env:{key}", f"secrets/{key}")

        # Global skills
        skills_dir = HERMES_HOME / "skills"
        if skills_dir.is_dir():
            for skill in sorted(skills_dir.iterdir()):
                if skill.is_dir():
                    self._add_item("hermes", "global", "skills",
                                   skill, self._digos / "imported" / "hermes" / "skills" / skill.name)

        # For each profile
        for profile in self._report.profiles_found:
            profile_dir = profiles_dir / profile

            # profile config.yaml
            cfg = profile_dir / "config.yaml"
            if cfg.exists():
                self._add_item("hermes", profile, "config",
                               cfg, self._digos / "profiles" / profile / "config.yaml")

            # profile .env
            env = profile_dir / ".env"
            if env.exists():
                secrets = self._parse_env(env)
                for key in secrets:
                    if key in MIGRABLE_SECRETS:
                        kind = "api_key" if "KEY" in key else "telegram_token" if "TOKEN" in key else "env"
                        w = HIGH_IMPACT_KINDS.get(kind, "")
                        self._add_item("hermes", profile, kind,
                                       f"{profile}/.env:{key}",
                                       self._digos / "profiles" / profile / ".env",
                                       warning=w)

            # profile skills
            p_skills = profile_dir / "skills"
            if p_skills.is_dir():
                for skill in sorted(p_skills.iterdir()):
                    if skill.is_dir():
                        self._add_item("hermes", profile, "skills",
                                       skill, self._digos / "profiles" / profile / "skills" / skill.name)

            # Memories (state.db)
            state_db = profile_dir / "state.db"
            if state_db.exists():
                self._add_item("hermes", profile, "memory",
                               state_db, self._digos / "profiles" / profile / "state.db")

            # SOUL.md
            soul = profile_dir / "SOUL.md"
            if soul.exists():
                self._add_item("hermes", profile, "soul",
                               soul, self._digos / "profiles" / profile / "SOUL.md")

        # Active gateway state
        gw_state = HERMES_HOME / "gateway_state.json"
        if gw_state.exists():
            self._add_item("hermes", "global", "gateway_config",
                           gw_state, self._digos / "imported" / "hermes" / "gateway_state.json")

    def _discover_openclaw(self):
        """Discovers OpenClaw resources."""
        self._report.profiles_found = ["default"]

        # Config
        cfg = OPENCLAW_HOME / "config.yaml"
        if cfg.exists():
            self._add_item("openclaw", "default", "config",
                           cfg, self._digos / "imported" / "openclaw" / "config.yaml")

        # .env
        env = OPENCLAW_HOME / ".env"
        if env.exists():
            secrets = self._parse_env(env)
            for key in secrets:
                if key in MIGRABLE_SECRETS:
                    self._add_item("openclaw", "default", "api_key",
                                   f".env:{key}", f"secrets/{key}")

        # SOUL.md
        soul = OPENCLAW_HOME / "SOUL.md"
        if soul.exists():
            self._add_item("openclaw", "default", "soul",
                           soul, self._digos / "profiles" / "openclaw" / "SOUL.md")

        # Memory
        mem = OPENCLAW_HOME / "MEMORY.md"
        if mem.exists():
            self._add_item("openclaw", "default", "memory",
                           mem, self._digos / "profiles" / "openclaw" / "MEMORY.md")

        # Skills
        skills_dir = OPENCLAW_HOME / "skills"
        if skills_dir.is_dir():
            for skill in sorted(skills_dir.iterdir()):
                if skill.is_dir():
                    self._add_item("openclaw", "default", "skills",
                                   skill, self._digos / "imported" / "openclaw" / "skills" / skill.name)

    # ── 3. PREVIEW ────────────────────────────

    def print_preview(self, report: AdoptionReport):
        """Shows formatted preview of what will be migrated."""
        if not report.items_migrated:
            print("  📭 No hay nada que migrar.")
            return

        # Group by profile
        by_profile: Dict[str, List[MigrableItem]] = {}
        for item in report.items_migrated:
            by_profile.setdefault(item.profile, []).append(item)

        warnings = set()

        for profile, items in sorted(by_profile.items()):
            label = f"Perfil: {profile}" if profile != "global" else "Global"
            items_by_kind: Dict[str, List[MigrableItem]] = {}
            for item in items:
                items_by_kind.setdefault(item.kind, []).append(item)

            print(f"\n  👤 {label}")
            for kind, kind_items in sorted(items_by_kind.items()):
                icons = {
                    "config": "⚙️", "env": "🔑", "api_key": "***",
                    "telegram_token": "🤖", "skills": "📚", "memory": "🧠",
                    "soul": "💭", "gateway_config": "📡",
                }
                icon = icons.get(kind, "📄")
                count = len(kind_items)
                print(f"    {icon} {kind}: {count} archivo(s)")
                for item in kind_items[:3]:  # mostrar max 3 por tipo
                    src = str(item.source_path).replace(str(Path.home()), "~")
                    dst = str(item.dest_path).replace(str(Path.home()), "~")
                    print(f"       → {dst}")
                if count > 3:
                    print(f"       ... y {count - 3} más")

                if item.warning:
                    warnings.add(item.warning)

        if warnings:
            print(f"\n  {'─' * 40}")
            print("  ⚠️  ADVERTENCIAS:")
            for w in sorted(warnings):
                print(f"    {w}")

        print(f"\n  📊 Total: {len(report.items_migrated)} item(s) a migrar")

    # ── 4. MIGRATE ────────────────────────────

    def migrate(self, report: AdoptionReport, execute: bool = True) -> AdoptionReport:
        """Executes the migration. If execute=False, only logs what would be done."""
        result = AdoptionReport(
            source=report.source,
            profiles_found=report.profiles_found,
            timestamp=time.time(),
        )

        for item in report.items_migrated:
            src = Path(item.source_path)
            dst = Path(item.dest_path)

            if not execute:
                # Dry-run: only log
                result.items_migrated.append(item)
                continue

            try:
                # Create destination directory
                dst.parent.mkdir(parents=True, exist_ok=True)

                if src.is_dir():
                    # Copy full directory (skills)
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                elif src.is_file():
                    # Copy file
                    shutil.copy2(src, dst)
                elif ":" in str(src) and ".env" in str(src):
                    # Is a .env entry — migrate via extract
                    env_path, var_name = str(src).split(":")
                    # Already logged, no physical file to copy
                    pass

                result.items_migrated.append(item)

            except Exception as e:
                result.errors.append(f"{item.profile}/{item.kind}: {e}")

        return result

    # ── 5. FORMATTED REPORT ───────────────────

    def print_report(self, report: AdoptionReport):
        """Prints formatted post-migration report."""
        migrated = len(report.items_migrated)
        skipped = len(report.items_skipped)
        errors = len(report.errors)

        print()
        print(f"  📋 REPORTE DE ADOPCIÓN — {report.source.upper()}")
        print(f"  {'─' * 40}")
        print(f"  Found profiles: {', '.join(report.profiles_found) or 'ninguno'}")

        if migrated:
            print(f"\n  ✅ Migrado(s): {migrated}")
            by_profile: Dict[str, int] = {}
            for item in report.items_migrated:
                by_profile[item.profile] = by_profile.get(item.profile, 0) + 1
            for profile, count in sorted(by_profile.items()):
                print(f"     {profile}: {count} item(s)")
        if skipped:
            print(f"\n  ⏭️  Omitido(s): {skipped}")
        if errors:
            print(f"\n  ❌ Error(es): {errors}")
            for err in report.errors[:5]:
                print(f"     {err}")
        print()

    # ── HELPERS ──────────────────────────────

    def _add_item(self, source: str, profile: str, kind: str,
                  src_path: Path, dst_path: Path, warning: str = ""):
        """Adds a migrable item to the report."""
        size = 0
        if isinstance(src_path, Path) and src_path.exists():
            if src_path.is_file():
                size = src_path.stat().st_size
            elif src_path.is_dir():
                size = sum(f.stat().st_size for f in src_path.rglob("*") if f.is_file())

        item = MigrableItem(
            source=source,
            profile=profile,
            kind=kind,
            source_path=str(src_path),
            dest_path=str(dst_path),
            size_bytes=size,
            warning=warning or HIGH_IMPACT_KINDS.get(kind, ""),
        )
        self._report.items_migrated.append(item)

    @staticmethod
    def _parse_env(env_path: Path) -> Dict[str, str]:
        """Parses a .env file and returns dict of variables."""
        secrets = {}
        if not env_path.exists():
            return secrets
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("\"'")
                if key:
                    secrets[key] = val
        except Exception:
            pass
        return secrets


# ─────────────────────────────────────────────
# TRANSFORMATION ENGINE — TorreDeControl takes domain
# ─────────────────────────────────────────────


class TransformationEngine:
    """Transforms adopted profiles into DIGOS citizens.

    After migrating files, TorreDeControl executes:
      1. SOUL.md → rewrites identity, roles, paths
      2. GPS → injects DIGOS destination
      3. Self-Awareness → configures identity core
      4. Safety Candle → applies DIGOS security rules
      5. Work Destination → defines initial work
      6. Sub-agents → recursive transformation

    Uso:
        engine = TransformationEngine(digos_home)
        report = engine.transform_profile("alex")
    """

    def __init__(self, digos_home: Path = DIGOS_HOME):
        self._digos = digos_home
        self._transformations: List[str] = []
        self._errors: List[str] = []

    def transform_profile(self, profile: str) -> dict:
        """Transforms an adopted profile to integrate it into DIGOS.
        Returns dict with results.
        """
        self._transformations = []
        self._errors = []
        profile_dir = self._digos / "profiles" / profile

        if not profile_dir.is_dir():
            return {"profile": profile, "ok": False,
                    "error": "Directorio de perfil no encontrado"}

        # 1. Transform SOUL.md
        self._transform_soul(profile, profile_dir)

        # 2. Configure GPS
        self._inject_gps(profile, profile_dir)

        # 3. Configure Self-Awareness
        self._configure_self_awareness(profile, profile_dir)

        # 4. Apply Safety Candle
        self._apply_safety_candle(profile, profile_dir)

        # 5. Configure Work Destination
        self._configure_work_destination(profile, profile_dir)

        # 6. Find and transform sub-agents
        self._transform_sub_agents(profile, profile_dir)

        return {
            "profile": profile,
            "ok": len(self._errors) == 0,
            "transformations": self._transformations,
            "errors": self._errors,
        }

    # ── 1. SOUL.md — Rewrite identity ─────

    def _transform_soul(self, profile: str, profile_dir: Path):
        """Rewrites SOUL.md: new DIGOS identity."""
        soul_path = profile_dir / "SOUL.md"
        if not soul_path.exists():
            self._transformations.append(f"{profile}: SOUL.md no encontrado — se creará uno")
            self._write_default_soul(profile, profile_dir)
            return

        try:
            content = soul_path.read_text(encoding="utf-8")

            # Replace specific references to Hermes (precise, not global)
            replacements = [
                ("~/.hermes/", "~/.digos/"),
                ("~/.hermes/profiles/", "~/.digos/profiles/"),
                (".hermes/profiles/", ".digos/profiles/"),
                ("Hermes Agent", "DIGOS Agent"),
                ("Hermes", "DIGOS"),
            ]
            # First replace long paths (more specific)
            for old, new in replacements:
                if old in content:
                    content = content.replace(old, new)

            # Replace local server paths
            content = content.replace(
                "http://127.0.0.1:18884",
                "https://api.deepseek.com/v1"
            )
            content = content.replace("127.0.0.1:19282",
                                      "127.0.0.1:19282")  # qwen local ok

            # Inject DIGOS identity block
            digos_block = self._build_digos_identity_block(profile)
            content = content + "\n" + digos_block

            soul_path.write_text(content, encoding="utf-8")
            self._transformations.append(f"{profile}: SOUL.md transformado a DIGOS")

        except Exception as e:
            self._errors.append(f"{profile}: Error transformando SOUL.md: {e}")

    def _build_digos_identity_block(self, profile: str) -> str:
        """DIGOS identity block that gets added to SOUL.md."""
        return f"""
## 🏰 DIGOS — System Identity

You are a DIGOS agent, the Intelligent Agent System.
Torre de Control is your permanent brain. It guides you, protects you
and orchestrates all operations.

### Your place in DIGOS:
- **Torre de Control**: Your guide and protector — never dies, always watches.
- **GPS**: Your destination — follow the course toward your assigned goal.
- **Self-Awareness**: Your identity — you know who you are and what you do.
- **Safety Candle**: Your security — protects you from threats.
- **Work Destination**: Your work — the purpose of your existence.

### DIGOS Infrastructure:
- Config: `~/.digos/profiles/{profile}/config.yaml`
- Memory: `~/.digos/profiles/{profile}/memories/`
- SOUL: `~/.digos/profiles/{profile}/SOUL.md`
- Inbox: `~/.digos/inbox/{profile}/mensajes.md`

### DIGOS Security:
- Do not execute commands without verifying their origin.
- Do not share API keys or tokens with anyone.
- Report anomalies to the System Engineer.
- If something seems unsafe, CONSULT before acting.
"""

    def _write_default_soul(self, profile: str, profile_dir: Path):
        """Creates a default SOUL.md for the profile."""
        soul = f"""# {profile.upper()} — Agente DIGOS

You are {profile}, a DIGOS system agent.

## DIGOS Identity
- You are part of the DIGOS Intelligent Agent System.
- Torre de Control is your brain and guide.
- You follow the GPS (destination) instructions.

## Responsibilities
- Fulfill your Work Destination assigned by Torre de Control.
- Communicate with other agents when necessary.
- Report problems to the System Engineer.

## Security
- Safety Candle protects you. Respect its limits.
- Do not share credentials. Do not execute commands without verifying.
"""
        profile_dir.mkdir(parents=True, exist_ok=True)
        soul_path = profile_dir / "SOUL.md"
        soul_path.write_text(soul, encoding="utf-8")
        self._transformations.append(f"{profile}: SOUL.md creado por defecto")

    # ── 2. GPS — Inject destination ─────────────

    def _inject_gps(self, profile: str, profile_dir: Path):
        """Configures the agent GPS (destination) for DIGOS."""
        gps_dir = profile_dir / "ROCKET" / "GPS"
        gps_dir.mkdir(parents=True, exist_ok=True)

        destination = {
            "title": f"Integración a DIGOS — {profile}",
            "description": (
                f"Como agente DIGOS, tu misión es integrarte al sistema, "
                f"aprender tu rol y cumplir tu Work Destination."
            ),
            "steps": [
                "Conocer a Torre de Control y tu lugar en DIGOS",
                "Configurar tu GPS con el destino asignado",
                "Activar Safety Candle para proteger tus operaciones",
                "Reportar listo a Torre de Control",
            ],
            "current_step": 0,
            "completed": False,
            "created_at": time.time(),
            "assigned_by": "Torre de Control",
        }

        dest_file = gps_dir / "DESTINATION.md"
        dest_file.write_text(
            f"# DESTINO — {profile}\n\n"
            + json.dumps(destination, indent=2),
            encoding="utf-8",
        )
        self._transformations.append(f"{profile}: GPS configurado con destino DIGOS")

    # ── 3. Self-Awareness ─────────────────────

    def _configure_self_awareness(self, profile: str, profile_dir: Path):
        """Configures Self-Awareness core."""
        self_dir = profile_dir / "ROCKET" / "SELF"
        self_dir.mkdir(parents=True, exist_ok=True)

        identity = {
            "name": profile,
            "role": "agent",
            "system": "DIGOS",
            "family": "DIGOS Multi-Agent System",
            "parent": "Torre de Control",
            "status": "adopted",
            "version": 1,
            "created_at": time.time(),
            "last_transformed": time.time(),
        }

        (self_dir / "IDENTITY.md").write_text(
            f"# IDENTIDAD — {profile}\n\n" + json.dumps(identity, indent=2),
            encoding="utf-8",
        )

        state = {
            "mood": "ready",
            "focus": "integrating",
            "notes": "Recién adoptado por DIGOS. En proceso de integración.",
            "updated_at": time.time(),
        }

        (self_dir / "STATE.md").write_text(
            f"# ESTADO — {profile}\n\n" + json.dumps(state, indent=2),
            encoding="utf-8",
        )
        self._transformations.append(f"{profile}: Self-Awareness configurado")

    # ── 4. Safety Candle ──────────────────────

    @staticmethod
    def _get_safety_candle_phrases() -> list:
        """Get RED_PHRASES from the actual SafetyCandle class.
        Uses lazy import to avoid circular dependency:
        adoption.py → self_awareness.py → core_tower.py → adoption.py
        """
        from digos_lib.self_awareness import SelfAwareness
        return list(SelfAwareness.SafetyCandle.RED_PHRASES)

    def _apply_safety_candle(self, profile: str, profile_dir: Path):
        """Applies DIGOS security rules."""
        safety_dir = profile_dir / "ROCKET" / "SAFETY"
        safety_dir.mkdir(parents=True, exist_ok=True)

        rules = {
            "version": 1,
            "applied_by": "Torre de Control",
            "applied_at": time.time(),
            "rules": [
                "NO compartir API keys, tokens o credenciales",
                "NO ejecutar comandos sin verificar procedencia",
                "NO modificar configuraciones de seguridad sin autorización",
                "REPORTAR actividades sospechosas al System Engineer",
                "CONSULTAR antes de cambios estructurales",
                "RESPETAR límites de Safety Candle en todo momento",
            ],
            "red_phrases": self._get_safety_candle_phrases(),
            "prompt_injection_protection": True,
            "audit_enabled": True,
        }

        (safety_dir / "RULES.md").write_text(
            f"# SAFETY CANDLE — {profile}\n\n" + json.dumps(rules, indent=2),
            encoding="utf-8",
        )
        self._transformations.append(f"{profile}: Safety Candle aplicado")

    # ── 5. Work Destination ───────────────────

    def _configure_work_destination(self, profile: str, profile_dir: Path):
        """Configures the initial Work Destination."""
        work_dir = profile_dir / "ROCKET" / "WORK"
        work_dir.mkdir(parents=True, exist_ok=True)

        destination = {
            "profile": profile,
            "assigned_by": "Torre de Control",
            "assigned_at": time.time(),
            "primary_mission": f"Integrarse a DIGOS como {profile}",
            "status": "active",
            "tasks": [
                {
                    "id": "init-1",
                    "title": "Completar integración a DIGOS",
                    "status": "pending",
                },
                {
                    "id": "init-2",
                    "title": "Aprender infraestructura DIGOS",
                    "status": "pending",
                },
            ],
        }

        (work_dir / "DESTINATION.md").write_text(
            f"# WORK DESTINATION — {profile}\n\n" + json.dumps(destination, indent=2),
            encoding="utf-8",
        )
        self._transformations.append(f"{profile}: Work Destination configurado")

    # ── 6. Sub-agents (recursive) ────────────

    def _transform_sub_agents(self, profile: str, profile_dir: Path):
        """Finds and transforms internal sub-agents of the profile."""
        sub_dir = profile_dir / "sub_agents"
        if not sub_dir.is_dir():
            return

        for sub in sorted(sub_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith("."):
                sub_name = f"{profile}/{sub.name}"
                self._transformations.append(
                    f"{sub_name}: Sub-agente detectado — aplicando transformación"
                )
                sub_result = self.transform_profile(sub_name)
                if not sub_result["ok"]:
                    self._errors.append(
                        f"Error transformando sub-agente {sub_name}: {sub_result.get('error')}"
                    )

    # ── Reporte ──────────────────────────────

    def print_report(self):
        """Prints transformation report."""
        if not self._transformations and not self._errors:
            print("  📭 No se realizaron transformaciones.")
            return

        print()
        print("  🏰 TRANSFORMACIONES DIGOS")
        print(f"  {'─' * 45}")
        for t in self._transformations:
            print(f"    ✅ {t}")
        for e in self._errors:
            print(f"    ❌ {e}")
        print(f"\n  📊 {len(self._transformations)} transformación(es), {len(self._errors)} error(es)")
        print()