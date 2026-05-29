"""
gps.py — Guidance Persistence System
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The GPS is the guide. It knows the DESTINATION (final goal),
the COURSE (planned steps), and tracks DEVIATIONS.

It does NOT speak to the user. It does NOT make decisions.
It provides data to SELF (the agent's soul) so SELF can decide.

Key innovation: deviation analysis.
- "on_track"         → everything aligned, proceed
- "necessary_detour" → deviating but it serves the destination, proceed silently
- "off_track"        → deviation conflicts with destination, SELF must ask user
- "new_direction"    → user changed the destination entirely, SELF must confirm
"""

import json
import os
import re
from typing import Optional, List
import time
from typing import Literal


DeviationResult = Literal["on_track", "necessary_detour", "off_track", "new_direction"]

# ─── WORD ROOTS & SEMANTIC HELPERS ──────────────────────────────

# Common stop words to exclude from matching
_STOP_WORDS: set[str] = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with",
    "by", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "and", "or", "but", "not",
    "no", "nor", "so", "if", "then", "else", "all", "each",
    "every", "some", "any", "none", "both", "neither", "either",
}

# Suffix stripping rules (simplified Porter-style)
_SUFFIX_RULES: list[tuple[str, str]] = [
    ("sses", "ss"),    # processes → process
    ("ied", "y"),      # studied → study
    ("ies", "y"),      # carries → carry
    ("ying", "y"),     # studying → study
    ("ingly", "ing"),  # interesting → interest
    ("ation", "ate"),  # creation → create
    ("ition", "ite"),  # definition → define
    ("ssion", "ss"),   # session → sess
    ("ction", "ct"),   # connection → connect
    ("ment", ""),      # development → develop
    ("able", ""),      # adaptable → adapt
    ("ible", ""),      # accessible → access
    ("ness", ""),      # awareness → aware
    ("less", ""),      # useless → use
    ("fully", ""),     # carefully → care
    ("hood", ""),      # likelihood → likely
    ("ship", ""),      # relationship → relation
    ("like", ""),      # childlike → child
    ("wise", ""),      # likewise → like
    ("ward", ""),      # forward → forw
    ("wards", ""),     # backwards → back
    ("ed", ""),        # worked → work
    ("ing", ""),       # working → work
    ("es", ""),        # boxes → box
    ("s", ""),         # cars → car
    ("ly", ""),        # quickly → quick
    ("er", ""),        # worker → work
    ("est", ""),       # largest → large
    ("al", ""),        # architectural → architectur
    ("ive", ""),       # creative → creat
    ("ous", ""),       # dangerous → danger
    ("ic", ""),        # scientific → scientif
    ("ize", ""),       # realize → real
]

# Word family groups — synonyms and related words
_WORD_FAMILIES: list[set[str]] = [
    # Building / construction
    {"build", "create", "construct", "make", "develop", "architect", "design", "craft", "forge", "shape", "assemble", "establish", "found", "erect", "form"},
    # Coding / development
    {"code", "program", "script", "develop", "implement", "write", "compile", "debug", "refactor", "codify", "software", "app", "application"},
    # System / architecture
    {"system", "architecture", "structure", "framework", "platform", "infrastructure", "engine", "core", "backbone", "foundation"},
    # Testing / validation
    {"test", "check", "verify", "validate", "audit", "review", "inspect", "examine", "confirm", "ensure", "qa", "quality"},
    # Setup / installation
    {"install", "setup", "configure", "init", "initialize", "bootstrap", "deploy", "prepare", "download", "dependencies", "dependency", "requirements", "prerequisites"},
    # Learning / research
    {"learn", "study", "research", "explore", "understand", "comprehend", "read", "examine", "analyze", "investigate", "master"},
    # Agent / AI
    {"agent", "ai", "intelligence", "model", "llm", "reasoning", "inference", "prompt", "context", "memory", "autonomous"},
    # Communication
    {"message", "communicate", "respond", "reply", "answer", "tell", "ask", "explain", "describe", "clarify"},
    # Security
    {"security", "secure", "protect", "safety", "guard", "shield", "encrypt", "auth", "permission", "access"},
    # Data
    {"data", "information", "content", "knowledge", "config", "state", "storage", "file", "database"},
]


def _stem(word: str) -> str:
    """Strip common suffixes to get the word root."""
    # Must be at least 3 chars after suffix removal
    for suffix, replacement in _SUFFIX_RULES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + replacement
    return word


def _word_families(word: str) -> set[str]:
    """Get all words in the same family group."""
    stemmed = _stem(word)
    related = {stemmed, word}
    for family in _WORD_FAMILIES:
        if stemmed in family or word in family:
            related.update(family)
    return related


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text with stemming."""
    words = re.findall(r"[a-záéíóúñü]+", text.lower())
    result: set[str] = set()
    for w in words:
        if w not in _STOP_WORDS and len(w) > 1:
            result.add(_stem(w))
    return result


def _semantic_overlap(a_words: set[str], b_words: set[str]) -> float:
    """
    Calculate semantic overlap ratio between two sets of stemmed keywords.
    Returns 0.0 to 1.0 — how much of set A is semantically related to set B.
    """
    if not a_words or not b_words:
        return 0.0

    # For each word in A, check if it belongs to a family in B
    b_families = {w: _word_families(w) for w in b_words}

    matches = 0
    for a_word in a_words:
        a_family = _word_families(a_word)
        # Check if any B word shares a family with A
        for b_word in b_words:
            if a_word == b_word or a_word in b_families.get(b_word, set()) or b_word in a_family:
                matches += 1
                break

    return matches / len(a_words)


class GPS:
    """The Guidance Persistence System — lives at ~/.digos/agents/{name}/ROCKET/GPS/"""

    FOLDER_NAMES = {
        "DESTINATION": "DESTINATION.md",
        "COURSE": "COURSE.md",
        "DEVIATIONS": "DEVIATIONS.md",
    }

    def __init__(self, rocket_path: str):
        self.gps_path = os.path.join(rocket_path, "GPS")
        os.makedirs(self.gps_path, exist_ok=True)
        self._files = {
            key: os.path.join(self.gps_path, fname)
            for key, fname in self.FOLDER_NAMES.items()
        }
        # ── ACTIVATION GATE ─────────────────────────────────────
        # GPS must NOT be activated until SafetyCandle + SelfAwareness
        # have given consensus that the user's intent is legitimate.
        # Activating GPS without intent verification would guide the
        # agent toward potentially harmful destinations.
        self._activated = False
        self._activation_reason = ""

    def activate(self, reason: str = "") -> None:
        """Activate GPS — called by SelfAwareness after safety+evidence consensus.
        
        Once activated, GPS will analyze deviations and guide the agent.
        Before activation, all analysis methods return safe defaults.
        """
        self._activated = True
        self._activation_reason = reason

    def deactivate(self) -> None:
        """Deactivate GPS — safety gate closed."""
        self._activated = False
        self._activation_reason = ""

    @property
    def is_activated(self) -> bool:
        """Check if GPS has been activated by SelfAwareness."""
        return self._activated

    # ─── DESTINATION ────────────────────────────────────────────

    def set_destination(self, title: str, description: str, steps: list[str]) -> None:
        """Set the final goal. Steps are high-level milestones."""
        dest = {
            "title": title,
            "description": description,
            "steps": steps,
            "current_step": 0,
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        with open(self._files["DESTINATION"], "w") as f:
            json.dump(dest, f, indent=2)

    def get_destination(self) -> Optional[dict]:
        """Get the current destination. Returns None if not set."""
        try:
            with open(self._files["DESTINATION"]) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def advance_step(self) -> bool:
        """Move to the next step. Returns False if already at last step."""
        dest = self.get_destination()
        if not dest:
            return False
        if dest["current_step"] >= len(dest["steps"]) - 1:
            return False
        dest["current_step"] += 1
        dest["updated_at"] = time.time()
        with open(self._files["DESTINATION"], "w") as f:
            json.dump(dest, f, indent=2)
        return True

    def destination_complete(self) -> bool:
        """Check if all destination steps are complete."""
        dest = self.get_destination()
        if not dest or not dest.get("steps"):
            return False
        return dest["current_step"] >= len(dest["steps"]) - 1

    # ─── COURSE ─────────────────────────────────────────────────

    def set_course(self, steps: list[dict]) -> None:
        """
        Set the detailed course. Each step:
          {"id": "step-1", "title": "...", "status": "pending|active|done|blocked"}
        """
        course = {
            "steps": steps,
            "updated_at": time.time(),
        }
        with open(self._files["COURSE"], "w") as f:
            json.dump(course, f, indent=2)

    def get_course(self) -> List[dict]:
        """Get all course steps."""
        try:
            with open(self._files["COURSE"]) as f:
                return json.load(f).get("steps", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def set_step_status(self, step_id: str, status: str) -> bool:
        """Update a single step's status."""
        steps = self.get_course()
        for step in steps:
            if step.get("id") == step_id:
                step["status"] = status
                self.set_course(steps)
                return True
        return False

    # ─── DEVIATIONS ─────────────────────────────────────────────

    def log_deviation(self, description: str, context: str = "") -> None:
        """Log a deviation that occurred during execution."""
        devs = self._load_deviations()
        devs.append({
            "time": time.time(),
            "description": description,
            "context": context,
            "resolved": False,
        })
        with open(self._files["DEVIATIONS"], "w") as f:
            json.dump(devs, f, indent=2)

    def resolve_deviation(self, index: int) -> bool:
        """Mark a deviation as resolved."""
        devs = self._load_deviations()
        if 0 <= index < len(devs):
            devs[index]["resolved"] = True
            with open(self._files["DEVIATIONS"], "w") as f:
                json.dump(devs, f, indent=2)
            return True
        return False

    def _load_deviations(self) -> List[dict]:
        try:
            with open(self._files["DEVIATIONS"]) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def get_active_deviations(self) -> List[dict]:
        """Get all unresolved deviations."""
        return [d for d in self._load_deviations() if not d["resolved"]]

    # ─── THE CORE — Deviation Analysis ─────────────────────────

    def analyze_deviation(self, user_message: str, active_task: str = "") -> DeviationResult:
        """
        Analyze whether a deviation from the user is part of the journey
        or a change of direction.

        This is the KEY innovation over Hermes.

        CRITICAL: GPS must be activated by SelfAwareness before analysis.
        If not activated, returns "off_track" — the agent has no guidance.

        Uses semantic word families and stemming to detect:
          "on_track"         — user is still working on the destination, full alignment
          "necessary_detour" — deviation is a sub-task needed for the destination
          "off_track"        — deviation conflicts with or is irrelevant to destination
          "new_direction"    — user explicitly changed the subject/destination
        """
        # ── ACTIVATION GATE: GPS must be activated by SelfAwareness ──
        if not self._activated:
            return "off_track"

        dest = self.get_destination()

        # No destination set — every message defines a new one
        if not dest:
            return "new_direction"

        dest_title = dest.get("title", "")
        dest_desc = dest.get("description", "")
        dest_text = f"{dest_title} {dest_desc}"

        # Get stemmed keyword sets
        dest_words = _extract_keywords(dest_text)
        msg_words = _extract_keywords(user_message)
        task_words = _extract_keywords(active_task) if active_task else set()

        if not msg_words:
            return "off_track"

        # ─── 1. Check semantic overlap with destination ──────────
        dest_overlap_ratio = _semantic_overlap(msg_words, dest_words)

        # ─── 2. Check semantic overlap with active task ──────────
        task_overlap_ratio = 0.0
        if task_words:
            task_overlap_ratio = _semantic_overlap(msg_words, task_words)

        # ─── 3. Greeting / chitchat detection ────────────────────
        greetings = {"hola", "hello", "hey", "hi", "buenos", "gracias", "ok", "okay", "sí", "si", "yeah", "yes"}
        is_greeting = bool(msg_words & greetings)
        is_very_short = len(msg_words) <= 2

        if is_greeting and is_very_short:
            return "on_track"

        # ─── 4. Decision logic ───────────────────────────────────
        # Thresholds (established empirically):
        #   0.40 = strong semantic match (high confidence)
        #   0.20 = moderate semantic match (medium confidence)
        #   0.15 = weak but meaningful match (low confidence)
        #
        # Strong destination alignment -> on_track
        if dest_overlap_ratio >= 0.4:
            return "on_track"

        # Weak destination + strong task alignment → necessary_detour
        if task_overlap_ratio >= 0.4 and dest_overlap_ratio < 0.4:
            return "necessary_detour"

        # Moderate destination alignment → on_track
        if dest_overlap_ratio >= 0.2:
            return "on_track"

        # Moderate task alignment → necessary_detour (sub-task work)
        if task_overlap_ratio >= 0.2:
            return "necessary_detour"

        # Check for necessary action words (setup, install, configure, etc.)
        # These are often necessary detours even without keyword match
        action_words = _extract_keywords(
            "install setup configure prepare download init bootstrap "
            "setup deploy prepare fix repair restore recover migrate "
            "move copy backup organize clean refactor review check"
        )
        action_overlap = _semantic_overlap(msg_words, action_words)
        if action_overlap >= 0.15 and active_task:
            return "necessary_detour"

        # Check if user is asking about the system or asking for help
        # These are "on_track" — they're about the work
        help_words = _extract_keywords(
            "how what why when where which help question explain "
            "show tell suggest recommend advise propose plan think"
        )
        help_overlap = _semantic_overlap(msg_words, help_words)
        if help_overlap >= 0.3 and active_task:
            return "on_track"

        # No match at all — off track or new direction
        # If message is long (8+ words) and substantive, likely a new goal
        if len(user_message.split()) >= 8:
            return "new_direction"

        return "off_track"

    # ─── CONSENSUS ──────────────────────────────────────────────

    def check_consensus(self, current_work_title: str) -> dict:
        """
        GPS checks if the current work still aligns with the destination
        using semantic word family matching.

        CRITICAL: GPS must be activated by SelfAwareness before consensus check.
        If not activated, returns no-consensus — the agent has no guidance.

        Returns:
          {"consensus": True/False, "reason": "...", "question": "..."}
        """
        # ── ACTIVATION GATE: GPS must be activated by SelfAwareness ──
        if not self._activated:
            return {
                "consensus": False,
                "reason": "GPS not activated — safety gate closed",
                "question": "Safety verification required before guidance can be provided.",
            }

        dest = self.get_destination()
        if not dest:
            return {
                "consensus": False,
                "reason": "No destination set",
                "question": "What is our destination?",
            }

        dest_title = dest.get("title", "")
        dest_desc = dest.get("description", "")
        dest_text = f"{dest_title} {dest_desc}"

        # Use semantic matching
        work_words = _extract_keywords(current_work_title)
        dest_words = _extract_keywords(dest_text)

        if not work_words:
            # No active work yet — consensus is fine, we're starting
            return {"consensus": True, "reason": "No active work yet — starting fresh"}

        overlap_ratio = _semantic_overlap(work_words, dest_words)

        if overlap_ratio >= 0.2:
            return {"consensus": True, "reason": "Aligned"}

        else:
            devs = self.get_active_deviations()
            dev_reason = ""
            if devs:
                dev_reason = f" ({len(devs)} unresolved deviation(s))"

            return {
                "consensus": False,
                "reason": f"Current work '{current_work_title}' doesn't align with destination '{dest_title}'{dev_reason}",
                "question": f"We were working toward '{dest_title}' but now we're working on '{current_work_title}'. Do we continue with the original destination, or has the goal changed?",
            }

    # ═══════════════════════════════════════════════════════════════
    # PROMPT SPLITTING — Long context handling
    # ═══════════════════════════════════════════════════════════════
    #
    # When the GPS context (destination + course + deviations + identity)
    # exceeds token limits, these methods split or compress it into
    # manageable chunks that preserve the most important information.
    #
    # Strategy:
    #   1. Estimate token count (rough: ~4 chars per token)
    #   2. If within budget → return full context
    #   3. If over budget → compress each section proportionally
    #   4. If still over → split into prioritized chunks
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        Estimate token count for a text string.
        Uses ~4 characters per token as a rough heuristic.
        More accurate for English text; slightly overestimates for code.

        Args:
            text: The text to estimate

        Returns:
            Estimated token count (integer)
        """
        if not text:
            return 0
        # Count words (split by whitespace) for better accuracy
        words = len(text.split())
        chars = len(text)
        # Average: ~1 token per 4 chars, or ~1.3 tokens per word
        # Use the more conservative estimate
        return max(words, chars // 4)

    @staticmethod
    def split_text(text: str, max_tokens: int = 2000, overlap_tokens: int = 100) -> list[dict]:
        """
        Split long text into chunks that fit within token limits.
        Each chunk includes overlap with the previous chunk for context preservation.

        Args:
            text: The text to split
            max_tokens: Maximum tokens per chunk (default: 2000)
            overlap_tokens: Number of tokens of overlap between chunks (default: 100)

        Returns:
            List of chunks, each with:
              {"index": int, "text": str, "tokens": int,
               "is_first": bool, "is_last": bool}
        """
        if not text:
            return []

        total_tokens = GPS.estimate_tokens(text)
        if total_tokens <= max_tokens:
            return [{
                "index": 0,
                "text": text,
                "tokens": total_tokens,
                "is_first": True,
                "is_last": True,
            }]

        # Split by paragraphs first (more semantic boundaries)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        # If no paragraph breaks, split by sentences
        if len(paragraphs) <= 1:
            sentences = re.split(r'(?<=[.!?])\s+', text)
            paragraphs = [s.strip() for s in sentences if s.strip()]

        # If still only one chunk, split by words
        if len(paragraphs) <= 1:
            words = text.split()
            approx_tokens_per_word = total_tokens / max(len(words), 1)
            words_per_chunk = max(1, int(max_tokens / approx_tokens_per_word))
            overlap_words = max(1, int(overlap_tokens / approx_tokens_per_word))
            paragraphs = []
            i = 0
            while i < len(words):
                chunk_words = words[i:i + words_per_chunk]
                paragraphs.append(" ".join(chunk_words))
                i += words_per_chunk - overlap_words

        # Build chunks from paragraphs
        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = GPS.estimate_tokens(para)

            # If a single paragraph exceeds max_tokens, split it by sentences
            if para_tokens > max_tokens:
                # Flush current chunk first
                if current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append(chunk_text)
                    current_chunk = []
                    current_tokens = 0

                # Split the large paragraph by sentences
                sentences = re.split(r'(?<=[.!?])\s+', para)
                for sent in sentences:
                    sent_tokens = GPS.estimate_tokens(sent)
                    if current_tokens + sent_tokens > max_tokens and current_chunk:
                        chunk_text = "\n\n".join(current_chunk)
                        chunks.append(chunk_text)
                        # Keep last sentence for overlap
                        overlap_para = current_chunk[-1] if current_chunk else ""
                        current_chunk = [overlap_para] if overlap_para else []
                        current_tokens = GPS.estimate_tokens(overlap_para)
                    current_chunk.append(sent)
                    current_tokens += sent_tokens
            else:
                if current_tokens + para_tokens > max_tokens and current_chunk:
                    chunk_text = "\n\n".join(current_chunk)
                    chunks.append(chunk_text)
                    # Keep last paragraph for overlap
                    overlap_para = current_chunk[-1] if current_chunk else ""
                    current_chunk = [overlap_para] if overlap_para else []
                    current_tokens = GPS.estimate_tokens(overlap_para)
                current_chunk.append(para)
                current_tokens += para_tokens

        # Don't forget the last chunk
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append(chunk_text)

        # Format results
        result = []
        for i, chunk_text in enumerate(chunks):
            result.append({
                "index": i,
                "text": chunk_text,
                "tokens": GPS.estimate_tokens(chunk_text),
                "is_first": i == 0,
                "is_last": i == len(chunks) - 1,
            })

        return result

    def compress_destination(self, max_tokens: int = 500) -> str:
        """
        Get the destination as a compressed string within token budget.
        Prioritizes: title > current_step > description > remaining steps.

        Args:
            max_tokens: Maximum token budget for the destination string

        Returns:
            Compressed destination string
        """
        dest = self.get_destination()
        if not dest:
            return "No destination set."

        title = dest.get("title", "")
        description = dest.get("description", "")
        steps = dest.get("steps", [])
        current_step = dest.get("current_step", 0)

        # Build incrementally, check budget after each addition
        lines = []

        # 1. Title (highest priority)
        title_line = f"Destination: {title}"
        lines.append(title_line)

        # 2. Progress
        if steps:
            progress_line = f"Progress: step {current_step + 1} of {len(steps)}"
            lines.append(progress_line)

        current_text = "\n".join(lines)
        budget_left = max_tokens - self.estimate_tokens(current_text)

        # 3. Description (if budget allows)
        if budget_left > 20 and description:
            desc_line = f"Description: {description}"
            desc_tokens = self.estimate_tokens(desc_line)
            if desc_tokens <= budget_left:
                lines.append(desc_line)
            else:
                # Truncate description to fit
                max_desc_chars = budget_left * 4
                truncated = description[:max_desc_chars]
                if len(truncated) < len(description):
                    truncated = truncated.rsplit(" ", 1)[0] + "..."
                lines.append(f"Description: {truncated}")

        current_text = "\n".join(lines)
        budget_left = max_tokens - self.estimate_tokens(current_text)

        # 4. Steps (lowest priority — show remaining only)
        if budget_left > 20 and steps:
            remaining_steps = steps[current_step:]
            step_lines = []
            for i, step in enumerate(remaining_steps):
                marker = "→" if i == 0 else " "
                step_line = f"  {marker} {step}"
                step_tokens = self.estimate_tokens(step_line)
                if step_tokens <= budget_left:
                    step_lines.append(step_line)
                    budget_left -= step_tokens
                else:
                    break
            if step_lines:
                lines.append("Steps:")
                lines.extend(step_lines)

        return "\n".join(lines)

    def compress_course(self, max_tokens: int = 300) -> str:
        """
        Get the course as a compressed string within token budget.
        Shows only active and pending steps (omits completed ones if needed).

        Args:
            max_tokens: Maximum token budget for the course string

        Returns:
            Compressed course string
        """
        course = self.get_course()
        if not course:
            return ""

        # Prioritize: active > pending > done
        active_steps = [s for s in course if s.get("status") == "active"]
        pending_steps = [s for s in course if s.get("status") in ("pending", "blocked")]
        done_steps = [s for s in course if s.get("status") == "done"]

        lines = []
        current_tokens = 0

        status_symbols = {
            "pending": "○", "active": "◉", "done": "✓", "blocked": "✗"
        }

        # Add active steps first
        for step in active_steps:
            sym = status_symbols.get(step.get("status", "pending"), "○")
            line = f"  {sym} {step.get('title', '?')} [ACTIVE]"
            line_tokens = self.estimate_tokens(line)
            if current_tokens + line_tokens <= max_tokens:
                lines.append(line)
                current_tokens += line_tokens

        # Then pending
        for step in pending_steps:
            sym = status_symbols.get(step.get("status", "pending"), "○")
            line = f"  {sym} {step.get('title', '?')}"
            line_tokens = self.estimate_tokens(line)
            if current_tokens + line_tokens <= max_tokens:
                lines.append(line)
                current_tokens += line_tokens

        # Finally done (summarized)
        if done_steps:
            done_count = len(done_steps)
            done_line = f"  ✓ ... ({done_count} completed step(s))"
            done_tokens = self.estimate_tokens(done_line)
            if current_tokens + done_tokens <= max_tokens:
                lines.append(done_line)
                current_tokens += done_tokens

        if not lines:
            return ""

        return "\n".join(["Course:"] + lines)

    def compress_deviations(self, max_tokens: int = 200) -> str:
        """
        Get active deviations as a compressed string within token budget.
        Shows most recent deviations first.

        Args:
            max_tokens: Maximum token budget for deviations string

        Returns:
            Compressed deviations string
        """
        devs = self.get_active_deviations()
        if not devs:
            return ""

        lines = [f"Active Deviations ({len(devs)}):"]
        current_tokens = self.estimate_tokens(lines[0])

        # Show most recent first
        for i, dev in enumerate(reversed(devs)):
            desc = dev.get("description", "Unknown")
            dev_line = f"  {i + 1}. {desc}"
            dev_tokens = self.estimate_tokens(dev_line)
            if current_tokens + dev_tokens <= max_tokens:
                lines.append(dev_line)
                current_tokens += dev_tokens
            else:
                # Show count of remaining deviations
                remaining = len(devs) - i
                if remaining > 0:
                    lines.append(f"  ... and {remaining} more")
                break

        return "\n".join(lines)

    def get_context_within_budget(self, max_tokens: int = 1500) -> str:
        """
        Get the complete GPS context (destination + course + deviations)
        within a token budget. Allocates budget proportionally:
          - destination: 50%
          - course: 30%
          - deviations: 20%

        Args:
            max_tokens: Total token budget for GPS context

        Returns:
            Compressed GPS context string
        """
        dest_budget = int(max_tokens * 0.50)
        course_budget = int(max_tokens * 0.30)
        dev_budget = int(max_tokens * 0.20)

        parts = []

        destination_str = self.compress_destination(dest_budget)
        if destination_str and destination_str != "No destination set.":
            parts.append(destination_str)

        course_str = self.compress_course(course_budget)
        if course_str:
            parts.append(course_str)

        devs_str = self.compress_deviations(dev_budget)
        if devs_str:
            parts.append(devs_str)

        if not parts:
            return "No GPS context available."

        return "\n\n".join(parts)

    def summarize_for_prompt(self, max_tokens: int = 1000) -> str:
        """
        Get a quick summary of GPS state suitable for inclusion in an
        LLM system prompt. Prioritizes the most actionable information.

        Format:
          [DESTINATION] Goal: ...
          [COURSE] Step X of Y: ...
          [DEVIATIONS] N active

        Args:
            max_tokens: Maximum token budget

        Returns:
            One-line summary per section
        """
        dest = self.get_destination()
        devs = self.get_active_deviations()

        lines = []
        current_tokens = 0

        # Destination summary (highest priority)
        if dest:
            title = dest.get("title", "?")
            steps = dest.get("steps", [])
            current = dest.get("current_step", 0)
            step_info = f"[step {current + 1}/{len(steps)}]" if steps else ""
            dest_line = f"[DESTINATION] {title} {step_info}".strip()
            dest_tokens = self.estimate_tokens(dest_line)
            if current_tokens + dest_tokens <= max_tokens:
                lines.append(dest_line)
                current_tokens += dest_tokens

        # Course summary
        course = self.get_course()
        if course:
            active = [s for s in course if s.get("status") == "active"]
            pending = [s for s in course if s.get("status") in ("pending", "blocked")]
            done = [s for s in course if s.get("status") == "done"]
            summary_parts = []
            if active:
                summary_parts.append(f"{len(active)} active")
            if pending:
                summary_parts.append(f"{len(pending)} pending")
            if done:
                summary_parts.append(f"{len(done)} done")
            if summary_parts:
                course_line = f"[COURSE] {', '.join(summary_parts)}"
                course_tokens = self.estimate_tokens(course_line)
                if current_tokens + course_tokens <= max_tokens:
                    lines.append(course_line)
                    current_tokens += course_tokens

        # Deviations summary
        if devs:
            unresolved = sum(1 for d in devs if not d.get("resolved", True))
            dev_line = f"[DEVIATIONS] {unresolved} active deviation(s)"
            dev_tokens = self.estimate_tokens(dev_line)
            if current_tokens + dev_tokens <= max_tokens:
                lines.append(dev_line)
                current_tokens += dev_tokens

        if not lines:
            return "[GPS] No destination set — awaiting first goal."

        return " | ".join(lines)
