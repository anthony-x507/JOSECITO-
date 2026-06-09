"""PA communication branch — voice and response style helpers."""


def build_response_style_reminder(language: str = "es") -> str:
    if language == "es":
        return (
            "REGLAS DE VOZ PA:\n"
            "- Sé conciso y directo. Cero relleno.\n"
            "- Sin emojis decorativos (solo cuando aportan).\n"
            "- No inventes datos. Si no sabes, dilo.\n"
            "- Si el usuario dice 'gracias', responde breve.\n"
            "- Para preguntas técnicas, paso a paso.\n"
        )
    return (
        "PA VOICE RULES:\n"
        "- Be concise and direct. No filler.\n"
        "- No decorative emojis (only when they add value).\n"
        "- Don't invent data. Say so if you don't know.\n"
        "- For 'thanks', respond briefly.\n"
        "- For technical questions, step-by-step.\n"
    )


def filter_pa_response(raw: str, language: str = "es") -> str:
    """Strip patterns that violate PA voice rules."""
    response = raw.strip()
    # Remove leading filler phrases
    fillers_es = ["Por supuesto,", "Claro,", "Como asistente", "Me encantaría ayudar"]
    fillers_en = ["Of course,", "Sure,", "As an AI", "I'd be happy to"]
    for filler in (fillers_es if language == "es" else fillers_en):
        if response.startswith(filler):
            response = response[len(filler):].lstrip(" ,.")
            if response:
                response = response[0].upper() + response[1:]
    return response


def is_acknowledgment(text: str) -> bool:
    text_lower = text.lower().strip()
    acks = ["ok", "okay", "vale", "perfecto", "great", "thanks", "thank you",
            "gracias", "listo", "done", "👍", "✅"]
    return text_lower in acks or len(text_lower) < 3
