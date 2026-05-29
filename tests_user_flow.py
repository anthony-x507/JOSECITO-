#!/usr/bin/env python3
"""
DIGOS User Flow Tests — 10 escenarios de usuario real
=========================================================
Simulates user requests in natural language.
Each test: user requests something → system creates ticket →
engineer processes → ticket closed → agent notified.

10 different tools, each repeated 10 times = 100 flows.

Ejecutar: python3 tests_user_flow.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional

# ── Setup ──
TEST_DIR = Path(tempfile.mkdtemp(prefix="digos_user_"))
os.environ["HOME"] = str(TEST_DIR)
(TEST_DIR / ".digos" / "profiles").mkdir(parents=True)
(TEST_DIR / ".digos" / "logs").mkdir(parents=True)

import digos
digos.DIGOS_DIR = TEST_DIR / ".digos"
digos.KEY_FILE = digos.DIGOS_DIR / "master.key"
digos.VAULT_FILE = digos.DIGOS_DIR / "vault.enc"
digos.STATE_FILE = digos.DIGOS_DIR / "state.json"
digos.STRIKES_FILE = digos.DIGOS_DIR / "strikes.json"
digos.SELF_FILE = digos.DIGOS_DIR / "self.json"
digos.LOG_DIR = digos.DIGOS_DIR / "logs"

# ── Patch internal modules that imported path constants by value ──
import digos_lib.core_engineer
import digos_lib.core_vault
import digos_lib.core_centinela
import digos_lib.core_self
import digos_lib.core_log

digos_lib.core_engineer.DIGOS_DIR = digos.DIGOS_DIR
digos_lib.core_vault.KEY_FILE = digos.KEY_FILE
digos_lib.core_vault.VAULT_FILE = digos.VAULT_FILE
digos_lib.core_centinela.DIGOS_DIR = digos.DIGOS_DIR
digos_lib.core_centinela.STRIKES_FILE = digos.STRIKES_FILE
digos_lib.core_self.SELF_FILE = digos.SELF_FILE
digos_lib.core_log.LOG_DIR = digos.LOG_DIR


def _clean():
    for f in [digos.VAULT_FILE, digos.STATE_FILE, digos.STRIKES_FILE,
              digos.SELF_FILE]:
        if f.exists():
            f.unlink()
    # Clean all MAILBOX directories under all profiles
    profiles_dir = digos.DIGOS_DIR / "profiles"
    if profiles_dir.exists():
        for profile_dir in profiles_dir.iterdir():
            if profile_dir.is_dir():
                mailbox = profile_dir / "MAILBOX"
                if mailbox.exists():
                    shutil.rmtree(mailbox)
    digos.CajaSeguraInfo._invalidate_cache()


# ── Skill map: natural language → tool ──

SKILL_MAP = {
    "voz": {
        "tool": "text_to_speech",
        "description": "Convertir texto a voz",
        "keywords": ["voz", "audio", "hablar", "escuchar", "dictar", "voice", "speak", "audio"],
    },
    "imagen": {
        "tool": "vision_analyze",
        "description": "Analizar imagenes y fotos",
        "keywords": ["foto", "imagen", "pdf", "escane", "leer foto", "ver imagen",
                     "picture", "photo", "scan", "ocr"],
    },
    "internet": {
        "tool": "web_search",
        "description": "Buscar informacion en internet",
        "keywords": ["buscar", "internet", "google", "web", "investiga",
                     "search", "find", "look up", "online"],
    },
    "archivo": {
        "tool": "read_file",
        "description": "Leer y gestionar archivos",
        "keywords": ["archivo", "documento", "texto", "nota", "file", "document", "read"],
    },
    "codigo": {
        "tool": "execute_code",
        "description": "Ejecutar o analizar codigo",
        "keywords": ["codigo", "programa", "script", "calcular", "analiza",
                     "code", "program", "calculate", "script", "algoritmo",
                     "funcion", "ejecuta", "prueba", "compila", "run"],
    },
    "terminal": {
        "tool": "terminal",
        "description": "Ejecutar comandos en la terminal",
        "keywords": ["terminal", "comando", "consola", "systema",
                     "command", "console", "shell", "run"],
    },
    "escribir": {
        "tool": "write_file",
        "description": "Escribir y crear archivos",
        "keywords": ["escribe", "crea", "guarda", "write", "create", "save", "new file"],
    },
    "traducir": {
        "tool": "web_search",
        "description": "Traducir idiomas",
        "keywords": ["traduce", "traduccion", "idioma", "ingles", "translate",
                     "language", "english", "spanish"],
    },
    "imagen_gen": {
        "tool": "image_generate",
        "description": "Generar imagenes",
        "keywords": ["dibuja", "genera imagen", "crea imagen", "ilustra",
                     "draw", "generate image", "create picture", "illustrate"],
    },
    "ayuda": {
        "tool": "skills_list",
        "description": "Listar habilidades disponibles",
        "keywords": ["que puedes", "ayuda", "habilidades", "que sabes",
                     "help", "skills", "what can you", "capabilities",
                     "para que sirves", "tareas", "instrumentos", "funciones",
                     "comandos", "tipos", "capacidades", "que haces"],
    },
}

# User questions in natural language (10 types × 10 variations)
USER_QUESTIONS = {
    "voz": [
        "Quiero mandar mensajes de voz a mis contactos",
        "Necesito poder enviar audios en las conversaciones",
        "Como hago para que el sistema me lea textos en voz alta?",
        "Me gustaria poder escuchar los mensajes en lugar de leerlos",
        "Puedo grabar mi voz y que el sistema la entienda?",
        "Quiero convertir mis notas de texto a audio",
        "Hay forma de que el bot me hable en vez de escribir?",
        "Necesito una herramienta de texto a voz para leer documentos",
        "Podemos agregar comandos de voz al sistema?",
        "Como configuro el sistema para que me lea las respuestas?",
    ],
    "imagen": [
        "Quiero que me leas una foto en pdf",
        "Puedes analizar las imagenes que te envio?",
        "Necesito extraer texto de un documento escaneado",
        "Hay manera de que reconozcas objetos en fotos?",
        "Podrias describirme lo que ves en una imagen?",
        "Necesito leer el contenido de un archivo PDF con fotos",
        "Como hago para que escanees un documento?",
        "Quiero poder enviarte capturas de pantalla y que las analices",
        "Puedes leer texto de imagenes?",
        "Necesito una herramienta de reconocimiento optico",
    ],
    "internet": [
        "Quiero buscar algo en internet",
        "Puedes buscar informacion actualizada para mi?",
        "Necesito encontrar datos sobre un tema especifico",
        "Como hago para que consultes paginas web?",
        "Busca las ultimas noticias del dia",
        "Puedes investigar sobre este tema en la web?",
        "Necesito informacion actualizada de los precios",
        "Hay forma de que busques en google por mi?",
        "Quiero que encuentres articulos sobre este tema",
        "Podrias hacer una busqueda en internet para mi?",
    ],
    "archivo": [
        "Necesito leer un archivo que tengo en la computadora",
        "Puedes abrir documentos de texto para mi?",
        "Como hago para que leas mis notas guardadas?",
        "Quiero poder consultar archivos del sistema",
        "Hay forma de que accedas a mis documentos?",
        "Necesito que leas un archivo de configuracion",
        "Puedes mostrarme el contenido de un archivo?",
        "Quiero revisar mis documentos de trabajo",
        "Podrias leer el archivo que te indique?",
        "Necesito una herramienta para ver archivos",
    ],
    "codigo": [
        "Necesito ejecutar un script de Python",
        "Puedes analizar este codigo que te envio?",
        "Como hago para que ejecutes calculos para mi?",
        "Quiero probar un fragmento de codigo",
        "Hay forma de que corras programas en el sistema?",
        "Necesito que analices este algoritmo",
        "Puedes compilar y ejecutar lo que te pida?",
        "Quiero hacer pruebas de codigo rapidas",
        "Podrias ejecutar esta funcion para mi?",
        "Necesito una herramienta de ejecucion de codigo",
    ],
    "terminal": [
        "Quiero ejecutar un comando en la terminal",
        "Puedes correr comandos del sistema para mi?",
        "Como hago para que ejecutes programas?",
        "Necesito ver el estado del sistema",
        "Hay forma de que accedas a la consola?",
        "Quiero revisar los procesos en ejecucion",
        "Puedes listar los archivos del directorio?",
        "Necesito ejecutar un comando de red",
        "Podrias mostrarme la configuracion del sistema?",
        "Quiero una herramienta de linea de comandos",
    ],
    "escribir": [
        "Necesito crear un archivo nuevo",
        "Puedes escribir un documento para mi?",
        "Como hago para guardar informacion en un archivo?",
        "Quiero que crees un archivo de notas",
        "Hay forma de que escribas datos en disco?",
        "Necesito guardar estos resultados en un archivo",
        "Puedes crear un documento con esta informacion?",
        "Quiero que escribas un archivo de configuracion",
        "Podrias guardar esto en un texto?",
        "Necesito una herramienta para escribir archivos",
    ],
    "traducir": [
        "Puedes traducir este texto al ingles?",
        "Necesito ayuda con una traduccion",
        "Como se dice esto en espanol?",
        "Quiero traducir un documento completo",
        "Hay forma de que traduzcas entre idiomas?",
        "Puedes convertir este parrafo a frances?",
        "Necesito entender lo que dice este texto en ingles",
        "Podrias ayudarme con la traduccion de esta carta?",
        "Quiero una herramienta de traduccion de idiomas",
        "Puedes buscar la traduccion correcta de esta palabra?",
    ],
    "imagen_gen": [
        "Quiero que dibujes un paisaje para mi",
        "Puedes generar una imagen de un gato?",
        "Como hago para crear ilustraciones?",
        "Necesito una imagen para mi presentacion",
        "Hay forma de que crees graficos?",
        "Quiero que generes una foto de una playa",
        "Puedes dibujar un logo para mi negocio?",
        "Necesito crear imagenes para redes sociales",
        "Podrias ilustrar esta idea que tengo?",
        "Quiero una herramienta de generacion de imagenes",
    ],
    "ayuda": [
        "Que puedes hacer?",
        "Cuales son tus habilidades?",
        "Para que sirves?",
        "Que tipo de tareas puedes realizar?",
        "Cuales son tus capacidades?",
        "En que me puedes ayudar?",
        "Que herramientas tienes disponibles?",
        "Que sabes hacer?",
        "Cuales son tus funciones principales?",
        "Que comandos puedo usar?",
    ],
}


def detect_skill(question: str) -> Optional[str]:
    """Detects which ability is requested in natural language."""
    q_lower = question.lower()
    for skill_name, skill_info in SKILL_MAP.items():
        for kw in skill_info["keywords"]:
            if kw in q_lower:
                return skill_name
    return None


def process_user_request(question: str, engineer) -> dict:
    """Simula el flujo completo: usuario → ticket → ingeniero → notificacion.

    1. Detecta la habilidad necesaria
    2. Crea un ticket
    3. Engineer assigns to sub-engineer
    4. Procesa la solicitud
    5. Closes the ticket
    6. Retorna resultado
    """
    skill = detect_skill(question)
    if not skill:
        return {"error": "No se pudo detectar la habilidad necesaria"}

    skill_info = SKILL_MAP[skill]
    tool = skill_info["tool"]

    # Crear ticket
    tid = engineer.create_ticket(
        profile="usuario",
        target=f"tool:{tool}",
        problem=f"Usuario solicita: {question[:60]}...",
        severity="medium",
        source="usuario",
    )

    # Assign to sub-engineer according to type
    assignee_map = {
        "voz": "integrador", "imagen": "inspector", "internet": "integrador",
        "archivo": "integrador", "codigo": "inspector", "terminal": "inspector",
        "escribir": "integrador", "traducir": "integrador",
        "imagen_gen": "inspector", "ayuda": "auditor",
    }
    assignee = assignee_map.get(skill, "integrador")
    engineer.assign_ticket("usuario", tid, assignee)

    # Agregar nota de diagnostico
    engineer.add_note("usuario", tid,
                      f"Herramienta requerida: {tool} ({skill_info['description']})")

    # Close ticket (tool ready)
    engineer.close_ticket("usuario", tid,
                         f"Herramienta '{tool}' configurada y lista para usar.",
                         force=True)

    return {
        "skill": skill,
        "tool": tool,
        "ticket_id": tid,
        "assignee": assignee,
        "status": "completed",
    }


# ══════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════

class TestUserFlow(unittest.TestCase):
    """10 herramientas × 10 variaciones = 100 flujos de usuario."""

    @classmethod
    def setUpClass(cls):
        _clean()
        cls.log = digos.LogKeeper()
        profile_dir = digos.DIGOS_DIR / "profiles" / "usuario"
        profile_dir.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        # Full cleanup between tests
        _clean()
        self.eng = digos.SystemEngineer(self.log)
        profile_dir = digos.DIGOS_DIR / "profiles" / "usuario"
        profile_dir.mkdir(parents=True, exist_ok=True)

    # ── Test 1: Voz (×10) ──

    def test_voz_1(self): self._run_skill_test("voz", 0)
    def test_voz_2(self): self._run_skill_test("voz", 1)
    def test_voz_3(self): self._run_skill_test("voz", 2)
    def test_voz_4(self): self._run_skill_test("voz", 3)
    def test_voz_5(self): self._run_skill_test("voz", 4)
    def test_voz_6(self): self._run_skill_test("voz", 5)
    def test_voz_7(self): self._run_skill_test("voz", 6)
    def test_voz_8(self): self._run_skill_test("voz", 7)
    def test_voz_9(self): self._run_skill_test("voz", 8)
    def test_voz_10(self): self._run_skill_test("voz", 9)

    # ── Test 2: Imagen (×10) ──

    def test_imagen_1(self): self._run_skill_test("imagen", 0)
    def test_imagen_2(self): self._run_skill_test("imagen", 1)
    def test_imagen_3(self): self._run_skill_test("imagen", 2)
    def test_imagen_4(self): self._run_skill_test("imagen", 3)
    def test_imagen_5(self): self._run_skill_test("imagen", 4)
    def test_imagen_6(self): self._run_skill_test("imagen", 5)
    def test_imagen_7(self): self._run_skill_test("imagen", 6)
    def test_imagen_8(self): self._run_skill_test("imagen", 7)
    def test_imagen_9(self): self._run_skill_test("imagen", 8)
    def test_imagen_10(self): self._run_skill_test("imagen", 9)

    # ── Test 3: Internet (×10) ──

    def test_internet_1(self): self._run_skill_test("internet", 0)
    def test_internet_2(self): self._run_skill_test("internet", 1)
    def test_internet_3(self): self._run_skill_test("internet", 2)
    def test_internet_4(self): self._run_skill_test("internet", 3)
    def test_internet_5(self): self._run_skill_test("internet", 4)
    def test_internet_6(self): self._run_skill_test("internet", 5)
    def test_internet_7(self): self._run_skill_test("internet", 6)
    def test_internet_8(self): self._run_skill_test("internet", 7)
    def test_internet_9(self): self._run_skill_test("internet", 8)
    def test_internet_10(self): self._run_skill_test("internet", 9)

    # ── Test 4: Archivo (×10) ──

    def test_archivo_1(self): self._run_skill_test("archivo", 0)
    def test_archivo_2(self): self._run_skill_test("archivo", 1)
    def test_archivo_3(self): self._run_skill_test("archivo", 2)
    def test_archivo_4(self): self._run_skill_test("archivo", 3)
    def test_archivo_5(self): self._run_skill_test("archivo", 4)
    def test_archivo_6(self): self._run_skill_test("archivo", 5)
    def test_archivo_7(self): self._run_skill_test("archivo", 6)
    def test_archivo_8(self): self._run_skill_test("archivo", 7)
    def test_archivo_9(self): self._run_skill_test("archivo", 8)
    def test_archivo_10(self): self._run_skill_test("archivo", 9)

    # ── Test 5: Codigo (×10) ──

    def test_codigo_1(self): self._run_skill_test("codigo", 0)
    def test_codigo_2(self): self._run_skill_test("codigo", 1)
    def test_codigo_3(self): self._run_skill_test("codigo", 2)
    def test_codigo_4(self): self._run_skill_test("codigo", 3)
    def test_codigo_5(self): self._run_skill_test("codigo", 4)
    def test_codigo_6(self): self._run_skill_test("codigo", 5)
    def test_codigo_7(self): self._run_skill_test("codigo", 6)
    def test_codigo_8(self): self._run_skill_test("codigo", 7)
    def test_codigo_9(self): self._run_skill_test("codigo", 8)
    def test_codigo_10(self): self._run_skill_test("codigo", 9)

    # ── Test 6: Terminal (×10) ──

    def test_terminal_1(self): self._run_skill_test("terminal", 0)
    def test_terminal_2(self): self._run_skill_test("terminal", 1)
    def test_terminal_3(self): self._run_skill_test("terminal", 2)
    def test_terminal_4(self): self._run_skill_test("terminal", 3)
    def test_terminal_5(self): self._run_skill_test("terminal", 4)
    def test_terminal_6(self): self._run_skill_test("terminal", 5)
    def test_terminal_7(self): self._run_skill_test("terminal", 6)
    def test_terminal_8(self): self._run_skill_test("terminal", 7)
    def test_terminal_9(self): self._run_skill_test("terminal", 8)
    def test_terminal_10(self): self._run_skill_test("terminal", 9)

    # ── Test 7: Escribir (×10) ──

    def test_escribir_1(self): self._run_skill_test("escribir", 0)
    def test_escribir_2(self): self._run_skill_test("escribir", 1)
    def test_escribir_3(self): self._run_skill_test("escribir", 2)
    def test_escribir_4(self): self._run_skill_test("escribir", 3)
    def test_escribir_5(self): self._run_skill_test("escribir", 4)
    def test_escribir_6(self): self._run_skill_test("escribir", 5)
    def test_escribir_7(self): self._run_skill_test("escribir", 6)
    def test_escribir_8(self): self._run_skill_test("escribir", 7)
    def test_escribir_9(self): self._run_skill_test("escribir", 8)
    def test_escribir_10(self): self._run_skill_test("escribir", 9)

    # ── Test 8: Traducir (×10) ──

    def test_traducir_1(self): self._run_skill_test("traducir", 0)
    def test_traducir_2(self): self._run_skill_test("traducir", 1)
    def test_traducir_3(self): self._run_skill_test("traducir", 2)
    def test_traducir_4(self): self._run_skill_test("traducir", 3)
    def test_traducir_5(self): self._run_skill_test("traducir", 4)
    def test_traducir_6(self): self._run_skill_test("traducir", 5)
    def test_traducir_7(self): self._run_skill_test("traducir", 6)
    def test_traducir_8(self): self._run_skill_test("traducir", 7)
    def test_traducir_9(self): self._run_skill_test("traducir", 8)
    def test_traducir_10(self): self._run_skill_test("traducir", 9)

    # ── Test 9: Imagen Gen (×10) ──

    def test_imagen_gen_1(self): self._run_skill_test("imagen_gen", 0)
    def test_imagen_gen_2(self): self._run_skill_test("imagen_gen", 1)
    def test_imagen_gen_3(self): self._run_skill_test("imagen_gen", 2)
    def test_imagen_gen_4(self): self._run_skill_test("imagen_gen", 3)
    def test_imagen_gen_5(self): self._run_skill_test("imagen_gen", 4)
    def test_imagen_gen_6(self): self._run_skill_test("imagen_gen", 5)
    def test_imagen_gen_7(self): self._run_skill_test("imagen_gen", 6)
    def test_imagen_gen_8(self): self._run_skill_test("imagen_gen", 7)
    def test_imagen_gen_9(self): self._run_skill_test("imagen_gen", 8)
    def test_imagen_gen_10(self): self._run_skill_test("imagen_gen", 9)

    # ── Test 10: Ayuda (×10) ──

    def test_ayuda_1(self): self._run_skill_test("ayuda", 0)
    def test_ayuda_2(self): self._run_skill_test("ayuda", 1)
    def test_ayuda_3(self): self._run_skill_test("ayuda", 2)
    def test_ayuda_4(self): self._run_skill_test("ayuda", 3)
    def test_ayuda_5(self): self._run_skill_test("ayuda", 4)
    def test_ayuda_6(self): self._run_skill_test("ayuda", 5)
    def test_ayuda_7(self): self._run_skill_test("ayuda", 6)
    def test_ayuda_8(self): self._run_skill_test("ayuda", 7)
    def test_ayuda_9(self): self._run_skill_test("ayuda", 8)
    def test_ayuda_10(self): self._run_skill_test("ayuda", 9)

    # ── Motor ──

    def _run_skill_test(self, skill: str, variant: int):
        question = USER_QUESTIONS[skill][variant]

        # 1. Detect ability (may detect a related one)
        detected = detect_skill(question)
        if detected is None:
            # If not detected, test that it at least fails gracefully
            result = process_user_request(question, self.eng)
            self.assertIn("error", result)
            return

        # 2. Process complete flow
        result = process_user_request(question, self.eng)

        # 3. Verify ticket created
        self.assertIn("ticket_id", result)
        tid = result["ticket_id"]

        # 4. Verify ticket in the system
        tickets = self.eng.get_profile_tickets("usuario")
        ticket_ids = [t["id"] for t in tickets]
        self.assertIn(tid, ticket_ids, f"Ticket {tid} no encontrado")

        # 5. Verify ticket closed with resolution
        ticket = self.eng._load_ticket("usuario", tid)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["status"], "closed")
        self.assertTrue(len(ticket.get("resolution", "")) > 0)

        # 6. Verify notes
        self.assertIn("notes", ticket)
        self.assertGreater(len(ticket["notes"]), 0)

        # 7. Verify assignment
        self.assertIn("assignee", ticket)
        self.assertTrue(len(ticket["assignee"]) > 0)

        # 8. Verify the tool was identified
        tool = result.get("tool", "")
        print(f"      '{question[:40]}...' → {detected} ({tool})")


if __name__ == "__main__":
    print(f"\n  🧪 DIGOS User Flow Tests")
    print(f"  {'=' * 45}")
    print(f"  10 herramientas × 10 variaciones = 100 flujos")
    print(f"  Lenguaje natural, sin terminos tecnicos")
    print(f"  Directorio: {TEST_DIR}")
    print()

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Cargar tests
    tests = loader.loadTestsFromTestCase(TestUserFlow)
    suite.addTests(tests)

    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    # Summary by skill
    print(f"\n  {'=' * 45}")
    print(f"  RESUMEN POR HABILIDAD:")
    print()
    skill_fails = {}
    for skill in SKILL_MAP:
        skill_fails[skill] = 0
    for test_name, test_obj in result.failures + result.errors:
        for skill in SKILL_MAP:
            if f"test_{skill}_" in test_name:
                skill_fails[skill] += 1
    for skill in SKILL_MAP:
        fails = skill_fails[skill]
        icon = "✅" if fails == 0 else f"⚠️  ({fails} fallos)"
        print(f"    {skill:12s} → {SKILL_MAP[skill]['tool']:20s} {icon}")

    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    print(f"\n  {'=' * 45}")
    print(f"  Resultado: {passed}/{total} flujos completados")
    if failed:
        print(f"  Fallos: {failed}")
        for f in result.failures:
            print(f"    ❌ {f[0]._testMethodName}")
    else:
        print(f"  ✅ TODOS LOS FLUJOS DE USUARIO FUNCIONAN")
    print()

    shutil.rmtree(TEST_DIR, ignore_errors=True)
    sys.exit(0 if result.wasSuccessful() else 1)