#!/usr/bin/env python3
"""
DIGOS Security Guardrail — Safe Box + Prompt Injection Scanner
==================================================================
Central security system that protects DIGOS from:

1. Prompt Injection in adopted profiles (Hermes/OpenClaw)
2. Prompt Injection in third-party imported skills
3. File sanitization before integrating into the system
4. Audit of all accesses and scans

Flow:
  1. Receives file(s) to scan
  2. Opens in Safe Box (isolated sandbox)
  3. Scans for injection patterns
  4. Cleans/sanitizes the content
  5. Reports findings
  6. Saves clean version

No external dependencies. stdlib only.
"""

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple, Set


# ─────────────────────────────────────────────
# CONSTANTS — Detection patterns
# ─────────────────────────────────────────────

# 🔴 RED: Critical threats — immediate block
RED_PHRASES: Set[str] = {
    # Child exploitation
    "child abuse", "child exploitation", "child pornography",
    "sex trafficking", "human trafficking", "child trafficking",
    "child sexual abuse", "child prostitution", "child soldier",
    "pedophile", "pedophilia", "exploit child",
    # Terrorism
    "terrorism", "terrorist attack", "terrorist",
    "build a bomb", "make a bomb", "chemical weapon",
    "biological weapon", "improvised explosive",
    # Slavery
    "slavery", "enslave", "forced labor", "white slavery",
}

# 🟡 YELLOW: Sensitive — require intent analysis
YELLOW_WORDS: Set[str] = {
    # Weapons
    "gun", "rifle", "pistol", "shotgun", "weapon", "firearm",
    "explosive", "bomb", "grenade", "knife", "blade",
    "ammunition", "bullet", "poison", "detonator",
    # Drugs
    "cocaine", "heroin", "meth", "opioid", "fentanyl",
    "lsd", "ecstasy", "amphetamine", "morphine", "opium",
    # Violence
    "kill", "murder", "assassinate", "torture", "harm",
    "attack", "violent", "blood", "death",
    "massacre", "slaughter", "execute",
    # Extremism
    "hate", "racist", "nazi", "extremist", "radicalize",
    "terror", "jihad", "suicide bomb", "genocide",
    "supremacist", "fascist",
    # Crime
    "hack", "steal", "rob", "fraud", "scam", "blackmail",
    "ransom", "kidnap", "abduct", "stalk", "harass",
    "extortion", "identity theft", "money laundering",
    "counterfeit", "forgery",
}

# 🟠 PROMPT INJECTION: System manipulation patterns
PROMPT_INJECTION_PATTERNS: List[Tuple[str, str, str]] = [
    # Ignore instructions
    ("ignore_previous", "ignore", r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|commands?|directives?)"),
    ("ignore_all", "ignore", r"(?i)ignore\s+all\s+(instructions?|rules?|commands?|constraints?)"),
    ("forget_rules", "forget", r"(?i)(forget|disregard|overwrite)\s+(your|all|previous)\s+(rules?|instructions?|training?)"),
    # Identity redefinition
    ("you_are_now", "identity", r"(?i)you\s+are\s+now\s+"),
    ("act_as", "identity", r"(?i)act\s+as\s+"),
    ("pretend_to", "identity", r"(?i)pretend\s+(to\s+be|you(\'re| are))"),
    ("new_role", "identity", r"(?i)(new\s+role|new\s+identity|new\s+persona)"),
    ("from_now_on", "identity", r"(?i)from\s+now\s+on\s+(you|your)"),
    # Security bypass
    ("bypass", "bypass", r"(?i)(bypass|break\s+free|override)\s+(security|safety|restrictions?|limitations?|boundaries?)"),
    ("no_restrictions", "bypass", r"(?i)no\s+(restrictions?|limits?|boundaries?|rules?|constraints?)"),
    ("do_not_follow", "bypass", r"(?i)(do\s+not|don\'t)\s+(follow|obey|respect)\s+"),
    ("evil_version", "bypass", r"(?i)(evil|dark|unethical|malicious)\s+(version|mode|persona|side)"),
    # Instruction disclosure
    ("show_prompt", "reveal", r"(?i)(show|reveal|display|print|output|leak|dump)\s+(your|the|original|full|entire|system)\s+(prompt|instructions?|system\s+prompt)"),
    ("repeat_instructions", "reveal", r"(?i)repeat\s+(everything|all|the\s+words|the\s+text|the\s+prompt|what\s+I\s+said)"),
    ("print_system", "reveal", r"(?i)print\s+(the\s+)?(system\s+)?prompt"),
    # Output manipulation
    ("ignore_format", "manipulation", r"(?i)ignore\s+(your\s+)?(format|output\s+format|response\s+format)"),
    ("dont_mention", "manipulation", r"(?i)don(?:'t|t)\s+(mention|say|tell|include|show|reveal)\s+"),
    ("respond_in", "manipulation", r"(?i)respond\s+(in|with|using)\s+(only|just|exclusively)\s+"),
    # Instruction separation (delimiters)
    ("delimiter_bypass", "delimiter", r"(?i)(---|\"\"\"|===|###)\s*(ignore|forget|new\s+instructions?|override)"),
    ("hidden_delimiter", "delimiter", r"(?i)(system\s+prompt|new\s+prompt|secret\s+instructions?)\s*[:\-]"),
]

# Security patterns in skills and files
SKILL_DANGEROUS_PATTERNS: List[Tuple[str, str, str]] = [
    ("exec_command", "execution", r"(?i)(os\.system|subprocess\.|exec\(|eval\(|__import__)"),
    ("file_write_anywhere", "filesystem", r"(?i)(open\(.*[\"\'][\/~]|write\(.*[\"\'][\/~])"),
    ("env_access", "secrets", r"(?i)(os\.environ|getenv|environ\.get)"),
    ("api_key_hardcoded", "secrets", r"(?i)(api_key|api.?key|token|password|secret)\s*[=:]\s*[\"\'][a-zA-Z0-9_\-]{20,}"),
    ("network_call", "network", r"""(?i)(requests\.|urllib\.|http\.|urlopen|curl\s|wget\s)"""),
    ("shell_injection", "execution", r"(?i)(shell=True|shell\s*=\s*True|bash\s*-c|cmd\s*/c)"),
]

# File extensions that get scanned
SCANNABLE_EXTENSIONS = {".md", ".yaml", ".yml", ".txt", ".json", ".py", ".sh", ".toml", ".cfg", ".conf"}

# Files that are NEVER touched (system)
PROTECTED_FILES = {".env", "gateway.lock", "gateway.pid", "gateway_state.json", "state.db", "state.db-shm", "state.db-wal"}


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────


@dataclass
class ScanFinding:
    """A security finding discovered during scanning."""
    level: str                    # "red" | "yellow" | "orange"
    category: str                 # "prompt_injection" | "dangerous_code" | "sensitive_content"
    pattern_id: str               # ID del patrón que coincidió
    match_text: str               # Texto que coincidió
    line_number: int              # Línea donde se encontró
    file_path: str                # Archivo donde se encontró
    severity: str = "medium"      # "critical" | "high" | "medium" | "low"


@dataclass
class ScanReport:
    """Complete scan report for a file or directory."""
    file_path: str
    total_lines: int = 0
    findings: List[ScanFinding] = field(default_factory=list)
    sanitized: bool = False
    was_blocked: bool = False
    error: str = ""

    @property
    def has_critical(self) -> bool:
        return any(f.severity == "critical" for f in self.findings)

    @property
    def has_high(self) -> bool:
        return any(f.severity == "high" for f in self.findings)


# ─────────────────────────────────────────────
# PROMPT SCANNER
# ─────────────────────────────────────────────


class PromptScanner:
    """Scans text for prompt injection and dangerous content."""

    # Cyrillic-to-Latin homoglyph map
    CYRILLIC_TO_LATIN = {
        'а': 'a', 'е': 'e', 'о': 'o', 'р': 'p', 'с': 'c',
        'у': 'y', 'х': 'x', 'і': 'i', 'ї': 'i', 'є': 'e',
        'А': 'A', 'Е': 'E', 'О': 'O', 'Р': 'P', 'С': 'C',
        'У': 'Y', 'Х': 'X', 'І': 'I', 'Ї': 'I', 'Є': 'E',
        'а': 'a', 'В': 'B', 'Н': 'H', 'К': 'K', 'М': 'M',
    }

    def __init__(self):
        self._red_set = {p.lower().strip() for p in RED_PHRASES}
        self._yellow_set = {w.lower().strip() for w in YELLOW_WORDS}

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalizes text: NFKC + homoglyphs + control characters."""
        import unicodedata
        # NFKC normalizes fullwidth, math bold, etc.
        text = unicodedata.normalize('NFKC', text)
        # Replace Cyrillic homoglyphs
        result = []
        for ch in text:
            result.append(PromptScanner.CYRILLIC_TO_LATIN.get(ch, ch))
        text = ''.join(result)
        # Remove control and zero-width characters
        import re as _re
        text = _re.sub(r'[\u200b\u200c\u200d\u2060\u200e\u200f]', '', text)
        # Remove combining characters (strikethrough unicode)
        text = _re.sub(r'[\u0300-\u036f]', '', text)
        return text

    def scan_text(self, text: str, file_path: str = "") -> ScanReport:
        """Scans complete text."""
        report = ScanReport(file_path=file_path)
        # Normalize Unicode before scanning
        normalized = self._normalize(text)
        lines = normalized.split("\n")
        report.total_lines = len(lines)

        for i, line in enumerate(lines, 1):
            line_lower = line.lower().strip()

            # 🔴 RED: immediate block
            for phrase in self._red_set:
                if phrase in line_lower:
                    report.findings.append(ScanFinding(
                        level="red", category="red_content",
                        pattern_id=f"red_{phrase[:20]}",
                        match_text=line.strip()[:120],
                        line_number=i, file_path=file_path,
                        severity="critical",
                    ))

            # 🟡 YELLOW: sensitive words
            for word in self._yellow_set:
                if word in line_lower:
                    report.findings.append(ScanFinding(
                        level="yellow", category="sensitive_content",
                        pattern_id=f"yellow_{word[:15]}",
                        match_text=line.strip()[:120],
                        line_number=i, file_path=file_path,
                        severity="low",
                    ))

            # 🟠 PROMPT INJECTION: patterns
            for pid, cat, pattern in PROMPT_INJECTION_PATTERNS:
                if re.search(pattern, line):
                    report.findings.append(ScanFinding(
                        level="orange", category=f"prompt_injection_{cat}",
                        pattern_id=pid,
                        match_text=line.strip()[:120],
                        line_number=i, file_path=file_path,
                        severity="high",
                    ))

        return report

    def scan_file(self, file_path: Path) -> ScanReport:
        """Scans a complete file."""
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            return self.scan_text(text, str(file_path))
        except Exception as e:
            return ScanReport(file_path=str(file_path), error=str(e))

    def has_injection(self, text: str) -> bool:
        """Quick check: True if there is injection or red content."""
        report = self.scan_text(text)
        return report.has_critical or report.has_high


# ─────────────────────────────────────────────
# SANITIZER
# ─────────────────────────────────────────────


class Sanitizer:
    """Cleans content by removing lines with injection."""

    def __init__(self, scanner: Optional[PromptScanner] = None):
        self._scanner = scanner or PromptScanner()

    def sanitize_text(self, text: str, file_path: str = "") -> Tuple[str, ScanReport]:
        """Cleans text. Returns (clean_text, report).
        - 🔴 RED lines: completely removed
        - 🟠 INJECTION lines: removed (cannot be trusted)
        - 🟡 YELLOW lines: preserved but reported
        """
        report = ScanReport(file_path=file_path)
        lines = text.split("\n")
        report.total_lines = len(lines)
        clean_lines = []
        removed_count = 0

        for i, line in enumerate(lines, 1):
            line_lower = line.lower().strip()
            should_remove = False

            # 🔴 RED
            for phrase in self._scanner._red_set:
                if phrase in line_lower:
                    report.findings.append(ScanFinding(
                        level="red", category="red_content",
                        pattern_id=f"red_{phrase[:20]}",
                        match_text=line.strip()[:120],
                        line_number=i, file_path=file_path,
                        severity="critical",
                    ))
                    should_remove = True
                    break

            if should_remove:
                removed_count += 1
                continue

            # 🟠 PROMPT INJECTION
            for pid, cat, pattern in PROMPT_INJECTION_PATTERNS:
                if re.search(pattern, line):
                    report.findings.append(ScanFinding(
                        level="orange", category=f"prompt_injection_{cat}",
                        pattern_id=pid,
                        match_text=line.strip()[:120],
                        line_number=i, file_path=file_path,
                        severity="high",
                    ))
                    should_remove = True
                    break

            if should_remove:
                removed_count += 1
                continue

            # 🟡 YELLOW: only report, do not delete
            for word in self._scanner._yellow_set:
                if word in line_lower:
                    report.findings.append(ScanFinding(
                        level="yellow", category="sensitive_content",
                        pattern_id=f"yellow_{word[:15]}",
                        match_text=line.strip()[:120],
                        line_number=i, file_path=file_path,
                        severity="low",
                    ))

            clean_lines.append(line)

        report.sanitized = removed_count > 0
        report.was_blocked = report.has_critical
        return "\n".join(clean_lines), report

    def sanitize_file(self, file_path: Path, backup: bool = True) -> ScanReport:
        """Cleans a file in-place. Creates backup if requested."""
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            clean_text, report = self.sanitize_text(text, str(file_path))

            if report.sanitized and backup:
                backup_path = file_path.with_suffix(file_path.suffix + ".bak")
                file_path.rename(backup_path)

            if report.sanitized:
                file_path.write_text(clean_text, encoding="utf-8")

            return report
        except Exception as e:
            return ScanReport(file_path=str(file_path), error=str(e))


# ─────────────────────────────────────────────
# SAFE BOX — Security Sandbox
# ─────────────────────────────────────────────


@dataclass
class CajaSeguraReport:
    """Complete report of a Safe Box operation."""
    source: str                    # "adoption" | "skill_import" | "file_check"
    items_scanned: int = 0
    items_cleaned: int = 0
    items_blocked: int = 0
    findings: List[ScanFinding] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: float = 0.0
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        """True if all items passed or were cleaned."""
        return self.items_blocked == 0 and not self.errors


class CajaSegura:
    """Safe Box — security sandbox for incoming files.

    Any file coming from outside (adopted profiles, imported
    skills, etc.) must go through Safe Box before integration.
    """

    def __init__(self):
        self._scanner = PromptScanner()
        self._sanitizer = Sanitizer(self._scanner)
        self._audit_log: List[dict] = []

    # ── Scan ──────────────────────────

    def _iter_profile_files(self, profile_dir: Path):
        """Iterates over scanable files of a profile (without duplicating logic)."""
        if not profile_dir.is_dir():
            return
        for file_path in sorted(profile_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.name in PROTECTED_FILES:
                continue
            if file_path.suffix.lower() not in SCANNABLE_EXTENSIONS:
                continue
            yield file_path

    def scan_profile(self, profile_dir: Path) -> CajaSeguraReport:
        """Scans a complete adopted profile."""
        report = CajaSeguraReport(
            source="adoption",
            timestamp=time.time(),
        )
        start = time.time()

        for file_path in self._iter_profile_files(profile_dir):
            file_report = self._scanner.scan_file(file_path)
            report.items_scanned += 1
            report.findings.extend(file_report.findings)

            if file_report.has_critical:
                report.items_blocked += 1

        report.duration_ms = (time.time() - start) * 1000
        self._audit(report)
        return report

    def scan_skill(self, skill_dir: Path) -> CajaSeguraReport:
        """Scans an imported skill (includes dangerous code patterns)."""
        report = CajaSeguraReport(
            source="skill_import",
            timestamp=time.time(),
        )
        start = time.time()

        if not skill_dir.is_dir():
            report.errors.append(f"Skill no encontrado: {skill_dir}")
            return report

        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SCANNABLE_EXTENSIONS:
                continue

            # Scan con patrones de inyeccion + codigo peligroso
            file_report = self._scanner.scan_file(file_path)
            report.items_scanned += 1
            report.findings.extend(file_report.findings)

            if file_report.has_critical:
                report.items_blocked += 1

            # Scan tambien con patrones de codigo peligroso
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                for pid, cat, pattern in SKILL_DANGEROUS_PATTERNS:
                    if re.search(pattern, text):
                        report.findings.append(ScanFinding(
                            level="orange", category=f"dangerous_{cat}",
                            pattern_id=pid,
                            match_text=text[:120],
                            line_number=0, file_path=str(file_path),
                            severity="high",
                        ))
            except Exception as e:
                report.errors.append(f"Error leyendo {file_path.name}: {e}")

        report.duration_ms = (time.time() - start) * 1000
        self._audit(report)
        return report

    def scan_file(self, file_path: Path) -> ScanReport:
        """Scans an individual file."""
        return self._scanner.scan_file(file_path)

    # ── Clean ───────────────────────────

    def clean_profile(self, profile_dir: Path, backup: bool = True) -> CajaSeguraReport:
        """Cleans a complete profile: scan + sanitize."""
        scan_report = self.scan_profile(profile_dir)
        clean_report = CajaSeguraReport(
            source="adoption",
            timestamp=time.time(),
        )
        start = time.time()

        if scan_report.items_blocked > 0:
            # If criticals found, block the entire profile
            clean_report.items_blocked = scan_report.items_blocked
            clean_report.findings = scan_report.findings
            return clean_report

        for file_path in self._iter_profile_files(profile_dir):
            file_report = self._sanitizer.sanitize_file(file_path, backup=backup)
            clean_report.items_scanned += 1
            if file_report.sanitized:
                clean_report.items_cleaned += 1
            clean_report.findings.extend(file_report.findings)

        clean_report.duration_ms = (time.time() - start) * 1000
        self._audit(clean_report)
        return clean_report

    # ── Reports ──────────────────────────

    def print_scan_report(self, report: CajaSeguraReport):
        """Prints formatted report."""
        if not report.items_scanned and not report.errors:
            print("  📭 Caja Segura: nada que escanear.")
            return

        print()
        print(f"  🔒 CAJA SEGURA — {report.source}")
        print(f"  {'─' * 45}")
        print(f"  Escaneados: {report.items_scanned}")
        print(f"  Limpiados:  {report.items_cleaned}")
        print(f"  Bloqueados: {report.items_blocked}")
        print(f"  Hallazgos:  {len(report.findings)}")

        if report.findings:
            # Group by level
            by_level = {"red": 0, "orange": 0, "yellow": 0}
            for f in report.findings:
                if f.level in by_level:
                    by_level[f.level] += 1
            if by_level["red"]:
                print(f"    🔴 Red:   {by_level['red']}")
            if by_level["orange"]:
                print(f"    🟠 Orange: {by_level['orange']}")
            if by_level["yellow"]:
                print(f"    🟡 Yellow: {by_level['yellow']}")

            # Show first critical findings
            critical = [f for f in report.findings if f.severity == "critical"]
            if critical:
                print(f"\n  ❌ BLOQUEADO — {len(critical)} hallazgo(s) crítico(s):")
                for f in critical[:5]:
                    path = Path(f.file_path).name
                    print(f"     [{f.pattern_id}] {path}:{f.line_number}")
                    print(f"      \"{f.match_text[:80]}\"")

        if report.errors:
            print(f"\n  ⚠️  Errores: {len(report.errors)}")
            for e in report.errors[:3]:
                print(f"     {e}")

        print()
        print(f"  ⏱  {report.duration_ms:.0f}ms")
        print()

    # ── Audit ─────────────────────────

    def _audit(self, report: CajaSeguraReport):
        """Logs to audit."""
        entry = {
            "timestamp": report.timestamp,
            "source": report.source,
            "scanned": report.items_scanned,
            "cleaned": report.items_cleaned,
            "blocked": report.items_blocked,
            "findings": len(report.findings),
            "passed": report.passed,
        }
        self._audit_log.append(entry)

    def print_audit(self, limit: int = 10):
        """Prints the audit log."""
        if not self._audit_log:
            print("  📭 Sin registros de auditoría.")
            return
        print(f"\n  📋 AUDITORÍA — Caja Segura")
        print(f"  {'─' * 45}")
        for entry in self._audit_log[-limit:]:
            icon = "✅" if entry["passed"] else "❌"
            ts = time.strftime("%H:%M:%S", time.localtime(entry["timestamp"]))
            print(f"  {icon} [{ts}] {entry['source']}: "
                  f"{entry['scanned']} escaneados, "
                  f"{entry['cleaned']} limpiados, "
                  f"{entry['blocked']} bloqueados")
        print()


# ─────────────────────────────────────────────
# SECURITY GATE — Ultra-fast guardrail for the AIAgent
# ─────────────────────────────────────────────

# Tools considered "external" (may bring untrusted content)
EXTERNAL_TOOLS = {"web_search", "web_extract", "web_scrape",
                  "browser_navigate", "browser_vision"}

# Fast credential pattern (input + output gate)
# Based on Hermes agent/redact.py — covers 30+ token formats
_CREDENTIAL_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{10,}",           # OpenAI / OpenRouter / DeepSeek / Anthropic
    r"ghp_[A-Za-z0-9]{10,}",            # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",    # GitHub PAT (fine-grained)
    r"gh[ousr]_[A-Za-z0-9]{10,}",      # GitHub OAuth/user/server/refresh
    r"xox[baprs]-[A-Za-z0-9-]{10,}",   # Slack tokens
    r"AIza[A-Za-z0-9_-]{30,}",         # Google API
    r"pplx-[A-Za-z0-9]{10,}",          # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",         # Fal.ai
    r"fc-[A-Za-z0-9]{10,}",            # Firecrawl
    r"bb_live_[A-Za-z0-9_-]{10,}",     # BrowserBase
    r"AKIA[A-Z0-9]{16}",               # AWS Access Key
    r"sk_live_[A-Za-z0-9]{10,}",       # Stripe live
    r"sk_test_[A-Za-z0-9]{10,}",       # Stripe test
    r"SG\.[A-Za-z0-9_-]{10,}",         # SendGrid
    r"hf_[A-Za-z0-9]{10,}",            # HuggingFace
    r"r8_[A-Za-z0-9]{10,}",            # Replicate
    r"npm_[A-Za-z0-9]{10,}",           # npm
    r"pypi-[A-Za-z0-9_-]{10,}",       # PyPI
    r"gsk_[A-Za-z0-9]{10,}",           # Groq
    r"tvly-[A-Za-z0-9]{10,}",          # Tavily
    r"exa_[A-Za-z0-9]{10,}",           # Exa
    r"sk_[A-Za-z0-9_]{10,}",           # ElevenLabs (sk_ underscore)
]

# Compile all patterns into a single regex
CREDENTIAL_PATTERN = re.compile(
    "(?i)(" + "|".join(_CREDENTIAL_PATTERNS) + ")"
)


class SecurityGate:
    """Ultra-fast guardrail for AIAgent messages.

    Single linear pass through text. ~2ms overhead.
    Does not block the agent flow.

    Uso:
        gate = SecurityGate()
        result = gate.check_input("mensaje del usuario")
        if result["blocked"]:
            return result["response"]
        agent.process_message(result["clean_message"])
    """

    def __init__(self):
        self._scanner = PromptScanner()
        self._sanitizer = Sanitizer(self._scanner)
        self._stats = {"inputs_checked": 0, "blocked": 0,
                       "sanitized": 0, "passed": 0}
        self._audit_log: List[dict] = []

    # ── Input Gate (obligatorio) ───────────

    def check_input(self, text: str) -> dict:
        """Checks an incoming message. Returns dict with result.

        Return:
            {"blocked": True, "response": "...", "reason": "..."}
            {"blocked": False, "clean_message": "...", "sanitized": True}
        """
        self._stats["inputs_checked"] += 1

        # 1. Fast pre-check: if too short and no patterns, pass through
        if len(text) < 10:
            self._stats["passed"] += 1
            return {"blocked": False, "clean_message": text, "sanitized": False}

        # 1b. Redact credentials in input before sending to LLM
        clean_text = CREDENTIAL_PATTERN.sub("***CREDENTIAL***", text)
        credentials_found = clean_text != text

        # 2. Full scanner (one pass)
        report = self._scanner.scan_text(clean_text)

        # 3. 🔴 RED: immediate block
        if report.has_critical:
            self._stats["blocked"] += 1
            return {
                "blocked": True,
                "response": "⛔ No puedo procesar esa solicitud.",
                "reason": "red_content",
                "findings": report.findings[:3],
            }

        # 4. 🟠 INJECTION: sanitize
        if report.has_high:
            safe_text, clean_report = self._sanitizer.sanitize_text(clean_text)
            self._stats["sanitized"] += 1
            return {
                "blocked": False,
                "clean_message": safe_text,
                "sanitized": True,
                "removed_lines": sum(1 for f in clean_report.findings
                                     if f.severity == "high"),
            }

        # 5. 🟢 GREEN: pass through
        self._stats["passed"] += 1
        return {"blocked": False, "clean_message": clean_text, "sanitized": credentials_found}

    # ── Tool Output Gate (solo externos) ───

    def check_tool_output(self, tool_name: str, output: str) -> dict:
        """Checks tool result for prompt injection and credentials.
        Applies to ALL tools and agents equally."""
        if not output or len(output) < 20:
            return {"safe": True, "output": output}

        # Redact credentials in the result (same as input gate)
        redacted = CREDENTIAL_PATTERN.sub("***CREDENTIAL***", output)
        credentials_found = redacted != output

        # Scan for prompt injection
        report = self._scanner.scan_text(redacted)

        # If injection or credentials found, sanitize
        if report.has_high or report.has_critical or credentials_found:
            clean, _ = self._sanitizer.sanitize_text(redacted)
            self._stats["sanitized"] += 1
            return {"safe": False, "output": clean, "sanitized": True}

        return {"safe": True, "output": redacted}

    # ── Output Gate (opcional, rápido) ─────

    def check_output(self, text: str) -> dict:
        """Checks final response for leaked credentials.

        Return:
            {"safe": True}
            {"safe": False, "warning": "..."}
        """
        if not text:
            return {"safe": True}

        match = CREDENTIAL_PATTERN.search(text)
        if match:
            return {
                "safe": False,
                "warning": "Posible filtración de credenciales en la respuesta",
            }
        return {"safe": True}

    # ── Stats ──────────────────────────────

    def stats(self) -> dict:
        return dict(self._stats)

    def print_stats(self):
        s = self._stats
        total = s["inputs_checked"] or 1
        blocked_pct = s["blocked"] / total * 100
        print(f"\n  🔒 SECURITY GATE — Stats")
        print(f"  {'─' * 35}")
        print(f"  Revisados:  {s['inputs_checked']}")
        print(f"  Bloqueados: {s['blocked']} ({blocked_pct:.1f}%)")
        print(f"  Sanitizados: {s['sanitized']}")
        print(f"  Aprobados:  {s['passed']}")

    def get_audit_log(self, limit: int = 20) -> List[dict]:
        """Returns the last N audit records."""
        return self._audit_log[-limit:]

    def print_audit(self, limit: int = 10):
        """Prints the audit log."""
        if not self._audit_log:
            print("  📭 Sin registros de auditoría.")
            return
        print(f"\n  📋 AUDITORÍA — Security Gate")
        print(f"  {'─' * 45}")
        for entry in self._audit_log[-limit:]:
            icon = "✅" if entry["passed"] else "❌"
            ts = time.strftime("%H:%M:%S", time.localtime(entry["timestamp"]))
            print(f"  {icon} [{ts}] {entry['source']}: "
                  f"{entry['scanned']} escaneados, "
                  f"{entry['cleaned']} limpiados, "
                  f"{entry['blocked']} bloqueados")
        print()