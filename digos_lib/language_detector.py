"""Language detection and enforcement."""
import re
from typing import Dict, Optional, Tuple, FrozenSet


_ES_PHRASES = frozenset([
    "hola", "como estas", "qué tal", "buenos dias", "buenas tardes",
    "gracias", "por favor", "como puedo", "que puedes", "ayudame",
    "quiero que", "necesito", "donde esta", "como se", "por que",
])
_EN_PHRASES = frozenset([
    "hello", "how are you", "good morning", "good afternoon",
    "thank you", "please", "how can", "what can", "help me",
    "i want", "i need", "where is", "how do", "why",
])

_ES_WORDS = frozenset([
    "el", "la", "los", "las", "adios", "adiós", "un", "una", "es", "son", "y", "pero",
    "porque", "como", "cuando", "donde", "que", "si", "no", "muy",
    "mas", "menos", "esto", "esa", "este", "eso", "tambien", "ya",
    "ser", "estar", "tener", "hacer", "ir", "ver", "dar",
])
_EN_WORDS = frozenset([
    "the", "is", "goodbye", "bye", "are", "and", "but", "because", "how", "when",
    "where", "what", "if", "no", "very", "more", "less", "this",
    "that", "also", "be", "have", "do", "go", "see", "give",
])


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _word_pattern(word: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)


def calculate_language_score(text: str, language: str) -> int:
    """Count how many words/phrases in text match the given language."""
    normalized = _normalize(text)
    if language == "es":
        phrases, words = _ES_PHRASES, _ES_WORDS
    elif language == "en":
        phrases, words = _EN_PHRASES, _EN_WORDS
    else:
        return 0
    score = 0
    for phrase in phrases:
        if phrase in normalized:
            score += 3
    for word in words:
        if _word_pattern(word).search(normalized):
            score += 1
    return score


def detect_requested_language(text: str) -> Optional[str]:
    """Detect which language the user is writing in. Returns 'es', 'en', or None."""
    es_score = calculate_language_score(text, "es")
    en_score = calculate_language_score(text, "en")
    if es_score == 0 and en_score == 0:
        return None
    return "es" if es_score > en_score else "en"


def resolve_telegram_chat_language(chat_id: str, text: str) -> Tuple[str, bool]:
    """Resolve which language to use for this chat. Returns (lang, should_ack)."""
    detected = detect_requested_language(text)
    if detected:
        return detected, True
    return "es", False


def build_switch_acknowledgment(new_language: str) -> str:
    if new_language == "es":
        return "🌐 Cambiando a español."
    if new_language == "en":
        return "🌐 Switching to English."
    return f"🌐 {new_language}"


def _response_language_marker_count(text: str, markers: FrozenSet[str]) -> int:
    return sum(1 for m in markers if m in text.lower())


def looks_like_spanish_response(text: str) -> bool:
    es_markers = frozenset([" el ", " la ", " que ", " es ", " no ", " sí ", " qué ", " cómo "])
    return _response_language_marker_count(text, es_markers) >= 3


def looks_like_english_response(text: str) -> bool:
    en_markers = frozenset([" the ", " is ", " that ", " you ", " and ", " with ", " for "])
    return _response_language_marker_count(text, en_markers) >= 3


def enforce_response_language(response: str, language: str) -> str:
    """Last-resort check: if response is in the wrong language, add a notice."""
    if language == "es" and looks_like_english_response(response) and not looks_like_spanish_response(response):
        return response + "\n\n(Nota: respondo mejor en español. Si prefieres inglés, pregúntame.)"
    if language == "en" and looks_like_spanish_response(response) and not looks_like_english_response(response):
        return response + "\n\n(Note: I respond better in English. If you prefer Spanish, just ask.)"
    return response


def clean_telegram_reply_style(reply: str) -> str:
    """Remove markdown that's hard to render in Telegram."""
    reply = re.sub(r"```[a-z]*\n", "", reply)
    reply = re.sub(r"```", "", reply)
    return reply.strip()


def normalize_public_owner_identity(text: str) -> str:
    return text.replace("josecito", "MASTER").replace("JOSECITO", "MASTER")
