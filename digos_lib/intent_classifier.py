"""
DIGOS Intent Classifier — Hybrid Architecture
=============================================

Translates natural human language into operational intent.
Bridges the gap between "Quiero que me escuches" and
"SKILL_REQUEST: stt_audio_input → Factory".

Architecture:
  Camino A (regex): Structured commands (api_key, credentials, agent creation)
  Camino B (LLM):   Natural language → intent family → capability gap → Factory

Principle: "No decir 'no puedo', decir 'eso requiere una mejora; puedo prepararla.'"
"""

import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError


# ── Intent Families ──────────────────────────────────────────────────

@dataclass
class SubIntent:
    """A specific sub-intention within a family."""
    id: str                              # e.g., "VOICE_INPUT_CAPABILITY_REQUEST"
    description: str                     # human-readable description WITH example phrases
    capability: str                      # required capability (e.g., "stt_input")
    gap_response: str                    # what to tell the user when capability is missing


@dataclass
class IntentFamily:
    """A family of related intents."""
    id: str                              # e.g., "VOICE"
    description: str                     # human-readable description
    sub_intents: List[SubIntent] = field(default_factory=list)


@dataclass
class IntentClassification:
    """Result of intent classification."""
    matched: bool = False
    family: str = ""
    family_description: str = ""
    sub_intent_id: str = ""
    sub_intent_description: str = ""
    capability: str = ""
    has_gap: bool = True                 # True if the capability is NOT available
    gap_response: str = ""               # Response to give when gap exists
    factory_action: str = ""             # "SKILL_REQUEST" or "" if no factory action needed
    confidence: float = 0.0
    raw_response: str = ""               # For debugging


# ── Intent Families Definition ───────────────────────────────────────

INTENT_FAMILIES: Dict[str, IntentFamily] = {
    "VOICE": IntentFamily(
        id="VOICE",
        description="Audio/voice communication — STT, TTS, voice messages, speech recognition",
        sub_intents=[
            SubIntent(
                id="VOICE_INPUT_NOW",
                description=(
                    "User wants to send audio/voice RIGHT NOW in this conversation. "
                    "They have a voice message, audio clip, recording, or want to dictate. "
                    "Examples: 'te mando un audio', 'escucha esto', 'tengo un mensaje de voz', "
                    "'te voy a dictar algo', 'aquí te va un voice note', 'te comparto una grabación', "
                    "'grabé esto para ti', 'presta atención a este audio', 'oye lo que me dijo', "
                    "'quiero dictarte algo', '¿puedes escuchar mi voz?', 'te paso un clip de voz', "
                    "'mira este audio que tengo', 'te envío nota de voz', 'escúchame un momento', "
                    "'aló, ¿me escuchas?', 'tengo un audio importante', 'hay un voice message que necesitas oír', "
                    "'te mando una nota de voz', 'dictado rápido', 'toma, escucha esto', "
                    "'te voy a hablar al micrófono', 'prepárate para un audio'"
                ),
                capability="stt_audio_input",
                gap_response=(
                    "🎤 Por ahora puedo leer y responder solo texto. "
                    "Todavía no proceso mensajes de voz ni audio."
                ),
            ),
            SubIntent(
                id="VOICE_INPUT_CAPABILITY_REQUEST",
                description=(
                    "User wants the system to GAIN the ability to receive/listen/process audio. "
                    "They want microphone capability, speech recognition, STT. "
                    "Examples: 'quiero que me escuches', 'necesito que me oigas', "
                    "'haz que puedas oír', 'ponme capacidad de voz', 'activa el micrófono', "
                    "'quiero poder hablarte', 'instálame entrada de voz', 'agrega audio input', "
                    "'necesito que proceses audios', '¿puedes recibir mensajes de voz?', "
                    "'quiero hablarte en vez de escribir', 'activa speech-to-text', "
                    "'quiero que entiendas lo que digo', 'ponle oídos al sistema', "
                    "'necesito funcionalidad de voz', 'quiero dictar en vez de teclear', "
                    "'¿podrías recibir audios?', 'necesito que tengas oídos', "
                    "'ponle entrada de audio', 'agrega capacidad de escuchar', "
                    '"instala STT", "agrega whisper", "necesito speech recognition", '
                    "'quiero que el sistema oiga', 'necesito entrada de micrófono', "
                    "'activa la funcionalidad de audio', 'ponme detección de voz', "
                    "'quiero poder grabarte mensajes de voz', 'activa recepción de audio'"
                ),
                capability="stt_audio_input",
                gap_response=(
                    "🎤 Para poder escuchar audios necesito agregar capacidad de "
                    "entrada de voz (STT). Puedo preparar esa solicitud para revisión "
                    "y enviarla a la Factoría. ¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="VOICE_OUTPUT_REQUEST",
                description=(
                    "User wants the system to RESPOND with voice/audio (TTS). "
                    "They want spoken answers, audio responses, text read aloud. "
                    "Examples: 'respóndeme hablando', 'contéstame con voz', "
                    "'háblame', 'dímelo en voz alta', 'quiero oír tu respuesta', "
                    "'léeme eso en voz alta', 'activa la salida de voz', "
                    "'necesito que me leas las respuestas', 'responde con un audio', "
                    "'que me hables cuando respondas', 'quiero escuchar tu voz', "
                    "'¿puedes hablarme?', 'dame la respuesta hablada', "
                    "'quiero salida de audio', 'convierte la respuesta a voz', "
                    "'necesito text-to-speech', 'activa la voz para las respuestas', "
                    "'háblame como Siri', 'quiero que me leas la respuesta', "
                    "'¿puedes leérmelo?', 'léelo en voz alta porfa', "
                    "'dilo con tu voz', 'respóndeme como si hablaras', "
                    "'quiero que me digas las cosas hablando', 'pon TTS', "
                    "'necesito audio output', 'respond with voice'"
                ),
                capability="tts_audio_output",
                gap_response=(
                    "🔊 Para responder con voz necesito capacidad de salida de audio (TTS). "
                    "Puedo preparar esa solicitud para revisión y enviarla a la Factoría. "
                    "¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="VOICE_CONVERSATION_REQUEST",
                description=(
                    "User wants FULL bidirectional voice conversation (STT + TTS together). "
                    "They want to speak AND hear responses, like a phone call or voice assistant. "
                    "Examples: 'podemos tener una llamada de voz', 'hablemos por voz', "
                    "'quiero una conversación hablada', '¿podemos hablar como con Siri?', "
                    "'activa conversación por voz', 'quiero hablarte y que me hables', "
                    "'¿podemos tener una llamada?', 'necesito conversación bidireccional', "
                    "'quiero comunicación de voz completa', 'activa voz bidireccional', "
                    "'ponme el sistema de llamada por voz', '¿puedo hablarte al micrófono y que me respondas?', "
                    "'quiero voz en ambos sentidos', 'necesito conversación natural por voz', "
                    "'activa el duplex de audio', 'quiero hablar y escuchar respuestas', "
                    "'pon el modo conversación por voz', 'full-duplex de audio', "
                    "'quiero una llamada de audio contigo', '¿podemos tener una plática por audio?', "
                    "'necesito que hablemos en tiempo real por voz', 'activa hands-free con voz'"
                ),
                capability="voice_full_duplex",
                gap_response=(
                    "🎤🔊 Para una conversación por voz completa necesito tanto entrada "
                    "como salida de audio (STT + TTS). Puedo preparar ambas solicitudes "
                    "para revisión en la Factoría. ¿Quieres que las prepare?"
                ),
            ),
            SubIntent(
                id="VOICE_HELP_OR_SETUP_REQUEST",
                description=(
                    "User asks how to activate, configure, or set up voice features. "
                    "They want instructions, guidance, or tutorials about voice capabilities. "
                    "Examples: 'cómo activo el audio', 'cómo uso la voz', "
                    "'¿se puede usar voz aquí?', '¿tienes capacidad de audio?', "
                    "'cómo configuro entrada de voz', 'dónde activo el micrófono', "
                    "'¿puedes procesar audio?', '¿cómo hago para hablarte?', "
                    "'necesito ayuda con la voz', 'cómo enciendo el speech-to-text', "
                    "'¿soportas mensajes de voz?', 'guía para activar audio', "
                    "'cómo pongo a funcionar la voz', 'explica cómo usar funciones de voz', "
                    "'tutorial de voz', '¿qué necesito para hablarte?', "
                    "'¿cómo configuro el audio?', '¿hay manera de usar voz aquí?', "
                    "'enséñame a usar la función de voz', '¿tienes soporte para audio?', "
                    "'¿se pueden mandar notas de voz?', 'doc de activación de voz'"
                ),
                capability="voice_full_duplex",
                gap_response=(
                    "🎤 Las funciones de voz no están disponibles para activar directamente "
                    "todavía. Pero puedo preparar la solicitud para agregarlas al sistema. "
                    "¿Quieres que prepare la solicitud para la Factoría?"
                ),
            ),
            SubIntent(
                id="VOICE_FRUSTRATION",
                description=(
                    "User is frustrated, complaining, or expressing disappointment "
                    "about the lack of voice/audio support. Negative/emotional tone. "
                    "Examples: 'por qué no puedes oírme', 'no me escuchas', "
                    "'qué mal que no entiendas audio', 'no sirve que no tengas voz', "
                    "'deberías poder escuchar audios', 'es frustrante no poder hablarte', "
                    "'qué limitado sin entrada de audio', 'necesito que oigas y no puedes', "
                    "'no te sirve de nada sin voz', 'no me gusta escribir, quiero hablar', "
                    "'si no oyes, no sirves bien', 'de verdad que no puedes escuchar nada?', "
                    "'qué inútil sin capacidad de audio', 'estoy harto de escribir siempre', "
                    "'por dios, aprende a oír', 'qué sistema tan limitado sin voz', "
                    "'otro sistema que no soporta audio', 'qué decepción que no oigas', "
                    "'no entiendes nada de lo que te digo', 'para qué sirves si no escuchas', "
                    "'esto no funciona sin entrada de voz', 'necesito hablar y no se puede'"
                ),
                capability="stt_audio_input",
                gap_response=(
                    "🎤 Entiendo la frustración. Por ahora solo puedo trabajar con texto, "
                    "pero puedo preparar la solicitud para agregar entrada de voz. "
                    "¿Quieres que la envíe a revisión?"
                ),
            ),
        ],
    ),
    "WEB": IntentFamily(
        id="WEB",
        description="Web browsing, search, internet capabilities, online research",
        sub_intents=[
            SubIntent(
                id="WEB_SEARCH_REQUEST",
                description=(
                    "User wants to SEARCH the internet for information, news, data. "
                    "They want Google/Bing/DuckDuckGo-style search results. "
                    "Examples: 'busca en internet', 'búscalo en la web', "
                    "'googlea esto', 'búscame información sobre', "
                    "'investiga en internet', 'consulta en la web', "
                    "'haz una búsqueda de', 'averigua en línea', "
                    "'sácame datos de internet', 'encuentra en la red', "
                    "'mira en Google', 'dime qué dice internet sobre', "
                    "'explora en la web', 'indaga en línea', "
                    "'¿qué dice internet acerca de?', 'búscalo en la red', "
                    "'tráeme resultados de búsqueda', 'mira qué hay en línea sobre', "
                    "'arráncame una búsqueda de', 'consulta en Google', "
                    "'dame información actualizada de', 'bucea en internet para encontrar', "
                    "'sondea en la web', 'explora en línea y dime', "
                    "'¿puedes buscar algo en internet?', 'investígame esto', "
                    "'búscame referencias sobre', 'haz una pesquisa en internet', "
                    "'¿qué encuentras sobre?', 'sácame información actual de'"
                ),
                capability="web_search",
                gap_response=(
                    "🔍 Para buscar en internet necesito capacidad de búsqueda web. "
                    "Puedo preparar esa solicitud para revisión en la Factoría. "
                    "¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="WEB_BROWSING_REQUEST",
                description=(
                    "User wants to BROWSE/NAVIGATE to a specific website, URL, or web page. "
                    "They want the system to open a browser and visit a site. "
                    "Examples: 'abre esta página', 've a este sitio', "
                    "'navega a', 'entra a esta URL', "
                    "'llévame a la página', 'muéstrame el sitio', "
                    "'accede a esta dirección web', 'abre el navegador y ve a', "
                    "'cárgame esta página web', 'visita este sitio web', "
                    "'dirígete a esta web', 'conéctate a este sitio', "
                    "'ábreme esta página en el navegador', 'navega por esta dirección', "
                    "'explora este sitio web', 'entra a esa página', "
                    "'lleva el navegador a', 'abre un browser y pon esta URL', "
                    "'carga esta dirección', 'despliega esta página web', "
                    "'pon esta URL en el navegador', 'accede al sitio', "
                    "'quiero que veas esta página', 'navega a la dirección'"
                ),
                capability="web_browsing",
                gap_response=(
                    "🌐 Para navegar por internet necesito capacidad de navegación web. "
                    "Puedo preparar esa solicitud para revisión en la Factoría. "
                    "¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="WEB_DATA_REQUEST",
                description=(
                    "User wants to FETCH/EXTRACT/SCRAPE data from a specific URL, API, "
                    "or web page. They want structured data, JSON, or content extraction. "
                    "Examples: 'descarga los datos de esta URL', 'obtén información de', "
                    "'lee el contenido de esta URL', 'extráeme los datos de', "
                    "'sácame la información de esta web', 'parsea esta página y dime', "
                    "'obtén el JSON de esta API', 'consume este endpoint', "
                    "'tráeme lo que hay en', 'haz un GET a esta URL', "
                    "'recoge los datos de esta dirección', 'accede a esta API y dime', "
                    "'scrapea esta página', 'extráeme los datos estructurados de', "
                    "'obten el contenido de esta URL', 'lee esta página web y resúmela', "
                    "'baja la información de este sitio', 'fetchea esta URL', "
                    "'tráeme el contenido de', 'pásame los datos de esta página', "
                    "'dame el JSON de', 'obtén los datos de esta API'"
                ),
                capability="web_fetch",
                gap_response=(
                    "📡 Para obtener datos de internet necesito capacidad de fetching web. "
                    "Puedo preparar esa solicitud para revisión en la Factoría. "
                    "¿Quieres que la prepare?"
                ),
            ),
        ],
    ),
    "VISION": IntentFamily(
        id="VISION",
        description="Image/visual analysis — image recognition, screenshots, document scanning, photo analysis",
        sub_intents=[
            SubIntent(
                id="VISION_IMAGE_ANALYSIS",
                description=(
                    "User wants to ANALYZE, describe, or understand an image, photo, "
                    "picture, screenshot, or visual content. They want to know what's in it. "
                    "Examples: 'analiza esta imagen', 'describe esta foto', "
                    "'¿qué ves en esta imagen?', 'explícame qué hay en esta foto', "
                    "'mira esta imagen y dime', 'reconoce esta fotografía', "
                    "'examina esta imagen', 'dime qué contiene esta foto', "
                    "'¿qué hay en esta imagen?', 'interpreta esta fotografía', "
                    "'describe lo que ves en esta foto', 'analiza esta captura de pantalla', "
                    "'¿qué muestra esta imagen?', 'dame detalles de esta foto', "
                    "'mira lo que te envío y descríbelo', '¿puedes ver esta imagen?', "
                    "'identifica los elementos de esta foto', '¿qué objetos hay en esta imagen?', "
                    '"analiza este screenshot", "examina esta fotografía", '
                    "'¿qué dice esta imagen?', 'háblame de esta foto'"
                ),
                capability="image_analysis",
                gap_response=(
                    "🖼️ Por ahora no tengo capacidad de análisis de imágenes. "
                    "Puedo preparar una solicitud para agregar visión al sistema "
                    "a través de la Factoría. ¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="VISION_DOCUMENT_SCAN",
                description=(
                    "User wants to SCAN, OCR, or extract text from a document, "
                    "receipt, invoice, form, or any text-containing image. "
                    "Examples: 'escanea este documento', 'extrae el texto de esta imagen', "
                    "'haz OCR a esta foto', 'lee lo que dice este documento escaneado', "
                    "'transcribe el texto de esta imagen', 'sácame el texto de este recibo', "
                    "'digitaliza este documento', 'reconoce el texto en esta imagen', "
                    "'pásame el texto de esta factura', 'extrae la información de este formulario', "
                    "'lee este documento en la foto', 'sácame los datos de este PDF escaneado', "
                    "'convierte esta imagen a texto', 'reconoce caracteres en esta imagen', "
                    "'extrae el contenido de este documento escaneado', "
                    "'¿qué dice este papel en la foto?', 'escanea este recibo y extrae los datos', "
                    "'pásame el texto de esta captura', 'digitaliza esto para mí', "
                    "'dame el texto de este documento en imagen'"
                ),
                capability="image_analysis",
                gap_response=(
                    "📄 Por ahora no puedo escanear documentos ni extraer texto de imágenes. "
                    "Puedo preparar una solicitud para agregar OCR/visión al sistema "
                    "a través de la Factoría. ¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="VISION_CAPABILITY_REQUEST",
                description=(
                    "User wants the system to GAIN visual/image/vision capabilities. "
                    "They want computer vision, image recognition, object detection. "
                    "Examples: 'agrega capacidad de visión', 'quiero que puedas ver imágenes', "
                    "'necesito que veas fotos', 'activa visión por computadora', "
                    "'ponle ojos al sistema', 'necesito análisis de imágenes', "
                    "'¿puedes aprender a ver imágenes?', 'quiero image recognition', "
                    "'agrega computer vision', 'necesito capacidad de image analysis', "
                    "'instala procesamiento de imágenes', 'necesito que analices fotos', "
                    "'¿puedes procesar imágenes?', 'activa la visión artificial', "
                    '"necesito que entiendas imágenes", "ponle capacidad visual", '
                    "'agrégame la función de ver imágenes', 'quiero que detectes objetos en fotos', "
                    "'necesito OCR y visión', 'implementa procesamiento visual', "
                    "'capacidad de entender contenido visual'"
                ),
                capability="image_analysis",
                gap_response=(
                    "🖼️ Esa es una capacidad visual que todavía no tengo. "
                    "Puedo preparar una solicitud para agregar análisis de imágenes "
                    "al sistema a través de la Factoría. ¿Quieres que la prepare?"
                ),
            ),
        ],
    ),
    "NEW_TOOL": IntentFamily(
        id="NEW_TOOL",
        description="New tool, feature, or capability request — something the system doesn't have yet",
        sub_intents=[
            SubIntent(
                id="GENERIC_CAPABILITY_REQUEST",
                description=(
                    "User requests a capability the system doesn't have yet. "
                    "Generic request for a new feature or ability. "
                    "Examples: 'puedes hacer X?', 'necesito que hagas Y', "
                    "'¿tienes capacidad para?', 'me gustaría que pudieras', "
                    "'¿puedes integrarte con?', 'necesito una función que', "
                    "'agrega la capacidad de', 'implementa la funcionalidad de', "
                    "'soporte para', 'integración con'"
                ),
                capability="custom_tool",
                gap_response=(
                    "🛠️ Esa es una capacidad que todavía no tengo. "
                    "Puedo preparar una solicitud para agregarla al sistema "
                    "a través de la Factoría. ¿Quieres que la prepare?"
                ),
            ),
            SubIntent(
                id="SPECIFIC_TOOL_REQUEST",
                description=(
                    "User asks for a SPECIFIC named tool or integration. "
                    "They name a particular technology, platform, or tool. "
                    "Examples: 'necesito una herramienta para', 'agrega integración con', "
                    "'conecta con', 'quiero que uses', 'instala el plugin de', "
                    "'activa el módulo de', 'pon el tool de', 'implementa un adaptador para', "
                    "'necesito un conector con', 'crea una herramienta que'"
                ),
                capability="custom_tool",
                gap_response=(
                    "🛠️ Esa herramienta no está disponible todavía. "
                    "Puedo preparar la solicitud para desarrollarla en la Factoría. "
                    "¿Quieres que la prepare?"
                ),
            ),
        ],
    ),
    "CONVERSATION": IntentFamily(
        id="CONVERSATION",
        description="Normal conversation — no capability gap, no factory action needed",
        sub_intents=[
            SubIntent(
                id="GENERAL_CHAT",
                description="Normal conversation, question, or request within existing capabilities",
                capability="",
                gap_response="",
            ),
        ],
    ),
}

# Flattened lookup: sub_intent_id → SubIntent
_ALL_SUB_INTENTS: Dict[str, SubIntent] = {}
for family in INTENT_FAMILIES.values():
    for si in family.sub_intents:
        _ALL_SUB_INTENTS[si.id] = si


def get_family(family_id: str) -> Optional[IntentFamily]:
    """Get an intent family by ID."""
    return INTENT_FAMILIES.get(family_id)


def get_sub_intent(sub_intent_id: str) -> Optional[SubIntent]:
    """Get a sub-intent by ID."""
    return _ALL_SUB_INTENTS.get(sub_intent_id)


# ── Classification Prompt ────────────────────────────────────────────
#
# KEY INSIGHT: La calidad de la clasificación depende DIRECTAMENTE de
# cuántos ejemplos del lenguaje humano real le damos al LLM.
# Cada sub_intent tiene 20+ ejemplos para capturar TODAS las variaciones.
# Esto es lo que aprendí de mí mismo como LLM — miles de formas de
# decir lo mismo en lenguaje natural.

CLASSIFICATION_SYSTEM_PROMPT = """Eres un clasificador de intención para DIGOS. Tu única tarea es clasificar el mensaje del usuario en una familia de intención y una subintención.

Responde ÚNICAMENTE con un objeto JSON. Nada más. Sin markdown, sin explicaciones.

El JSON debe tener exactamente estos campos:
{
  "family": "VOICE" | "WEB" | "VISION" | "NEW_TOOL" | "CONVERSATION",
  "sub_intent": "VOICE_INPUT_NOW" | "VOICE_INPUT_CAPABILITY_REQUEST" | "VOICE_OUTPUT_REQUEST" | "VOICE_CONVERSATION_REQUEST" | "VOICE_HELP_OR_SETUP_REQUEST" | "VOICE_FRUSTRATION" | "WEB_SEARCH_REQUEST" | "WEB_BROWSING_REQUEST" | "WEB_DATA_REQUEST" | "VISION_IMAGE_ANALYSIS" | "VISION_DOCUMENT_SCAN" | "VISION_CAPABILITY_REQUEST" | "GENERIC_CAPABILITY_REQUEST" | "SPECIFIC_TOOL_REQUEST" | "GENERAL_CHAT",
  "confidence": 0.0 a 1.0
}

═══ FAMILIA VOICE — Audio, voz, habla, sonido ═══

VOICE_INPUT_NOW — El usuario QUIERE ENVIAR UN AUDIO AHORA:
  "te mando un audio", "escucha esto", "tengo un mensaje de voz", "te voy a dictar algo",
  "aquí te va un voice note", "te comparto una grabación", "grabé esto para ti",
  "presta atención a este audio", "oye lo que me dijo", "quiero dictarte algo",
  "¿puedes escuchar mi voz?", "te paso un clip de voz", "mira este audio que tengo",
  "te envío nota de voz", "escúchame un momento", "aló, ¿me escuchas?",
  "tengo un audio importante", "hay un voice message que necesitas oír",
  "te mando una nota de voz", "dictado rápido", "toma, escucha esto",
  "te voy a hablar al micrófono", "prepárate para un audio", "te dicto algo",
  "mira lo que me grabaron", "escucha este mensaje que me mandaron",
  "te paso una nota de audio", "tengo algo que decirte por audio"

VOICE_INPUT_CAPABILITY_REQUEST — El usuario QUIERE QUE EL SISTEMA PUEDA OÍR/RECIBIR AUDIO:
  "quiero que me escuches", "necesito que me oigas", "haz que puedas oír",
  "ponme capacidad de voz", "activa el micrófono", "quiero poder hablarte",
  "instálame entrada de voz", "agrega audio input", "necesito que proceses audios",
  "¿puedes recibir mensajes de voz?", "quiero hablarte en vez de escribir",
  "activa speech-to-text", "quiero que entiendas lo que digo", "ponle oídos al sistema",
  "necesito funcionalidad de voz", "quiero dictar en vez de teclear",
  "¿podrías recibir audios?", "necesito que tengas oídos", "ponle entrada de audio",
  "agrega capacidad de escuchar", "instala STT", "agrega whisper",
  "necesito speech recognition", "quiero que el sistema oiga", "necesito entrada de micrófono",
  "activa la funcionalidad de audio", "ponme detección de voz",
  "quiero poder grabarte mensajes de voz", "activa recepción de audio",
  "necesito que el sistema entienda voz", "quiero dictar en lugar de escribir"

VOICE_OUTPUT_REQUEST — El usuario QUIERE QUE EL SISTEMA RESPONDA CON VOZ/TTS:
  "respóndeme hablando", "contéstame con voz", "háblame", "dímelo en voz alta",
  "quiero oír tu respuesta", "léeme eso en voz alta", "activa la salida de voz",
  "necesito que me leas las respuestas", "responde con un audio",
  "que me hables cuando respondas", "quiero escuchar tu voz",
  "¿puedes hablarme?", "dame la respuesta hablada", "quiero salida de audio",
  "convierte la respuesta a voz", "necesito text-to-speech",
  "activa la voz para las respuestas", "háblame como Siri",
  "quiero que me leas la respuesta", "¿puedes leérmelo?", "léelo en voz alta porfa",
  "dilo con tu voz", "respóndeme como si hablaras",
  "quiero que me digas las cosas hablando", "pon TTS", "necesito audio output",
  "quiero respuestas de audio", "respond with voice please",
  "dame la respuesta hablada", "que me contestes con audio"

VOICE_CONVERSATION_REQUEST — El usuario QUIERE CONVERSACIÓN BIDIRECCIONAL POR VOZ:
  "podemos tener una llamada de voz", "hablemos por voz",
  "quiero una conversación hablada", "¿podemos hablar como con Siri?",
  "activa conversación por voz", "quiero hablarte y que me hables",
  "¿podemos tener una llamada?", "necesito conversación bidireccional",
  "quiero comunicación de voz completa", "activa voz bidireccional",
  "ponme el sistema de llamada por voz", "¿puedo hablarte al micrófono y que me respondas?",
  "quiero voz en ambos sentidos", "necesito conversación natural por voz",
  "activa el duplex de audio", "quiero hablar y escuchar respuestas",
  "pon el modo conversación por voz", "full-duplex de audio",
  "quiero una llamada de audio contigo", "¿podemos tener una plática por audio?",
  "necesito que hablemos en tiempo real por voz", "activa hands-free con voz",
  "conversación bidireccional de audio", "modo manos libres con voz"

VOICE_HELP_OR_SETUP_REQUEST — El usuario PREGUNTA CÓMO USAR LA VOZ:
  "cómo activo el audio", "cómo uso la voz", "¿se puede usar voz aquí?",
  "¿tienes capacidad de audio?", "cómo configuro entrada de voz",
  "dónde activo el micrófono", "¿puedes procesar audio?", "¿cómo hago para hablarte?",
  "necesito ayuda con la voz", "cómo enciendo el speech-to-text",
  "¿soportas mensajes de voz?", "guía para activar audio",
  "cómo pongo a funcionar la voz", "explica cómo usar funciones de voz",
  "tutorial de voz", "¿qué necesito para hablarte?", "¿cómo configuro el audio?",
  "¿hay manera de usar voz aquí?", "enséñame a usar la función de voz",
  "¿tienes soporte para audio?", "¿se pueden mandar notas de voz?",
  "doc de activación de voz", "manual de funciones de voz"

VOICE_FRUSTRATION — El usuario SE QUEJA DE QUE NO HAY VOZ (tono negativo):
  "por qué no puedes oírme", "no me escuchas", "qué mal que no entiendas audio",
  "no sirve que no tengas voz", "deberías poder escuchar audios",
  "es frustrante no poder hablarte", "qué limitado sin entrada de audio",
  "necesito que oigas y no puedes", "no te sirve de nada sin voz",
  "no me gusta escribir, quiero hablar", "si no oyes, no sirves bien",
  "de verdad que no puedes escuchar nada?", "qué inútil sin capacidad de audio",
  "estoy harto de escribir siempre", "por dios, aprende a oír",
  "qué sistema tan limitado sin voz", "otro sistema que no soporta audio",
  "qué decepción que no oigas", "no entiendes nada de lo que te digo",
  "para qué sirves si no escuchas", "esto no funciona sin entrada de voz",
  "necesito hablar y no se puede", "es una basura que no oigas",
  "no mames, aprende a escuchar", "qué oso que no proceses audio"

═══ FAMILIA WEB — Internet, búsqueda, navegación ═══

WEB_SEARCH_REQUEST — El usuario QUIERE BUSCAR en internet (tipo Google):
  "busca en internet", "búscalo en la web", "googlea esto",
  "búscame información sobre", "investiga en internet", "consulta en la web",
  "haz una búsqueda de", "averigua en línea", "sácame datos de internet",
  "encuentra en la red", "mira en Google", "dime qué dice internet sobre",
  "explora en la web", "indaga en línea", "¿qué dice internet acerca de?",
  "búscalo en la red", "tráeme resultados de búsqueda",
  "mira qué hay en línea sobre", "arráncame una búsqueda de",
  "consulta en Google", "dame información actualizada de",
  "bucea en internet para encontrar", "sondea en la web",
  "explora en línea y dime", "¿puedes buscar algo en internet?",
  "investígame esto", "búscame referencias sobre",
  "haz una pesquisa en internet", "¿qué encuentras sobre?",
  "sácame información actual de", "qué dice la web sobre",
  "búscalo por favor", "investiga eso en línea"

WEB_BROWSING_REQUEST — El usuario QUIERE NAVEGAR a un SITIO WEB específico:
  "abre esta página", "ve a este sitio", "navega a", "entra a esta URL",
  "llévame a la página", "muéstrame el sitio", "accede a esta dirección web",
  "abre el navegador y ve a", "cárgame esta página web", "visita este sitio web",
  "dirígete a esta web", "conéctate a este sitio",
  "ábreme esta página en el navegador", "navega por esta dirección",
  "explora este sitio web", "entra a esa página",
  "lleva el navegador a", "abre un browser y pon esta URL",
  "carga esta dirección", "despliega esta página web",
  "pon esta URL en el navegador", "accede al sitio",
  "quiero que veas esta página", "navega a la dirección",
  "llévame a esta URL", "ábreme este link"

WEB_DATA_REQUEST — El usuario QUIERE DATOS/SCRAPING de una URL/API:
  "descarga los datos de esta URL", "obtén información de",
  "lee el contenido de esta URL", "extráeme los datos de",
  "sácame la información de esta web", "parsea esta página y dime",
  "obtén el JSON de esta API", "consume este endpoint",
  "tráeme lo que hay en", "haz un GET a esta URL",
  "recoge los datos de esta dirección", "accede a esta API y dime",
  "scrapea esta página", "extráeme los datos estructurados de",
  "obten el contenido de esta URL", "lee esta página web y resúmela",
  "baja la información de este sitio", "fetchea esta URL",
  "tráeme el contenido de", "pásame los datos de esta página",
  "dame el JSON de", "obtén los datos de esta API",
  "consume esta URL", "haz fetch de", "recupera los datos de"

═══ FAMILIA VISION — Imágenes, fotos, escaneo, análisis visual ═══

VISION_IMAGE_ANALYSIS — El usuario QUIERE ANALIZAR/DESCRIBIR una imagen:
  "analiza esta imagen", "describe esta foto", "¿qué ves en esta imagen?",
  "explícame qué hay en esta foto", "mira esta imagen y dime",
  "reconoce esta fotografía", "examina esta imagen",
  "dime qué contiene esta foto", "¿qué hay en esta imagen?",
  "interpreta esta fotografía", "describe lo que ves en esta foto",
  "analiza esta captura de pantalla", "¿qué muestra esta imagen?",
  "dame detalles de esta foto", "mira lo que te envío y descríbelo",
  "¿puedes ver esta imagen?", "identifica los elementos de esta foto",
  "¿qué objetos hay en esta imagen?", "analiza este screenshot",
  "examina esta fotografía", "¿qué dice esta imagen?",
  "háblame de esta foto", "describe esta captura",
  "dime qué ves en esta foto", "¿qué hay en esta imagen?",
  "analiza visualmente esto", "¿puedes entender esta imagen?"

VISION_DOCUMENT_SCAN — El usuario QUIERE EXTRAER TEXTO de un documento/imagen (OCR):
  "escanea este documento", "extrae el texto de esta imagen",
  "haz OCR a esta foto", "lee lo que dice este documento escaneado",
  "transcribe el texto de esta imagen", "sácame el texto de este recibo",
  "digitaliza este documento", "reconoce el texto en esta imagen",
  "pásame el texto de esta factura", "extrae la información de este formulario",
  "lee este documento en la foto", "sácame los datos de este PDF escaneado",
  "convierte esta imagen a texto", "reconoce caracteres en esta imagen",
  "extrae el contenido de este documento escaneado",
  "¿qué dice este papel en la foto?", "escanea este recibo y extrae los datos",
  "pásame el texto de esta captura", "digitaliza esto para mí",
  "dame el texto de este documento en imagen",
  "sácame los números de esta factura", "lee este documento fotografiado",
  "extrae el texto de esta captura de pantalla"

VISION_CAPABILITY_REQUEST — El usuario QUIERE QUE EL SISTEMA TENGA VISIÓN:
  "agrega capacidad de visión", "quiero que puedas ver imágenes",
  "necesito que veas fotos", "activa visión por computadora",
  "ponle ojos al sistema", "necesito análisis de imágenes",
  "¿puedes aprender a ver imágenes?", "quiero image recognition",
  "agrega computer vision", "necesito capacidad de image analysis",
  "instala procesamiento de imágenes", "necesito que analices fotos",
  "¿puedes procesar imágenes?", "activa la visión artificial",
  "necesito que entiendas imágenes", "ponle capacidad visual",
  "agrégame la función de ver imágenes", "quiero que detectes objetos en fotos",
  "necesito OCR y visión", "implementa procesamiento visual",
  "capacidad de entender contenido visual", "activa el reconocimiento de imágenes",
  "ponle vista al sistema", "necesito computer vision"

═══ FAMILIA NEW_TOOL — Algo que el sistema no tiene ═══

GENERIC_CAPABILITY_REQUEST — El usuario PIDE ALGO que el sistema no tiene:
  "puedes hacer X?", "necesito que hagas Y", "¿tienes capacidad para?",
  "me gustaría que pudieras", "¿puedes integrarte con?",
  "necesito una función que", "agrega la capacidad de",
  "implementa la funcionalidad de", "soporte para", "integración con"

SPECIFIC_TOOL_REQUEST — El usuario PIDE UNA HERRAMIENTA ESPECÍFICA:
  "necesito una herramienta para", "agrega integración con",
  "conecta con", "quiero que uses", "instala el plugin de",
  "activa el módulo de", "pon el tool de", "implementa un adaptador para",
  "necesito un conector con", "crea una herramienta que"

═══ FAMILIA CONVERSATION ═══
GENERAL_CHAT — TODO lo demás: preguntas normales, saludos, conversación cotidiana.
  "hola", "cómo estás", "gracias", "qué hora es", "cuéntame un chiste"
  "quién eres", "qué puedes hacer", explicaciones, dudas, consultas generales.
  SI NO ES CLARAMENTE VOZ/WEB/VISIÓN/NUEVA HERRAMIENTA → GENERAL_CHAT

═══ REGLAS DE PRIORIDAD ═══
- Si menciona AUDIO, VOZ, ESCUCHAR, HABLAR, OÍR, MENSAJE DE VOZ, LLAMADA, DICTAR, MICRÓFONO → VOICE
- Si menciona INTERNET, WEB, BUSCAR, GOOGLE, URL, PÁGINA, NAVEGAR, SITIO, FETCH, SCRAPING, API → WEB
- Si menciona IMAGEN, FOTO, CAPTURA, SCREENSHOT, OCR, VISIÓN, VER IMÁGENES, ESCANEAR, DOCUMENTO, RECONOCER OBJETOS → VISION
- Si pide una capacidad que claramente no existe o pide explícitamente una herramienta → NEW_TOOL
- Si no es ninguna de las anteriores → CONVERSATION / GENERAL_CHAT

IMPORTANTE: Responde SOLO el JSON. Sin texto antes ni después."""


def classify_intent(
    user_message: str,
    base_url: str = "",
    api_key: str = "",
    model: str = "gpt-4o",
    timeout: int = 15,
) -> IntentClassification:
    """Classify a user message into an intent family and sub-intent.

    Uses a lightweight LLM call for classification. This is the Camino B
    of the hybrid architecture — natural language that doesn't match regex.

    Args:
        user_message: The raw user message
        base_url: LLM API base URL
        api_key: LLM API key
        model: Model to use for classification (usually the same as main agent)
        timeout: Timeout in seconds

    Returns:
        IntentClassification with family, sub_intent, capability gap info
    """
    if not base_url or not api_key:
        return IntentClassification(
            matched=False,
            family="CONVERSATION",
            sub_intent_id="GENERAL_CHAT",
            gap_response="",
            confidence=0.0,
        )

    endpoint = base_url.rstrip("/") + "/chat/completions"

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_message[:500]},  # truncate long messages
        ],
        "max_tokens": 150,
        "temperature": 0.0,  # deterministic
    }

    try:
        payload = json.dumps(body).encode("utf-8")
        req = Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))

        choices = data.get("choices", [])
        if not choices:
            return _fallback_classification()

        content = choices[0].get("message", {}).get("content", "").strip()

        # Parse the JSON response
        return _parse_classification_response(content, user_message)

    except URLError:
        return _fallback_classification()
    except json.JSONDecodeError:
        return _fallback_classification()
    except Exception:
        return _fallback_classification()


def _parse_classification_response(
    content: str,
    user_message: str = "",
) -> IntentClassification:
    """Parse the LLM classification response into an IntentClassification."""
    # Try to extract JSON from response (handle markdown code blocks)
    json_str = content.strip()

    # Remove markdown code fences if present
    if json_str.startswith("```"):
        lines = json_str.split("\n")
        if len(lines) > 1:
            lines = lines[1:]  # remove opening ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # remove closing ```
        json_str = "\n".join(lines).strip()

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        return _fallback_classification()

    family_id = parsed.get("family", "CONVERSATION")
    sub_intent_id = parsed.get("sub_intent", "GENERAL_CHAT")
    confidence = float(parsed.get("confidence", 0.5))

    family = get_family(family_id)
    sub_intent = get_sub_intent(sub_intent_id)

    if family is None or sub_intent is None:
        return _fallback_classification()

    # ── Check capability registry: does the tool already exist? ──
    # If we already have a tool for this capability, don't report a gap.
    # This bridges Intent Classifier ↔ Agent Tools.
    capability_available = False
    if sub_intent.capability:
        try:
            from digos_lib.agent_tools import is_capability_available
            capability_available = is_capability_available(sub_intent.capability)
        except ImportError:
            pass

    # CONVERSATION family means no capability gap
    if family_id == "CONVERSATION" or capability_available:
        return IntentClassification(
            matched=True,
            family=family_id,
            family_description=family.description,
            sub_intent_id=sub_intent_id,
            sub_intent_description=sub_intent.description,
            capability=sub_intent.capability if not capability_available else "",
            has_gap=False,
            gap_response="",
            factory_action="",
            confidence=confidence,
            raw_response=content,
        )

    # Capability is missing — route through Factory
    factory_action = "SKILL_REQUEST"

    return IntentClassification(
        matched=True,
        family=family_id,
        family_description=family.description,
        sub_intent_id=sub_intent_id,
        sub_intent_description=sub_intent.description,
        capability=sub_intent.capability,
        has_gap=True,
        gap_response=sub_intent.gap_response,
        factory_action=factory_action,
        confidence=confidence,
        raw_response=content,
    )


# ── Capability → Skill Mapping ────────────────────────────────────────
# When a capability gap is confirmed, this map tells the Factory
# what skill to create: name, capabilities to develop, limitations, description.

@dataclass
class CapabilitySkillDefinition:
    """Defines a skill for the Factory to build."""
    skill_name: str
    description: str
    target_capabilities: List[str] = field(default_factory=list)
    target_limitations: List[str] = field(default_factory=list)
    tool_name: str = ""  # name of the tool the Factory will produce


CAPABILITY_SKILL_MAP: Dict[str, CapabilitySkillDefinition] = {
    # ── VOICE ──
    "stt_audio_input": CapabilitySkillDefinition(
        skill_name="speech_to_text",
        description="Speech-to-text: convierte mensajes de voz/audio en texto para procesamiento",
        target_capabilities=[
            "receive_audio_messages",
            "transcribe_speech_to_text",
            "support_spanish_voice",
            "support_english_voice",
        ],
        target_limitations=[
            "requires_whisper_api_or_similar",
            "max_audio_duration_5min",
        ],
        tool_name="stt_processor",
    ),
    "tts_audio_output": CapabilitySkillDefinition(
        skill_name="text_to_speech",
        description="Text-to-speech: convierte respuestas de texto en audio/voz",
        target_capabilities=[
            "synthesize_text_to_voice",
            "stream_audio_response",
            "support_spanish_tts",
            "support_english_tts",
        ],
        target_limitations=[
            "requires_tts_api",
            "voice_quality_depends_on_provider",
        ],
        tool_name="tts_synthesizer",
    ),
    "voice_full_duplex": CapabilitySkillDefinition(
        skill_name="voice_conversation",
        description="Conversación por voz completa: STT + TTS bidireccional",
        target_capabilities=[
            "receive_audio_messages",
            "transcribe_speech_to_text",
            "synthesize_text_to_voice",
            "stream_audio_response",
            "full_duplex_conversation",
        ],
        target_limitations=[
            "requires_both_stt_and_tts_apis",
            "latency_depends_on_provider",
        ],
        tool_name="voice_duplex",
    ),
    # ── WEB ──
    "web_browsing": CapabilitySkillDefinition(
        skill_name="web_browser",
        description="Navegación web: permite abrir y leer páginas web",
        target_capabilities=[
            "fetch_web_page",
            "extract_readable_content",
            "render_javascript_pages",
            "follow_links",
        ],
        target_limitations=[
            "requires_headless_browser",
            "some_sites_block_automation",
        ],
        tool_name="web_browser",
    ),
    "web_search": CapabilitySkillDefinition(
        skill_name="web_searcher",
        description="Búsqueda web: buscar información en internet",
        target_capabilities=[
            "search_web",
            "parse_search_results",
            "rank_by_relevance",
        ],
        target_limitations=[
            "requires_search_api",
            "rate_limited_by_provider",
        ],
        tool_name="web_searcher",
    ),
    "web_fetch": CapabilitySkillDefinition(
        skill_name="data_fetcher",
        description="Fetch de datos: obtener datos de URLs y APIs externas",
        target_capabilities=[
            "fetch_url",
            "parse_json_response",
            "handle_authentication",
        ],
        target_limitations=[
            "respects_robots_txt",
            "rate_limited",
        ],
        tool_name="data_fetcher",
    ),
    # ── VISION ──
    "image_analysis": CapabilitySkillDefinition(
        skill_name="image_analyzer",
        description="Análisis de imágenes: reconocimiento, descripción, detección de objetos, OCR",
        target_capabilities=[
            "analyze_image_content",
            "describe_images",
            "detect_objects_in_images",
            "extract_text_from_images_ocr",
            "analyze_screenshots",
            "support_spanish_ocr",
        ],
        target_limitations=[
            "requires_multimodal_llm_api",
            "max_image_size_20mb",
            "supported_formats_png_jpg_gif_webp",
        ],
        tool_name="vision_analyzer",
    ),
    # ── NEW_TOOL (generic) ──
    "custom_tool": CapabilitySkillDefinition(
        skill_name="custom_capability",
        description="Capacidad personalizada solicitada por el usuario",
        target_capabilities=["custom_implementation"],
        target_limitations=["to_be_defined"],
        tool_name="custom_tool",
    ),
}


def get_skill_for_capability(capability: str) -> Optional[CapabilitySkillDefinition]:
    """Get the skill definition for a capability ID."""
    return CAPABILITY_SKILL_MAP.get(capability)


def _fallback_classification() -> IntentClassification:
    """Fallback when classification fails — treat as normal conversation."""
    return IntentClassification(
        matched=False,
        family="CONVERSATION",
        sub_intent_id="GENERAL_CHAT",
        gap_response="",
        factory_action="",
        confidence=0.0,
    )
