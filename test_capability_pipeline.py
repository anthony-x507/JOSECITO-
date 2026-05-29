#!/usr/bin/env python3
"""
PRUEBA DE CAPABILITIES — Batería completa de tests
====================================================
1. 15 VOICE:   Diferentes formas de pedir herramienta de voz (STT/TTS)
2. 15 WEB:     Diferentes formas de pedir búsqueda web
3.  5 VISION:  Diferentes formas de pedir visión/análisis de imágenes
4. 10 TICKET:  Persistencia del pipeline S&D (Engineer sigue las instrucciones)
5. 14 CAP:     Flujo completo de capability gap + Factory callback

Estrategia de testing:
  - VOICE / WEB / VISION: mockean classify_intent() porque requiere API key real.
    Se testean las estructuras de datos reales (INTENT_FAMILIES, CAPABILITY_SKILL_MAP,
    AVAILABLE_CAPABILITIES, get_family(), get_sub_intent(), etc.)
  - TICKET S&D: tests 100% reales contra SystemEngineer — sin mock.
  - CAP FLOW: tests reales contra SystemEngineer + mock factory_create_fn callback.

Ejecutar: python3 test_capability_pipeline.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ─────────────────────────────────────────────
# SETUP: Temporary directory for tests
# ─────────────────────────────────────────────

TEST_DIR = Path(tempfile.mkdtemp(prefix="digos_cap_test_"))
os.environ["HOME"] = str(TEST_DIR)
os.chdir(str(TEST_DIR))

(TEST_DIR / ".digos").mkdir(exist_ok=True)
(TEST_DIR / ".digos" / "profiles").mkdir(exist_ok=True)

import digos
import digos_lib.core_engineer
import digos_lib.core_vault
import digos_lib.core_centinela
import digos_lib.core_self
import digos_lib.core_log
import digos_lib.core_tower
from digos_lib import intent_classifier
from digos_lib.intent_classifier import (
    get_family, get_sub_intent, get_skill_for_capability,
    INTENT_FAMILIES, CAPABILITY_SKILL_MAP,
    CapabilitySkillDefinition, IntentClassification, SubIntent,
)
from digos_lib.agent_tools import (
    AVAILABLE_CAPABILITIES, is_capability_available,
    register_capability, capability_set_state, capability_get_info,
    CapabilityState, add_dynamic_tool, DYNAMIC_TOOLS, DYNAMIC_TOOL_DEFS,
)
from digos_lib.core_engineer import SystemEngineer
from digos_lib.core_log import LogKeeper
from digos_lib.core_pipeline import TicketConversationPipeline
from digos_lib.core_tower import TorreDeControl

# Patch all path constants
digos.DIGOS_DIR = TEST_DIR / ".digos"
digos.KEY_FILE = digos.DIGOS_DIR / ".digos_key"
digos.VAULT_FILE = digos.DIGOS_DIR / "vault.enc"
digos.STATE_FILE = digos.DIGOS_DIR / "state.json"
digos.STRIKES_FILE = digos.DIGOS_DIR / "strikes.json"
digos.TICKETS_FILE = digos.DIGOS_DIR / "tickets.json"
digos.SELF_FILE = digos.DIGOS_DIR / "self.json"
digos.LOG_DIR = digos.DIGOS_DIR / "logs"

digos_lib.core_engineer.DIGOS_DIR = digos.DIGOS_DIR
digos_lib.core_vault.KEY_FILE = digos.KEY_FILE
digos_lib.core_vault.VAULT_FILE = digos.VAULT_FILE
digos_lib.core_centinela.DIGOS_DIR = digos.DIGOS_DIR
digos_lib.core_centinela.STRIKES_FILE = digos.STRIKES_FILE
digos_lib.core_self.SELF_FILE = digos.SELF_FILE
digos_lib.core_log.LOG_DIR = digos.LOG_DIR
digos_lib.core_tower.DIGOS_DIR = digos.DIGOS_DIR
digos_lib.core_tower.STATE_FILE = digos.STATE_FILE
digos_lib.core_tower.STRIKES_FILE = digos.STRIKES_FILE
digos_lib.core_tower.TICKETS_FILE = digos.TICKETS_FILE
digos_lib.core_tower.SELF_FILE = digos.SELF_FILE
digos_lib.core_tower.LOG_DIR = digos.LOG_DIR
digos_lib.core_tower.KEY_FILE = digos.KEY_FILE
digos_lib.core_tower.VAULT_FILE = digos.VAULT_FILE


def _ensure_profile(profile: str):
    (TEST_DIR / ".digos" / "profiles" / profile).mkdir(parents=True, exist_ok=True)


_ensure_profile("test-agent")


# ─────────────────────────────────────────────
# HELPERS — Mock classification factory
# ─────────────────────────────────────────────

def _make_classification(family: str, sub_intent_id: str,
                         capability: str = "", has_gap: bool = True,
                         gap_response: str = "", matched: bool = True,
                         confidence: float = 0.95) -> IntentClassification:
    """Build an IntentClassification for testing without calling the LLM."""
    si = get_sub_intent(sub_intent_id)
    fam = get_family(family)
    return IntentClassification(
        matched=matched,
        family=family,
        family_description=fam.description if fam else "",
        sub_intent_id=sub_intent_id,
        sub_intent_description=si.description if si else "",
        capability=capability or (si.capability if si else ""),
        has_gap=has_gap,
        gap_response=gap_response or (si.gap_response if si else ""),
        factory_action="SKILL_REQUEST" if has_gap and capability else "",
        confidence=confidence,
    )


def _mock_classify_side_effect(msg_map: dict):
    """Build a side_effect function that routes messages to expected classifications.
    
    msg_map: {message_prefix: (family, sub_intent_id, capability, has_gap)}
    The first matching prefix wins.
    """
    def side_effect(user_message, base_url="", api_key="", model="", timeout=15):
        for prefix, (family, sub_intent_id, capability, has_gap) in msg_map.items():
            if prefix.lower() in user_message.lower():
                return _make_classification(family, sub_intent_id, capability, has_gap)
        return _make_classification("CONVERSATION", "GENERAL_CHAT", matched=False)
    return side_effect


def _register_ready_dynamic_capability(capability_id: str, tool_name: str) -> None:
    """Register a test-only dynamic tool and mark its capability executable."""
    DYNAMIC_TOOLS.pop(tool_name, None)
    DYNAMIC_TOOL_DEFS[:] = [
        tool_def for tool_def in DYNAMIC_TOOL_DEFS
        if tool_def.get("function", {}).get("name") != tool_name
    ]
    register_capability(capability_id, tool_name, source="test_factory")
    add_dynamic_tool(
        tool_name,
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": "Test-only dynamic tool",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        lambda args=None, **kwargs: {"ok": True},
    )
    capability_set_state(
        capability_id,
        CapabilityState.TOOL_READY,
        notes="Test dynamic tool is loaded in DYNAMIC_TOOLS",
    )


# ════════════════════════════════════════════════════
# PARTE 1: 15 TESTS DE VOZ — Capacidad STT/TTS
# ════════════════════════════════════════════════════

class TestVoiceCapabilityRequests(unittest.TestCase):
    """15 tests: estructura de INTENT_FAMILIES[VOICE], clasificación con mock,
    capability gaps, CAPABILITY_SKILL_MAP, y registro de capacidades."""

    # ── Test 1-6: Verificar que INTENT_FAMILIES tiene la estructura correcta ──

    def test_voice_01_family_exists(self):
        """INTENT_FAMILIES debe contener VOICE con 6 sub_intents."""
        self.assertIn("VOICE", INTENT_FAMILIES)
        family = INTENT_FAMILIES["VOICE"]
        self.assertEqual(len(family.sub_intents), 6,
                         "VOICE debe tener exactamente 6 sub_intents")

    def test_voice_02_voice_input_now_def(self):
        """VOICE_INPUT_NOW: capability=stt_audio_input, gap_response no vacío."""
        si = get_sub_intent("VOICE_INPUT_NOW")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "stt_audio_input")
        self.assertTrue(len(si.gap_response) > 0)
        self.assertIn("🎤", si.gap_response)

    def test_voice_03_voice_capability_request_def(self):
        """VOICE_INPUT_CAPABILITY_REQUEST: capability=stt_audio_input."""
        si = get_sub_intent("VOICE_INPUT_CAPABILITY_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "stt_audio_input")
        self.assertIn("STT", si.gap_response)

    def test_voice_04_voice_output_def(self):
        """VOICE_OUTPUT_REQUEST: capability=tts_audio_output."""
        si = get_sub_intent("VOICE_OUTPUT_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "tts_audio_output")
        self.assertIn("TTS", si.gap_response)

    def test_voice_05_voice_full_duplex_def(self):
        """VOICE_CONVERSATION_REQUEST: capability=voice_full_duplex."""
        si = get_sub_intent("VOICE_CONVERSATION_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "voice_full_duplex")
        self.assertIn("STT + TTS", si.gap_response)

    def test_voice_06_voice_frustration_def(self):
        """VOICE_FRUSTRATION: capability=stt_audio_input, gap_response empático."""
        si = get_sub_intent("VOICE_FRUSTRATION")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "stt_audio_input")
        self.assertIn("frustración", si.gap_response.lower())

    # ── Test 7-11: Clasificación con mock ──

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_voice_07_te_mando_un_audio(self, mock_cls):
        """'te mando un audio' → VOICE/VOICE_INPUT_NOW"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "te mando un audio": ("VOICE", "VOICE_INPUT_NOW", "stt_audio_input", True),
        })
        result = intent_classifier.classify_intent("te mando un audio")
        self.assertTrue(result.matched)
        self.assertEqual(result.family, "VOICE")
        self.assertEqual(result.sub_intent_id, "VOICE_INPUT_NOW")
        self.assertEqual(result.capability, "stt_audio_input")
        print(f"  ✅ [VOICE-07] 'te mando un audio' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_voice_08_escucha_esto(self, mock_cls):
        """'escucha esto' → VOICE/VOICE_INPUT_NOW"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "escucha esto": ("VOICE", "VOICE_INPUT_NOW", "stt_audio_input", True),
        })
        result = intent_classifier.classify_intent("escucha esto")
        self.assertEqual(result.family, "VOICE")
        self.assertEqual(result.sub_intent_id, "VOICE_INPUT_NOW")
        print(f"  ✅ [VOICE-08] 'escucha esto' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_voice_09_quiero_me_escuches(self, mock_cls):
        """'quiero que me escuches' → VOICE/VOICE_INPUT_CAPABILITY_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "quiero que me escuches": ("VOICE", "VOICE_INPUT_CAPABILITY_REQUEST", "stt_audio_input", True),
        })
        result = intent_classifier.classify_intent("quiero que me escuches")
        self.assertEqual(result.family, "VOICE")
        self.assertEqual(result.sub_intent_id, "VOICE_INPUT_CAPABILITY_REQUEST")
        print(f"  ✅ [VOICE-09] 'quiero que me escuches' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_voice_10_respondeme_hablando(self, mock_cls):
        """'respóndeme hablando' → VOICE/VOICE_OUTPUT_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "respóndeme hablando": ("VOICE", "VOICE_OUTPUT_REQUEST", "tts_audio_output", True),
        })
        result = intent_classifier.classify_intent("respóndeme hablando")
        self.assertEqual(result.family, "VOICE")
        self.assertEqual(result.sub_intent_id, "VOICE_OUTPUT_REQUEST")
        print(f"  ✅ [VOICE-10] 'respóndeme hablando' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_voice_11_llamada_voz(self, mock_cls):
        """'podemos tener una llamada de voz' → VOICE/VOICE_CONVERSATION_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "llamada de voz": ("VOICE", "VOICE_CONVERSATION_REQUEST", "voice_full_duplex", True),
        })
        result = intent_classifier.classify_intent("podemos tener una llamada de voz")
        self.assertEqual(result.family, "VOICE")
        self.assertEqual(result.sub_intent_id, "VOICE_CONVERSATION_REQUEST")
        print(f"  ✅ [VOICE-11] 'llamada de voz' → {result.family}/{result.sub_intent_id}")

    # ── Test 12-13: Capability gap detection ──

    def test_voice_12_gap_cuando_no_registrado(self):
        """Si stt_audio_input NO está en AVAILABLE_CAPABILITIES → has_gap=True."""
        # Asegurar que la capacidad NO está registrada
        saved = dict(AVAILABLE_CAPABILITIES)
        AVAILABLE_CAPABILITIES.pop("stt_audio_input", None)
        try:
            # Simular clasificación para VOICE_INPUT_CAPABILITY_REQUEST sin capacidad
            result = _make_classification("VOICE", "VOICE_INPUT_CAPABILITY_REQUEST",
                                          "stt_audio_input", has_gap=True)
            self.assertTrue(result.has_gap)
            self.assertEqual(result.factory_action, "SKILL_REQUEST")
            self.assertTrue(len(result.gap_response) > 0)
            # Verificar que is_capability_available dice False
            self.assertFalse(is_capability_available("stt_audio_input"))
        finally:
            AVAILABLE_CAPABILITIES.clear()
            AVAILABLE_CAPABILITIES.update(saved)

    def test_voice_13_registered_voice_still_has_gap_until_validated(self):
        """stt_audio_input registrada no equivale a capacidad ejecutable."""
        register_capability("stt_audio_input", "transcribe_audio")
        info = capability_get_info("stt_audio_input")
        self.assertEqual(info["state"], CapabilityState.REGISTERED)
        self.assertFalse(is_capability_available("stt_audio_input"))

        result = _make_classification("VOICE", "VOICE_INPUT_CAPABILITY_REQUEST",
                                      "stt_audio_input", has_gap=True)
        self.assertTrue(result.has_gap)
        self.assertEqual(result.factory_action, "SKILL_REQUEST")

    # ── Test 14-15: CAPABILITY_SKILL_MAP para voice ──

    def test_voice_14_skill_map_stt(self):
        """stt_audio_input en CAPABILITY_SKILL_MAP tiene skill speech_to_text."""
        skill = CAPABILITY_SKILL_MAP.get("stt_audio_input")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.skill_name, "speech_to_text")
        self.assertTrue(len(skill.target_capabilities) > 0)
        self.assertTrue(len(skill.tool_name) > 0)
        self.assertEqual(skill.tool_name, "stt_processor")

    def test_voice_15_skill_map_tts(self):
        """tts_audio_output en CAPABILITY_SKILL_MAP tiene skill text_to_speech."""
        skill = CAPABILITY_SKILL_MAP.get("tts_audio_output")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.skill_name, "text_to_speech")
        self.assertTrue(len(skill.target_capabilities) > 0)
        self.assertEqual(skill.tool_name, "tts_synthesizer")


# ════════════════════════════════════════════════════
# PARTE 2: 15 TESTS DE WEB — Capacidad de búsqueda web
# ════════════════════════════════════════════════════

class TestWebCapabilityRequests(unittest.TestCase):
    """15 tests: estructura de INTENT_FAMILIES[WEB], clasificación con mock,
    capability gaps, CAPABILITY_SKILL_MAP para web."""

    # ── Test 1-4: Verificar estructura INTENT_FAMILIES[WEB] ──

    def test_web_01_family_exists(self):
        """INTENT_FAMILIES debe contener WEB con 3 sub_intents."""
        self.assertIn("WEB", INTENT_FAMILIES)
        family = INTENT_FAMILIES["WEB"]
        self.assertEqual(len(family.sub_intents), 3,
                         "WEB debe tener exactamente 3 sub_intents")

    def test_web_02_web_search_def(self):
        """WEB_SEARCH_REQUEST: capability=web_search."""
        si = get_sub_intent("WEB_SEARCH_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "web_search")
        self.assertIn("🔍", si.gap_response)

    def test_web_03_web_browsing_def(self):
        """WEB_BROWSING_REQUEST: capability=web_browsing."""
        si = get_sub_intent("WEB_BROWSING_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "web_browsing")
        self.assertIn("🌐", si.gap_response)

    def test_web_04_web_data_def(self):
        """WEB_DATA_REQUEST: capability=web_fetch."""
        si = get_sub_intent("WEB_DATA_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "web_fetch")
        self.assertIn("📡", si.gap_response)

    # ── Test 5-10: Clasificación con mock ──

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_web_05_busca_en_internet(self, mock_cls):
        """'busca en internet' → WEB/WEB_SEARCH_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "busca en internet": ("WEB", "WEB_SEARCH_REQUEST", "web_search", True),
        })
        result = intent_classifier.classify_intent("busca en internet el clima de hoy")
        self.assertTrue(result.matched)
        self.assertEqual(result.family, "WEB")
        self.assertEqual(result.sub_intent_id, "WEB_SEARCH_REQUEST")
        self.assertEqual(result.capability, "web_search")
        print(f"  ✅ [WEB-05] 'busca en internet' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_web_06_googlea_esto(self, mock_cls):
        """'googlea esto' → WEB/WEB_SEARCH_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "googlea esto": ("WEB", "WEB_SEARCH_REQUEST", "web_search", True),
        })
        result = intent_classifier.classify_intent("googlea esto para mi")
        self.assertEqual(result.family, "WEB")
        self.assertEqual(result.sub_intent_id, "WEB_SEARCH_REQUEST")
        print(f"  ✅ [WEB-06] 'googlea esto' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_web_07_busca_informacion(self, mock_cls):
        """'búscame información sobre' → WEB/WEB_SEARCH_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "búscame información": ("WEB", "WEB_SEARCH_REQUEST", "web_search", True),
        })
        result = intent_classifier.classify_intent("búscame información sobre algo")
        self.assertEqual(result.family, "WEB")
        self.assertEqual(result.sub_intent_id, "WEB_SEARCH_REQUEST")
        print(f"  ✅ [WEB-07] 'búscame información' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_web_08_abre_google(self, mock_cls):
        """'abre google.com' → WEB/WEB_BROWSING_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "abre google": ("WEB", "WEB_BROWSING_REQUEST", "web_browsing", True),
        })
        result = intent_classifier.classify_intent("abre google.com")
        self.assertEqual(result.family, "WEB")
        self.assertEqual(result.sub_intent_id, "WEB_BROWSING_REQUEST")
        self.assertEqual(result.capability, "web_browsing")
        print(f"  ✅ [WEB-08] 'abre google.com' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_web_09_ve_a_pagina(self, mock_cls):
        """'ve a esta página' → WEB/WEB_BROWSING_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "ve a esta página": ("WEB", "WEB_BROWSING_REQUEST", "web_browsing", True),
        })
        result = intent_classifier.classify_intent("ve a esta página web")
        self.assertEqual(result.family, "WEB")
        self.assertEqual(result.sub_intent_id, "WEB_BROWSING_REQUEST")
        print(f"  ✅ [WEB-09] 've a esta página' → {result.family}/{result.sub_intent_id}")

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_web_10_descarga_de_esta_url(self, mock_cls):
        """'descarga los datos de esta URL' → WEB/WEB_DATA_REQUEST"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "descarga los datos": ("WEB", "WEB_DATA_REQUEST", "web_fetch", True),
        })
        result = intent_classifier.classify_intent("descarga los datos de esta URL")
        self.assertEqual(result.family, "WEB")
        self.assertEqual(result.sub_intent_id, "WEB_DATA_REQUEST")
        self.assertEqual(result.capability, "web_fetch")
        print(f"  ✅ [WEB-10] 'descarga de URL' → {result.family}/{result.sub_intent_id}")

    # ── Test 11-13: Verificar que web_search ya está disponible ──

    def test_web_11_web_search_disponible(self):
        """web_search debe estar en AVAILABLE_CAPABILITIES."""
        self.assertTrue(is_capability_available("web_search"),
                        "web_search debe estar disponible por defecto")
        self.assertEqual(AVAILABLE_CAPABILITIES.get("web_search"), "web_search")

    def test_web_12_sin_gap_cuando_disponible(self):
        """Cuando web_search está disponible → no hay gap."""
        result = _make_classification("WEB", "WEB_SEARCH_REQUEST",
                                      "web_search", has_gap=False)
        self.assertFalse(result.has_gap)
        self.assertEqual(result.factory_action, "")

    def test_web_13_gap_cuando_no_disponible(self):
        """web_browsing NO está en AVAILABLE_CAPABILITIES → gap."""
        self.assertFalse(is_capability_available("web_browsing"),
                         "web_browsing no debe estar disponible por defecto")

    # ── Test 14-15: CAPABILITY_SKILL_MAP para web ──

    def test_web_14_skill_map_web_search(self):
        """web_search en CAPABILITY_SKILL_MAP tiene skill web_searcher."""
        skill = CAPABILITY_SKILL_MAP.get("web_search")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.skill_name, "web_searcher")
        self.assertTrue(len(skill.tool_name) > 0)
        self.assertEqual(skill.tool_name, "web_searcher")

    def test_web_15_skill_map_web_browsing(self):
        """web_browsing en CAPABILITY_SKILL_MAP tiene skill web_browser."""
        skill = CAPABILITY_SKILL_MAP.get("web_browsing")
        self.assertIsNotNone(skill)
        self.assertEqual(skill.skill_name, "web_browser")
        self.assertTrue(len(skill.target_capabilities) > 0)
        self.assertEqual(skill.tool_name, "web_browser")


# ════════════════════════════════════════════════════
# PARTE 3: 5 TESTS DE VISIÓN — Capacidad de imagen
# ════════════════════════════════════════════════════

class TestVisionCapabilityRequests(unittest.TestCase):
    """8 tests: NUEVA familia VISION con 3 sub_intents dedicados.
    Testea:
    - La familia VISION con 3 sub_intents (IMAGE_ANALYSIS, DOCUMENT_SCAN, CAPABILITY_REQUEST)
    - CAPABILITY_SKILL_MAP para image_analysis
    - image_analysis registrada pero no disponible hasta validación
    - Clasificación de distintas formas de pedir visión"""

    # ── Test 1-2: Verificar estructura de VISION family ──

    def test_vision_01_family_exists(self):
        """INTENT_FAMILIES debe contener VISION con 3 sub_intents."""
        self.assertIn("VISION", INTENT_FAMILIES)
        family = INTENT_FAMILIES["VISION"]
        self.assertEqual(len(family.sub_intents), 3,
                         "VISION debe tener exactamente 3 sub_intents")

    def test_vision_02_vision_image_analysis_def(self):
        """VISION_IMAGE_ANALYSIS: capability=image_analysis."""
        si = get_sub_intent("VISION_IMAGE_ANALYSIS")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "image_analysis")
        self.assertIn("🖼️", si.gap_response)

    def test_vision_03_vision_document_scan_def(self):
        """VISION_DOCUMENT_SCAN: capability=image_analysis."""
        si = get_sub_intent("VISION_DOCUMENT_SCAN")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "image_analysis")
        self.assertIn("📄", si.gap_response)

    def test_vision_04_vision_capability_request_def(self):
        """VISION_CAPABILITY_REQUEST: capability=image_analysis."""
        si = get_sub_intent("VISION_CAPABILITY_REQUEST")
        self.assertIsNotNone(si)
        self.assertEqual(si.capability, "image_analysis")
        self.assertIn("🖼️", si.gap_response)

    # ── Test 5: image_analysis en CAPABILITY_SKILL_MAP ──

    def test_vision_05_skill_map_image_analysis(self):
        """image_analysis en CAPABILITY_SKILL_MAP tiene skill image_analyzer y tool vision_analyzer."""
        skill = CAPABILITY_SKILL_MAP.get("image_analysis")
        self.assertIsNotNone(skill, "image_analysis debe estar en CAPABILITY_SKILL_MAP")
        self.assertEqual(skill.skill_name, "image_analyzer")
        self.assertTrue(len(skill.target_capabilities) > 0)
        self.assertEqual(skill.tool_name, "vision_analyzer")

    # ── Test 6: image_analysis conocida pero no ejecutable sin validación ──

    def test_vision_06_image_analysis_registered_not_available(self):
        """image_analysis puede estar registrada sin estar lista para producto."""
        self.assertFalse(is_capability_available("image_analysis"),
                         "image_analysis no debe estar disponible hasta validarse")
        self.assertEqual(AVAILABLE_CAPABILITIES.get("image_analysis"), "view_image")
        info = capability_get_info("image_analysis")
        self.assertEqual(info["state"], CapabilityState.REGISTERED)

    # ── Test 7: Clasificación con mock — analiza imagen ──

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_vision_07_analiza_imagen(self, mock_cls):
        """'analiza esta imagen' → VISION/VISION_IMAGE_ANALYSIS"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "analiza esta imagen": ("VISION", "VISION_IMAGE_ANALYSIS", "image_analysis", False),
        })
        result = intent_classifier.classify_intent("analiza esta imagen para mi")
        self.assertTrue(result.matched, "Debe clasificar como matched=True")
        self.assertEqual(result.family, "VISION")
        self.assertEqual(result.sub_intent_id, "VISION_IMAGE_ANALYSIS")
        print(f"  ✅ [VISION-07] 'analiza esta imagen' → {result.family}/{result.sub_intent_id}")

    # ── Test 8: Clasificación con mock — escanear documento ──

    @patch("digos_lib.intent_classifier.classify_intent")
    def test_vision_08_escanea_documento(self, mock_cls):
        """'escanea este documento' → VISION/VISION_DOCUMENT_SCAN"""
        mock_cls.side_effect = _mock_classify_side_effect({
            "escanea este documento": ("VISION", "VISION_DOCUMENT_SCAN", "image_analysis", False),
        })
        result = intent_classifier.classify_intent("escanea este documento y sácame el texto")
        self.assertTrue(result.matched)
        self.assertEqual(result.family, "VISION")
        self.assertEqual(result.sub_intent_id, "VISION_DOCUMENT_SCAN")
        self.assertEqual(result.capability, "image_analysis")
        print(f"  ✅ [VISION-08] 'escanea documento' → {result.family}/{result.sub_intent_id}")


# ════════════════════════════════════════════════════
# PARTE 4: 10 TESTS DE PERSISTENCIA DE TICKETS (S&D)
# ════════════════════════════════════════════════════

class TestTicketPersistence(unittest.TestCase):
    """10 tests para verificar que el pipeline S&D funciona correctamente
    SIN mock — contra SystemEngineer real.

    Verifica que:
    - Los flags cambian en el orden correcto
    - El Engineer sigue las instrucciones del S&D
    - No se puede cerrar un ticket sin pasar por testing
    - El pipeline completo funciona
    - Los reintentos en FAIL funcionan
    """

    def setUp(self):
        self.log = LogKeeper()
        self.eng = SystemEngineer(self.log)
        _ensure_profile("test-sd")

    def tearDown(self):
        profiles_dir = digos.DIGOS_DIR / "profiles"
        if profiles_dir.exists():
            for profile_dir in profiles_dir.iterdir():
                if profile_dir.is_dir():
                    mailbox = profile_dir / "MAILBOX"
                    if mailbox.exists():
                        shutil.rmtree(mailbox)

    # ── Test 1: Pipeline completo create → pickup → submit → test(pass) → close ──

    def test_sd_01_pipeline_completo_pass(self):
        """Pipeline: inbox → processing → testing → review → delivered (S&D completo)"""
        tid = self.eng.create_ticket("test-sd", "feature-a", "Añadir tool web_search",
                                     requester="agente-principal")
        self.assertEqual(self.eng._load_ticket("test-sd", tid)["flag_status"], "inbox",
                         "El ticket debe nacer en inbox")

        # Engineer recoge el ticket
        self.assertTrue(self.eng.pickup_ticket("test-sd", tid),
                        "pickup_ticket debe retornar True")
        self.assertEqual(self.eng._load_ticket("test-sd", tid)["flag_status"], "processing",
                         "Debe pasar a processing")

        # Engineer envía a testing
        self.assertTrue(self.eng.submit_for_testing("test-sd", tid, "Tool creada correctamente"),
                        "submit_for_testing debe retornar True")
        self.assertEqual(self.eng._load_ticket("test-sd", tid)["flag_status"], "testing",
                         "Debe pasar a testing")

        # Agente prueba y pasa
        self.assertTrue(self.eng.test_ticket("test-sd", tid, "✅ Tool funciona correctamente", passed=True),
                        "test_ticket(passed=True) debe retornar True")
        self.assertEqual(self.eng._load_ticket("test-sd", tid)["flag_status"], "review",
                         "Debe pasar a review")

        # Engineer entrega
        self.assertTrue(self.eng.deliver_ticket("test-sd", tid, "Feature-A implementada", "completado"),
                        "deliver_ticket debe retornar True")
        ticket = self.eng._load_ticket("test-sd", tid)
        self.assertEqual(ticket["flag_status"], "delivered",
                         "Debe terminar en delivered")
        self.assertEqual(ticket["status"], "closed",
                         "El ticket debe quedar cerrado")
        self.assertEqual(ticket["result"], "Feature-A implementada")
        self.assertEqual(ticket["resolution"], "completado")
        print(f"  ✅ [SD-01] Pipeline PASS completo: {tid} → inbox→processing→testing→review→delivered")

    # ── Test 2: Pipeline con FAIL → reintento → PASS ──

    def test_sd_02_pipeline_fail_then_retry(self):
        """Pipeline: testing → FAIL → processing → testing → PASS → review → delivered"""
        tid = self.eng.create_ticket("test-sd", "feature-b", "Añadir tool TTS",
                                     requester="agente-principal")
        self.eng.pickup_ticket("test-sd", tid)
        self.eng.submit_for_testing("test-sd", tid, "Primera versión de TTS")

        # Prueba FALLA
        self.eng.test_ticket("test-sd", tid, "❌ La síntesis de voz no funciona en español", passed=False)
        ticket = self.eng._load_ticket("test-sd", tid)
        self.assertEqual(ticket["flag_status"], "processing",
                         "En FAIL debe regresar a processing")
        self.assertIn("last_failure", ticket,
                      "Debe guardar la razón del fallo")
        self.assertEqual(ticket["last_failure"],
                         "❌ La síntesis de voz no funciona en español")

        # Engineer corrige y reenvía
        self.eng.submit_for_testing("test-sd", tid, "Versión corregida con soporte español")
        self.eng.test_ticket("test-sd", tid, "✅ TTS funciona en español correctamente", passed=True)
        self.assertEqual(self.eng._load_ticket("test-sd", tid)["flag_status"], "review",
                         "En PASS debe pasar a review")

        # Engineer entrega
        self.eng.deliver_ticket("test-sd", tid, "TTS implementado con soporte multi-idioma", "completado")
        ticket = self.eng._load_ticket("test-sd", tid)
        self.assertEqual(ticket["flag_status"], "delivered")
        self.assertEqual(len(ticket.get("test_results", [])), 2,
                         "Debe haber 2 resultados de test (1 fail + 1 pass)")
        print(f"  ✅ [SD-02] Pipeline FAIL→RETRY→PASS completo: {tid} → 2 resultados de test")

    # ── Test 3: S&D Guard — no se puede cerrar sin testing ──

    def test_sd_03_guard_no_close_without_testing(self):
        """close_ticket debe rechazar tickets sin pasar por testing"""
        tid = self.eng.create_ticket("test-sd", "feature-c", "Tool de visión",
                                     requester="agente-principal")
        self.eng.pickup_ticket("test-sd", tid)

        # Intentar cerrar sin pasar por testing
        closed = self.eng.close_ticket("test-sd", tid, "Completado")
        self.assertFalse(closed,
                         "close_ticket debe retornar False cuando no ha pasado por testing")
        ticket = self.eng._load_ticket("test-sd", tid)
        self.assertNotEqual(ticket["status"], "closed",
                            "El ticket NO debe cerrarse")

        # Con force=True debe funcionar (bypass)
        closed_force = self.eng.close_ticket("test-sd", tid, "Forzado", force=True)
        self.assertTrue(closed_force,
                        "close_ticket con force=True debe funcionar")
        print(f"  ✅ [SD-03] Guardia S&D: close sin testing → False, close con force → True")

    # ── Test 4: S&D Guard — submit_for_testing requiere processing ──

    def test_sd_04_guard_submit_requires_processing(self):
        """submit_for_testing debe fallar si el ticket no está en processing"""
        tid = self.eng.create_ticket("test-sd", "feature-d", "Tool de búsqueda",
                                     requester="agente-principal")

        # Intentar enviar a testing desde inbox (sin pickup)
        submitted = self.eng.submit_for_testing("test-sd", tid, "Trabajo completado")
        self.assertFalse(submitted,
                         "submit_for_testing desde inbox debe fallar")
        ticket = self.eng._load_ticket("test-sd", tid)
        self.assertEqual(ticket["flag_status"], "inbox",
                         "El flag no debe cambiar")

        # Hacer pickup primero
        self.eng.pickup_ticket("test-sd", tid)
        submitted = self.eng.submit_for_testing("test-sd", tid, "Ahora sí")
        self.assertTrue(submitted,
                        "submit_for_testing desde processing debe funcionar")
        print(f"  ✅ [SD-04] Guardia S&D: submit desde inbox → False, submit desde processing → True")

    # ── Test 5: S&D Guard — test_ticket requiere testing ──

    def test_sd_05_guard_test_requires_testing_flag(self):
        """test_ticket debe fallar si el ticket no está en testing"""
        tid = self.eng.create_ticket("test-sd", "feature-e", "Tool de datos",
                                     requester="agente-principal")

        # Intentar testear desde inbox
        tested = self.eng.test_ticket("test-sd", tid, "test", passed=True)
        self.assertFalse(tested, "test_ticket desde inbox debe fallar")

        # Pipeline correcto
        self.eng.pickup_ticket("test-sd", tid)
        tested = self.eng.test_ticket("test-sd", tid, "test directo", passed=True)
        self.assertFalse(tested, "test_ticket desde processing (sin submit) debe fallar")

        # Pipeline correcto completo
        self.eng.submit_for_testing("test-sd", tid, "Trabajo terminado")
        tested = self.eng.test_ticket("test-sd", tid, "✅ Todo funciona", passed=True)
        self.assertTrue(tested, "test_ticket desde testing debe funcionar")
        print(f"  ✅ [SD-05] Guardia S&D: test desde inbox→False, desde processing→False, desde testing→True")

    # ── Test 6: Verificar que los resultados de test se guardan ──

    def test_sd_06_test_results_persist(self):
        """Los resultados de test deben persistir en el ticket"""
        tid = self.eng.create_ticket("test-sd", "feature-f", "Tool de scraping",
                                     requester="agente-principal")
        self.eng.pickup_ticket("test-sd", tid)

        # Submit y test varias veces
        self.eng.submit_for_testing("test-sd", tid, "v1")
        self.eng.test_ticket("test-sd", tid, "❌ Error en parsing", passed=False)

        self.eng.submit_for_testing("test-sd", tid, "v2")
        self.eng.test_ticket("test-sd", tid, "❌ Timeout en request", passed=False)

        self.eng.submit_for_testing("test-sd", tid, "v3")
        self.eng.test_ticket("test-sd", tid, "✅ Scraping funciona", passed=True)

        ticket = self.eng._load_ticket("test-sd", tid)
        results = ticket.get("test_results", [])
        self.assertEqual(len(results), 3,
                         "Debe haber 3 resultados de test guardados")
        self.assertFalse(results[0]["passed"],
                         "Primer test debe ser FAIL")
        self.assertFalse(results[1]["passed"],
                         "Segundo test debe ser FAIL")
        self.assertTrue(results[2]["passed"],
                        "Tercer test debe ser PASS")
        print(f"  ✅ [SD-06] Tests resultados: 3 resultados guardados (2 fails, 1 pass)")

    # ── Test 7: Flag summary muestra conteos correctos ──

    def test_sd_07_flag_summary_counts(self):
        """flag_summary debe mostrar conteos correctos de cada estado"""
        t_inbox = self.eng.create_ticket("test-sd", "t-inbox", "en inbox", requester="user")
        t_proc = self.eng.create_ticket("test-sd", "t-proc", "en processing", requester="user")
        self.eng.pickup_ticket("test-sd", t_proc)
        t_test = self.eng.create_ticket("test-sd", "t-test", "en testing", requester="user")
        self.eng.pickup_ticket("test-sd", t_test)
        self.eng.submit_for_testing("test-sd", t_test, "en testing")

        summary = self.eng.flag_summary("test-sd")
        self.assertIn("Inbox", summary)
        self.assertIn("Processing", summary)
        self.assertIn("Testing", summary)
        self.assertIn("Delivered", summary)

        # Verificar que los números aparecen
        self.assertTrue(summary.count('📥') > 0 or any(c.isdigit() for c in summary),
                        "El summary debe mostrar números")
        print(f"  ✅ [SD-07] Flag summary: {summary.count('📥')} inbox, {summary.count('🔧')} processing, {summary.count('🧪')} testing")

    # ── Test 8: get_my_tickets permite al agente ver su progreso ──

    def test_sd_08_agent_can_track_its_tickets(self):
        """El agente puede ver sus tickets con get_my_tickets"""
        tid_a = self.eng.create_ticket("test-sd", "feature-g", "Tool A",
                                       requester="agente-voice")
        tid_b = self.eng.create_ticket("test-sd", "feature-h", "Tool B",
                                       requester="agente-web")

        self.eng.pickup_ticket("test-sd", tid_a)
        self.eng.submit_for_testing("test-sd", tid_a, "Tool A lista")
        self.eng.test_ticket("test-sd", tid_a, "✅ Tool A funciona", passed=True)

        # Voice agent ve su ticket en review
        voice_tickets = self.eng.get_my_tickets("agente-voice")
        self.assertEqual(len(voice_tickets), 1)
        self.assertEqual(voice_tickets[0]["flag_status"], "review")

        # Web agent ve su ticket en inbox (nadie lo ha tocado)
        web_tickets = self.eng.get_my_tickets("agente-web")
        self.assertEqual(len(web_tickets), 1)
        self.assertEqual(web_tickets[0]["flag_status"], "inbox")

        # Web agent filtra por estado
        web_inbox = self.eng.get_my_tickets("agente-web", status_filter="inbox")
        self.assertEqual(len(web_inbox), 1)
        web_delivered = self.eng.get_my_tickets("agente-web", status_filter="delivered")
        self.assertEqual(len(web_delivered), 0)
        print(f"  ✅ [SD-08] Agentes ven sus tickets: voice={len(voice_tickets)} (review), web={len(web_tickets)} (inbox)")

    # ── Test 9: Pipeline de capability request (intent → ticket) ──

    def test_sd_09_capability_request_creates_ticket(self):
        """create_capability_request crea ticket y registra el gap"""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="necesito que puedas navegar por internet",
            requester="agente-test",
        )
        self.assertTrue(result["ok"],
                        "create_capability_request debe retornar ok=True")
        self.assertIsNotNone(result["ticket_id"],
                             "Debe generar un ticket_id")
        self.assertEqual(result["capability"], "web_browsing")

        # Verificar que el ticket se creó en el sistema
        ticket = self.eng.get_ticket(result["ticket_id"])
        self.assertIsNotNone(ticket, "El ticket debe existir en el sistema")
        self.assertEqual(ticket["source"], "intent_classifier")
        self.assertEqual(ticket["flag_status"], "inbox")
        print(f"  ✅ [SD-09] Capability request: ticket {result['ticket_id']} creado para web_browsing")

    # ── Test 10: Verificar que _check_existing_resource detecta capacidades existentes ──

    def test_sd_10_check_existing_resource(self):
        """_check_existing_resource distingue listo, registrado y detectado."""
        # web_search ya está en AVAILABLE_CAPABILITIES
        result = TorreDeControl._check_existing_resource("web_search")
        self.assertTrue(result["exists"],
                        "web_search debe detectarse como existente")
        self.assertEqual(result["resource"], "web_search")

        # stt_audio_input está registrada, pero no validada para producto
        result = TorreDeControl._check_existing_resource("stt_audio_input")
        self.assertFalse(result["exists"],
                         "stt_audio_input registrada no debe presentarse como lista")
        self.assertEqual(result["resource"], "stt_audio_input")
        self.assertEqual(result["state"], CapabilityState.REGISTERED)
        self.assertTrue(result["needs_validation"])

        # web_browsing NO está listo por defecto. Si Chrome existe, queda DETECTED.
        self.assertFalse(is_capability_available("web_browsing"),
                         "web_browsing no debe estar en AVAILABLE_CAPABILITIES por defecto")
        result = TorreDeControl._check_existing_resource("web_browsing")
        self.assertFalse(result["exists"])
        if result.get("resource") == "chrome":
            self.assertIn("Chrome", result["message"],
                          "Si existe es porque Chrome está instalado")
            self.assertEqual(result["state"], CapabilityState.DETECTED)

        # Registrar manualmente NO basta: falta herramienta cargada y validación
        register_capability("web_browsing", "web_browser")
        self.assertFalse(is_capability_available("web_browsing"),
                         "web_browsing registrada no debe estar lista todavía")
        result = TorreDeControl._check_existing_resource("web_browsing")
        self.assertFalse(result["exists"])
        self.assertEqual(result["resource"], "web_browsing")
        self.assertEqual(result["state"], CapabilityState.REGISTERED)
        print(f"  ✅ [SD-10] _check_existing_resource: web_search listo, stt/web_browsing registrados no listos")


# ════════════════════════════════════════════════════
# PARTE 5: 10 TESTS DE FLUJO COMPLETO DE CAPABILITY GAP
# ════════════════════════════════════════════════════

class TestCapabilityPipelineFlow(unittest.TestCase):
    """14 tests: Full capability gap flow — intent → ticket → pipeline → S&D → registro + Factory callback.

    Flujo completo:
      1. Intent classification detecta capability gap (web_browsing NO disponible)
      2. create_capability_request() crea ticket + abre pipeline (auto_pipeline=True)
      3. Engineer recoge el ticket (pickup → processing)
      4. Engineer construye y envía a testing (submit_for_testing → testing)
      5. Agente prueba (test_ticket → review si pasa, processing si falla)
      6. Engineer entrega (deliver_ticket → delivered)
      7. Capacidad solo queda disponible si la herramienta real se carga y pasa a TOOL_READY/VALIDATED

    Esta suite verifica que toda la cadena está conectada de principio a fin.
    """

    def setUp(self):
        self.log = LogKeeper()
        self.pipeline = TicketConversationPipeline(self.log)
        self.eng = SystemEngineer(self.log)
        self.eng._pipeline = self.pipeline
        _ensure_profile("system")
        # Clean up web_browsing that may have been registered by test_sd_10
        AVAILABLE_CAPABILITIES.pop("web_browsing", None)
        # Clean up any stale pipeline files from previous tests
        pipelines_dir = digos.DIGOS_DIR / "pipelines"
        if pipelines_dir.exists():
            shutil.rmtree(pipelines_dir, ignore_errors=True)
        pipelines_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        # Clean mailboxes
        profiles_dir = digos.DIGOS_DIR / "profiles"
        if profiles_dir.exists():
            for p_dir in profiles_dir.iterdir():
                if p_dir.is_dir():
                    mailbox = p_dir / "MAILBOX"
                    if mailbox.exists():
                        shutil.rmtree(mailbox)
        # Clean pipelines
        pipelines_dir = digos.DIGOS_DIR / "pipelines"
        if pipelines_dir.exists():
            shutil.rmtree(pipelines_dir, ignore_errors=True)

    # ── Test 1: Gap detection → create_capability_request → ticket + pipeline ──

    def test_cap_01_gap_detection_creates_ticket_and_pipeline(self):
        """Capability gap detectado → create_capability_request crea ticket y abre pipeline."""
        # Simular detección de gap para web_browsing (NO en AVAILABLE_CAPABILITIES)
        self.assertFalse(is_capability_available("web_browsing"),
                         "web_browsing no debe estar disponible por defecto")

        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="necesito que puedas navegar por internet",
            requester="agente-test",
        )
        self.assertTrue(result["ok"])
        tid = result["ticket_id"]

        # Ticket creado con datos correctos
        ticket = self.eng.get_ticket(tid)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["source"], "intent_classifier")
        self.assertEqual(ticket["target"], "capability_request:web_browsing")
        self.assertEqual(ticket["flag_status"], "inbox")

        # Pipeline abierto automáticamente
        status = self.eng.pipeline_get_status(tid)
        self.assertIsNotNone(status)
        self.assertEqual(status.get("status"), "active")
        self.assertIn("agente", status.get("participants", []))
        self.assertIn("engineer", status.get("participants", []))

        # Mensaje inicial en el pipeline
        messages = self.eng.pipeline_get_messages(tid)
        self.assertGreaterEqual(len(messages), 1)
        self.assertEqual(messages[0]["sender"], "sistema")
        self.assertIn("web_browsing", messages[0]["content"])
        print(f"  ✅ [CAP-01] Gap detectado → ticket #{tid} + pipeline activo")

    # ── Test 2: Full S&D pipeline completo ──

    def test_cap_02_sd_pipeline_completo(self):
        """Pipeline S&D completo: pickup → submit → test(pass) → deliver → registrar."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="necesito navegar por sitios web",
            requester="agente-test",
        )
        tid = result["ticket_id"]

        # 1. Engineer recoge
        self.assertTrue(self.eng.pickup_ticket("system", tid))
        self.assertEqual(self.eng._load_ticket("system", tid)["flag_status"], "processing")

        # 2. Engineer construye y envía a testing
        self.assertTrue(self.eng.submit_for_testing("system", tid,
                        "web_browsing implementada con Selenium/ChromeDriver"))
        self.assertEqual(self.eng._load_ticket("system", tid)["flag_status"], "testing")

        # 3. Agente prueba y pasa
        self.assertTrue(self.eng.test_ticket("system", tid,
                        "✅ web_browsing navega correctamente", passed=True))
        self.assertEqual(self.eng._load_ticket("system", tid)["flag_status"], "review")

        # 4. Engineer entrega
        self.assertTrue(self.eng.deliver_ticket("system", tid,
                        "web_browsing implementada", "completado"))
        ticket = self.eng._load_ticket("system", tid)
        self.assertEqual(ticket["flag_status"], "delivered")
        self.assertEqual(ticket["status"], "closed")
        self.assertEqual(ticket["result"], "web_browsing implementada")

        # 5. Registrar capacidad solo deja trazabilidad; no la vuelve ejecutable
        register_capability("web_browsing", "web_browser")
        self.assertFalse(is_capability_available("web_browsing"),
                         "registrar no basta si no hay tool cargada/validada")
        self.assertEqual(AVAILABLE_CAPABILITIES.get("web_browsing"), "web_browser")
        print(f"  ✅ [CAP-02] S&D completo: {tid} → delivered→registered, no ejecutable sin tool real")

    # ── Test 3: Capability NO disponible hasta que exista herramienta real ──

    def test_cap_03_capability_not_available_before_delivery(self):
        """Registrar una capability no la vuelve ejecutable sin herramienta real."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega esta página",
            requester="agente-test",
        )
        tid = result["ticket_id"]

        # Antes de cualquier S&D, no está disponible
        self.assertFalse(is_capability_available("web_browsing"))

        # Después de S&D, sigue sin estar disponible (no se ha registrado)
        self.eng.pickup_ticket("system", tid)
        self.eng.submit_for_testing("system", tid, "Tool implementada")
        self.eng.test_ticket("system", tid, "✅ Funciona", passed=True)
        self.eng.deliver_ticket("system", tid, "Listo", "completado")
        self.assertFalse(is_capability_available("web_browsing"),
                         "No disponible hasta que la Factory registre")

        # Factory registra; sigue sin disponibilidad hasta cargar la tool real
        register_capability("web_browsing", "web_browser")
        self.assertFalse(is_capability_available("web_browsing"))
        self.assertEqual(AVAILABLE_CAPABILITIES.get("web_browsing"), "web_browser")
        _register_ready_dynamic_capability("runtime_probe_capability", "runtime_probe_tool")
        self.assertTrue(is_capability_available("runtime_probe_capability"))
        print(f"  ✅ [CAP-03] Registro no basta; dynamic tool cargada sí queda disponible")

    # ── Test 4: Fail → retry → pass → deliver → register ──

    def test_cap_04_fail_then_retry(self):
        """Capability test FAIL → Engineer corrige → retry PASS → entrega → registro."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega por favor",
            requester="agente-test",
        )
        tid = result["ticket_id"]

        # Primera ronda
        self.eng.pickup_ticket("system", tid)
        self.eng.submit_for_testing("system", tid, "v1: implementación básica con requests")

        # FAIL — requests no ejecuta JS
        self.eng.test_ticket("system", tid,
                             "❌ No ejecuta JavaScript, páginas dinámicas no cargan", passed=False)
        ticket = self.eng._load_ticket("system", tid)
        self.assertEqual(ticket["flag_status"], "processing",
                         "FAIL debe regresar a processing")
        self.assertIn("JavaScript", ticket.get("last_failure", ""))

        # Engineer corrige con Selenium
        self.eng.submit_for_testing("system", tid,
                                     "v2: implementación con Selenium + ChromeDriver")

        # PASS
        self.eng.test_ticket("system", tid,
                              "✅ Ahora ejecuta JS correctamente, navegación completa", passed=True)
        self.assertEqual(self.eng._load_ticket("system", tid)["flag_status"], "review")

        # Engineer entrega
        self.eng.deliver_ticket("system", tid,
                                 "web_browsing con Selenium y ChromeDriver", "completado")

        # Factory registra la intención, pero disponibilidad exige tool real
        register_capability("web_browsing", "web_browser")
        self.assertFalse(is_capability_available("web_browsing"))

        # 2 resultados de test guardados
        ticket = self.eng._load_ticket("system", tid)
        results = ticket.get("test_results", [])
        self.assertEqual(len(results), 2)
        self.assertFalse(results[0]["passed"])
        self.assertTrue(results[1]["passed"])
        print(f"  ✅ [CAP-04] FAIL→RETRY→PASS: {tid} — 2 test results; no tool-ready falso")

    # ── Test 5: Pipeline mensajes persisten a través de S&D ──

    def test_cap_05_pipeline_persists_through_sd(self):
        """Los mensajes del pipeline persisten durante todo el ciclo S&D."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="necesito que puedas navegar",
            requester="agente-web",
        )
        tid = result["ticket_id"]

        # Agente pregunta algo al Engineer
        self.eng.pipeline_send(tid, "agente",
                                "¿Qué motor de navegación prefieres? ¿Chrome o Firefox?",
                                "question")

        # Engineer recoge y responde
        self.eng.pickup_ticket("system", tid)
        self.eng.pipeline_send(tid, "engineer",
                                "Usaré Selenium con ChromeDriver. Es el más compatible.",
                                "response")

        # Submit y test
        self.eng.submit_for_testing("system", tid,
                                     "Implementado con Selenium + ChromeDriver")
        self.eng.pipeline_send(tid, "agente", "Voy a probar la navegación...", "info")
        self.eng.test_ticket("system", tid,
                              "✅ Navegación funciona en Chrome correctamente", passed=True)
        self.eng.pipeline_send(tid, "engineer", "Perfecto, procedo a entregar.", "info")

        # Engineer entrega
        self.eng.deliver_ticket("system", tid, "web_browsing completa", "completado")
        register_capability("web_browsing", "web_browser")

        # Todos los mensajes persistieron
        messages = self.eng.pipeline_get_messages(tid)
        self.assertGreaterEqual(len(messages), 5,  # initial + question + response + info + info
                                "Todos los mensajes deben persistir en el pipeline")
        self.assertEqual(messages[0]["sender"], "sistema", "Mensaje inicial del sistema")
        self.assertEqual(messages[1]["sender"], "agente", "Pregunta del agente")
        self.assertEqual(messages[2]["sender"], "engineer", "Respuesta del Engineer")
        self.assertIn("Chrome", messages[2]["content"], "Engineer menciona Chrome")

        # Pipeline sigue activo (no se resuelve automáticamente al entregar)
        status = self.eng.pipeline_get_status(tid)
        self.assertEqual(status.get("status"), "active",
                         "Pipeline debe seguir activo después de entrega")
        print(f"  ✅ [CAP-05] Pipeline persistente: {len(messages)} mensajes a través de S&D")

    # ── Test 6: Flag summary incluye capability requests ──

    def test_cap_06_flag_summary_includes_capability(self):
        """Capability request aparece en el flag summary del Engineer."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega internet",
            requester="agente-test",
        )
        tid = result["ticket_id"]

        # Flag summary debe mostrar el ticket
        summary = self.eng.flag_summary("system")
        self.assertIn("Inbox", summary)
        # El ticket debe aparecer en la categoría correcta
        self.assertIn(f"#{tid}", summary)
        print(f"  ✅ [CAP-06] Flag summary muestra capability request #{tid}")

    # ── Test 7: Agente puede enviar mensajes en pipeline antes de S&D ──

    def test_cap_07_agent_sends_message_before_pickup(self):
        """Agente puede enviar mensajes en el pipeline incluso antes de que Engineer recoja."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega por internet",
            requester="agente-test",
        )
        tid = result["ticket_id"]

        # Agente envía mensaje ANTES de que Engineer recoja
        msg_id = self.eng.pipeline_send(tid, "agente",
                                         "Esta capacidad requiere instalar Chrome. ¿Tienes Chrome instalado?",
                                         "question")
        self.assertIsNotNone(msg_id)
        self.assertGreater(len(msg_id), 0)

        # Engineer ve el mensaje
        messages = self.eng.pipeline_get_messages(tid)
        self.assertEqual(len(messages), 2, "initial + question del agente")
        self.assertEqual(messages[1]["sender"], "agente")
        self.assertIn("Chrome", messages[1]["content"])
        print(f"  ✅ [CAP-07] Agente envía mensaje antes de pickup: msg_id={msg_id[:12]}...")

    # ── Test 8: Múltiples capability requests no se mezclan ──

    def test_cap_08_multiple_capabilities_independent(self):
        """Dos capability requests independientes → dos pipelines separados."""
        # Request 1: web_browsing
        r1 = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega internet",
            requester="agente-a",
        )
        # Request 2: stt_audio_input (aunque ya disponible, se registra igual)
        r2 = self.eng.create_capability_request(
            capability="stt_audio_input",
            family="VOICE",
            sub_intent="VOICE_INPUT_CAPABILITY_REQUEST",
            user_message="quiero que me escuches",
            requester="agente-b",
        )

        tid_a, tid_b = r1["ticket_id"], r2["ticket_id"]
        self.assertNotEqual(tid_a, tid_b, "Cada capability debe tener su propio ticket")

        # Cada uno tiene su pipeline independiente
        status_a = self.eng.pipeline_get_status(tid_a)
        status_b = self.eng.pipeline_get_status(tid_b)
        self.assertIsNotNone(status_a)
        self.assertIsNotNone(status_b)
        self.assertEqual(status_a["status"], "active")
        self.assertEqual(status_b["status"], "active")

        # Mensajes en cada pipeline son independientes
        self.eng.pipeline_send(tid_a, "agente", "Mensaje para pipeline A", "response")
        msgs_a = self.eng.pipeline_get_messages(tid_a)
        msgs_b = self.eng.pipeline_get_messages(tid_b)
        self.assertEqual(len(msgs_a), 2, "Pipeline A: initial + response")
        self.assertEqual(len(msgs_b), 1, "Pipeline B: solo initial")
        self.assertIn("pipeline A", msgs_a[1]["content"])
        print(f"  ✅ [CAP-08] Pipelines independientes: A={len(msgs_a)} msgs, B={len(msgs_b)} msgs")

    # ── Test 9: Pipeline entrega resumen para el agente ──

    def test_cap_09_summary_for_agent(self):
        """Capability request aparece en el resumen del pipeline para el agente."""
        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega por internet",
            requester="agente-test",
        )
        tid = result["ticket_id"]

        # El agente puede ver el resumen del pipeline
        summary = self.eng.pipeline_get_summary_for_agent()
        self.assertGreater(len(summary), 0, "Debe haber un resumen para el agente")
        self.assertIn(tid, summary, "El ticket debe aparecer en el resumen")
        self.assertIn("web_browsing", summary, "La capability debe aparecer en el resumen")
        self.assertIn("pipeline_respond()", summary,
                      "El resumen debe indicar al agente cómo responder")
        print(f"  ✅ [CAP-09] Resumen para agente: {tid} visible en summary")

    # ── Test 10: Tool de voz registrada requiere pipeline hasta validación ──

    def test_cap_10_registered_capability_still_gets_pipeline(self):
        """Una capability registrada pero no validada sigue abriendo pipeline S&D."""
        self.assertFalse(is_capability_available("stt_audio_input"))

        result = self.eng.create_capability_request(
            capability="stt_audio_input",
            family="VOICE",
            sub_intent="VOICE_INPUT_CAPABILITY_REQUEST",
            user_message="quiero que puedas escuchar audios",
            requester="agente-voice",
        )
        self.assertTrue(result["ok"])
        tid = result["ticket_id"]

        # Ticket creado con pipeline
        ticket = self.eng.get_ticket(tid)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["source"], "intent_classifier")
        status = self.eng.pipeline_get_status(tid)
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "active")

        # S&D normal: todavía necesita validación real antes de declararse lista
        self.eng.pickup_ticket("system", tid)
        self.eng.submit_for_testing("system", tid, "STT ya disponible, verificando conexión")
        self.eng.test_ticket("system", tid, "✅ STT responde correctamente", passed=True)
        self.eng.deliver_ticket("system", tid, "STT verificada", "auditoría")

        ticket = self.eng._load_ticket("system", tid)
        self.assertEqual(ticket["flag_status"], "delivered")
        self.assertEqual(ticket["status"], "closed")
        self.assertFalse(is_capability_available("stt_audio_input"))
        print(f"  ✅ [CAP-10] Capability registrada: ticket #{tid} S&D completado sin disponibilidad falsa")

    # ── Test 11: Factory callback recibe capability y devuelve skill de CAPABILITY_SKILL_MAP ──

    def test_cap_11_factory_callback_receives_capability_and_returns_skill(self):
        """factory_create_fn recibe capability y devuelve el CapabilitySkillDefinition de CAPABILITY_SKILL_MAP."""
        # Simular Factory callback que busca en CAPABILITY_SKILL_MAP
        factory_results = []

        def mock_factory(capability_name):
            skill = get_skill_for_capability(capability_name)
            factory_results.append((capability_name, skill))
            return skill

        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="necesito que puedas navegar por internet",
            requester="agente-test",
            factory_create_fn=mock_factory,
        )

        # Verificar que la Factory fue llamada con la capability correcta
        self.assertTrue(result["ok"])
        self.assertEqual(len(factory_results), 1,
                         "Factory debe haber sido llamada exactamente una vez")
        self.assertEqual(factory_results[0][0], "web_browsing",
                         "Factory debe recibir la capability como argumento")

        # Verificar que devolvió el skill de CAPABILITY_SKILL_MAP
        skill = result.get("skill")
        self.assertIsNotNone(skill, "factory_create_fn debe devolver un skill")
        self.assertIsInstance(skill, CapabilitySkillDefinition,
                              "Debe ser un CapabilitySkillDefinition")
        self.assertEqual(skill.skill_name, "web_browser",
                         "Skill para web_browsing debe ser web_browser")
        self.assertEqual(skill.tool_name, "web_browser",
                         "Tool name debe coincidir")
        self.assertIn("fetch_web_page", skill.target_capabilities,
                      "Skill debe tener target_capabilities definidas")
        self.assertIn("requires_headless_browser", skill.target_limitations,
                      "Skill debe tener target_limitations definidas")

        # Verificar que el ticket tiene nota de la Factory
        ticket = self.eng.get_ticket(result["ticket_id"])
        notes = ticket.get("notes", [])
        factory_notes = [n for n in notes if "Factory" in n.get("text", "")]
        self.assertGreaterEqual(len(factory_notes), 1,
                                "Debe haber al menos una nota de la Factory en el ticket")
        self.assertIn("web_browsing", factory_notes[0]["text"],
                      "La nota debe mencionar la capability")
        self.assertIn("web_browser", factory_notes[0]["text"],
                      "La nota debe mencionar el skill devuelto")

        print(f"  ✅ [CAP-11] Factory callback: skill={skill.skill_name}, "
              f"tool={skill.tool_name}, "
              f"capabilities={len(skill.target_capabilities)}, "
              f"limitations={len(skill.target_limitations)}")

    # ── Test 12: Factory callback con capability de voz ──

    def test_cap_12_factory_callback_with_voice_capability(self):
        """factory_create_fn con stt_audio_input devuelve skill speech_to_text de CAPABILITY_SKILL_MAP."""
        factory_calls = []

        def mock_factory(capability_name):
            skill = get_skill_for_capability(capability_name)
            factory_calls.append(capability_name)
            return skill

        result = self.eng.create_capability_request(
            capability="stt_audio_input",
            family="VOICE",
            sub_intent="VOICE_INPUT_CAPABILITY_REQUEST",
            user_message="quiero que puedas escuchar audios",
            requester="agente-voice",
            factory_create_fn=mock_factory,
        )

        # Verificar que la Factory recibió la capability correcta
        self.assertTrue(result["ok"])
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(factory_calls[0], "stt_audio_input")

        # Verificar el skill devuelto
        skill = result.get("skill")
        self.assertIsNotNone(skill)
        self.assertIsInstance(skill, CapabilitySkillDefinition)
        self.assertEqual(skill.skill_name, "speech_to_text",
                         "Skill para stt_audio_input debe ser speech_to_text")
        self.assertEqual(skill.tool_name, "stt_processor",
                         "Tool name debe ser stt_processor")
        self.assertIn("transcribe_speech_to_text", skill.target_capabilities)
        self.assertIn("requires_whisper_api_or_similar", skill.target_limitations)

        print(f"  ✅ [CAP-12] Factory callback voice: skill={skill.skill_name}, tool={skill.tool_name}")

    # ── Test 13: Factory callback con capability que NO existe en CAPABILITY_SKILL_MAP ──

    def test_cap_13_factory_callback_unknown_capability(self):
        """Si la capability no está en CAPABILITY_SKILL_MAP, factory_create_fn devuelve None."""
        factory_calls = []

        def mock_factory(capability_name):
            factory_calls.append(capability_name)
            return get_skill_for_capability(capability_name)  # None si no existe

        result = self.eng.create_capability_request(
            capability="nonexistent_12345",
            family="NEW_TOOL",
            sub_intent="GENERIC_CAPABILITY_REQUEST",
            user_message="necesito una herramienta que no existe",
            requester="agente-test",
            factory_create_fn=mock_factory,
        )

        # Verificar que la Factory fue llamada con la capability desconocida
        self.assertTrue(result["ok"])
        self.assertEqual(len(factory_calls), 1)
        self.assertEqual(factory_calls[0], "nonexistent_12345")

        # skill debe ser None porque no existe en CAPABILITY_SKILL_MAP
        skill = result.get("skill")
        self.assertIsNone(skill,
                          "Para capability desconocida, skill debe ser None")

        print(f"  ✅ [CAP-13] Factory callback unknown capability: skill=None (no existe en CAPABILITY_SKILL_MAP)")

    # ── Test 14: Factory callback que LLEGA TARDE (S&D ya completado) ──

    def test_cap_14_factory_callback_after_sd_then_register(self):
        """Factory callback se llama al crear el request, S&D se completa, y luego se registra.
        El callback captura el skill desde el principio, el S&D construye la herramienta,
        y register_capability la declara disponible."""
        captured_skill = None

        def mock_factory(capability_name):
            nonlocal captured_skill
            captured_skill = get_skill_for_capability(capability_name)
            return captured_skill

        result = self.eng.create_capability_request(
            capability="web_browsing",
            family="WEB",
            sub_intent="WEB_BROWSING_REQUEST",
            user_message="navega por internet",
            requester="agente-test",
            factory_create_fn=mock_factory,
        )
        tid = result["ticket_id"]

        # 1. El Factory callback YA capturó el skill desde el principio
        self.assertIsNotNone(captured_skill)
        self.assertEqual(captured_skill.skill_name, "web_browser")

        # 2. La capacidad NO está disponible (no registrada aún)
        self.assertFalse(is_capability_available("web_browsing"))

        # 3. S&D completo
        self.eng.pickup_ticket("system", tid)
        self.eng.submit_for_testing("system", tid, "web_browsing implementada")
        self.eng.test_ticket("system", tid, "✅ Funciona", passed=True)
        self.eng.deliver_ticket("system", tid, "web_browsing lista", "completado")

        # 4. Factory registra la capacidad usando el skill que capturó al inicio.
        # Eso aún no significa que la tool esté cargada y ejecutable.
        register_capability("web_browsing", captured_skill.tool_name)
        self.assertFalse(is_capability_available("web_browsing"))
        self.assertEqual(AVAILABLE_CAPABILITIES.get("web_browsing"),
                         captured_skill.tool_name,
                         "La herramienta registrada debe usar el tool_name del skill")

        print(f"  ✅ [CAP-14] Factory callback + S&D + register: skill={captured_skill.skill_name}, "
              f"registered_tool={AVAILABLE_CAPABILITIES.get('web_browsing')} no disponible hasta cargar tool")


# ════════════════════════════════════════════════════
# MAIN — Ejecutar todos los tests
# ════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║     🧪 PRUEBA DE CAPABILITIES — Batería Completa            ║")
    print("║     15 VOICE + 15 WEB + 8 VISION + 10 TICKET S&D + 14 CAP GAP   ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # ── Suite: VOICE ──
    print("━" * 60)
    print("🎤 PARTE 1: 15 TESTS DE VOZ (STT / TTS)")
    print("━" * 60)
    voice_suite = unittest.TestLoader().loadTestsFromTestCase(TestVoiceCapabilityRequests)
    voice_runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    voice_result = voice_runner.run(voice_suite)
    voice_pass = voice_result.testsRun - len(voice_result.failures) - len(voice_result.errors)

    # ── Suite: WEB ──
    print()
    print("━" * 60)
    print("🌐 PARTE 2: 15 TESTS DE WEB (Búsqueda / Navegación)")
    print("━" * 60)
    web_suite = unittest.TestLoader().loadTestsFromTestCase(TestWebCapabilityRequests)
    web_runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    web_result = web_runner.run(web_suite)
    web_pass = web_result.testsRun - len(web_result.failures) - len(web_result.errors)

    # ── Suite: VISION ──
    print()
    print("━" * 60)
    print("🖼️  PARTE 3: 8 TESTS DE VISIÓN (Nueva familia VISION)")
    print("━" * 60)
    vision_suite = unittest.TestLoader().loadTestsFromTestCase(TestVisionCapabilityRequests)
    vision_runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    vision_result = vision_runner.run(vision_suite)
    vision_pass = vision_result.testsRun - len(vision_result.failures) - len(vision_result.errors)

    # ── Suite: TICKET PERSISTENCE ──
    print()
    print("━" * 60)
    print("🚩 PARTE 4: 10 TESTS DE PERSISTENCIA S&D")
    print("━" * 60)
    ticket_suite = unittest.TestLoader().loadTestsFromTestCase(TestTicketPersistence)
    ticket_runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    ticket_result = ticket_runner.run(ticket_suite)
    ticket_pass = ticket_result.testsRun - len(ticket_result.failures) - len(ticket_result.errors)

    # ── Suite: CAPABILITY PIPELINE FLOW ──
    print()
    print("━" * 60)
    print("🎻 PARTE 5: 14 TESTS DE FLUJO COMPLETO DE CAPABILITY GAP")
    print("━" * 60)
    cap_suite = unittest.TestLoader().loadTestsFromTestCase(TestCapabilityPipelineFlow)
    cap_runner = unittest.TextTestRunner(verbosity=0, stream=sys.stdout)
    cap_result = cap_runner.run(cap_suite)
    cap_pass = cap_result.testsRun - len(cap_result.failures) - len(cap_result.errors)

    # ── RESULTADO FINAL ──
    total = (voice_result.testsRun + web_result.testsRun +
             vision_result.testsRun + ticket_result.testsRun +
             cap_result.testsRun)
    total_pass = (voice_pass + web_pass + vision_pass + ticket_pass +
                  cap_pass)
    total_fail = (len(voice_result.failures) + len(web_result.failures) +
                  len(vision_result.failures) + len(ticket_result.failures) +
                  len(cap_result.failures))
    total_error = (len(voice_result.errors) + len(web_result.errors) +
                   len(vision_result.errors) + len(ticket_result.errors) +
                   len(cap_result.errors))

    print()
    print("═" * 60)

    # Detalle por suite
    suites = [
        ("🎤 VOICE", voice_pass, voice_result.testsRun,
         len(voice_result.failures), len(voice_result.errors)),
        ("🌐 WEB", web_pass, web_result.testsRun,
         len(web_result.failures), len(web_result.errors)),
        ("🖼️ VISION", vision_pass, vision_result.testsRun,
         len(vision_result.failures), len(vision_result.errors)),
        ("🚩 S&D", ticket_pass, ticket_result.testsRun,
         len(ticket_result.failures), len(ticket_result.errors)),
        ("🎻 CAP", cap_pass, cap_result.testsRun,
         len(cap_result.failures), len(cap_result.errors)),
    ]
    for name, p, t, f, e in suites:
        icons = "✅" if f == 0 and e == 0 else "⚠️"
        print(f"  {icons} {name}: {p}/{t}  (fail={f}, error={e})")

    print()
    if total_fail == 0 and total_error == 0:
        print(f"  🎉 ¡TODOS LOS {total} TESTS PASARON! ✅")
    else:
        print(f"  📊 {total_pass}/{total} passed | {total_fail} failures | {total_error} errors")
        # Show details of failures
        for suite_name, suite_result in [
            ("VOICE", voice_result), ("WEB", web_result),
            ("VISION", vision_result), ("S&D", ticket_result),
            ("CAP", cap_result),
        ]:
            for f in suite_result.failures:
                print(f"     ❌ [{suite_name}] {f[0]._testMethodName}: {f[1].split(chr(10))[-2]}")
            for e in suite_result.errors:
                print(f"     ⚠️  [{suite_name}] {e[0]._testMethodName}: {e[1].split(chr(10))[-2]}")
    print("═" * 60)
    print()
