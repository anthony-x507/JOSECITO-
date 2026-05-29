# 📋 MANUAL DE OPERACIONES — DIGOS System
## Protocolo S&D (Send & Deliver) — Testing Obligatorio de Herramientas

> **Versión:** 1.0
> **Integración:** Engineer Manual (`engineer-manual.md`) + Torre de Control
> **Regla de Oro:** *Ninguna herramienta se entrega sin ser testeada antes.*

---

## ÍNDICE

1. [Filosofía S&D](#1-filosofía-sd)
2. [Ciclo de Vida Completo](#2-ciclo-de-vida-completo)
3. [Protocolo de Testing](#3-protocolo-de-testing)
4. [Reglas de Aceptación y Rechazo](#4-reglas-de-aceptación-y-rechazo)
5. [S&D Guards (Protecciones)](#5-sd-guards-protecciones)
6. [Flujo por Tipo de Herramienta](#6-flujo-por-tipo-de-herramienta)
7. [Diagrama de Decisiones](#7-diagrama-de-decisiones)
8. [Responsabilidades](#8-responsabilidades)
9. [Solución de Problemas](#9-solución-de-problemas)
10. [Apéndice: Comandos Rápidos](#10-apéndice-comandos-rápidos)

---

## 1. FILOSOFÍA S&D

### ¿Por qué existe este manual?

Cada herramienta, capability o recurso que el sistema produce debe ser **verificado antes de ser entregado al usuario o a otro agente**. No entregamos trabajo sin validación. Esa es la regla fundamental.

### Principios

| # | Principio | Significado |
|---|-----------|-------------|
| 1 | **Testear antes de entregar** | Nadie recibe una herramienta que no haya sido probada y verificada. |
| 2 | **Si falla, documentar por qué** | Un rechazo no es un fracaso — es información valiosa. El `test_notes` explica exactamente qué falló para que el Engineer pueda corregirlo. |
| 3 | **El agente es quien prueba** | El agente que recibe el trabajo (builder, auditor, reviewer) es responsable de probarlo y reportar el resultado. |
| 4 | **El Engineer es quien entrega** | Solo el System Engineer puede cerrar el ciclo y entregar al creador. |
| 5 | **Sin testing no hay cierre** | La guardia S&D en `close_ticket()` bloquea cualquier cierre que no haya pasado por testing. |

### El ciclo en una frase

```
📥 Pedido → 🔧 Trabajo → 🧪 Testing → (✅ Pass → Entrega) / (❌ Fail → Corrección)
```

---

## 2. CICLO DE VIDA COMPLETO

### Pipeline S&D

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CICLO S&D — SEND & DELIVER                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  📥 INBOX                                                           │
│     Ticket recién creado, esperando al Engineer                     │
│     flag_status = "inbox"                                           │
│           │                                                         │
│           ▼ pickup_ticket()                                          │
│                                                                      │
│  🔧 PROCESSING                                                      │
│     Engineer trabaja en el ticket, asigna a agente de fábrica       │
│     flag_status = "processing"                                      │
│           │                                                         │
│           ▼ submit_for_testing()  ← 🆕 S&D                          │
│                                                                      │
│  🧪 TESTING ════════════════════════════════════════════════════    │
│     ║  El agente PRUEBA el resultado del trabajo                  ║    │
│     ║  flag_status = "testing"                                    ║    │
│     ║  ┌─────────────────────────────────────┐                    ║    │
│     ║  │ ✅ test_ticket(passed=True)         │                    ║    │
│     ║  │   → flag_status = "review"          │                    ║    │
│     ║  └──────────────┬──────────────────────┘                    ║    │
│     ║                 │                                            ║    │
│     ║  ┌──────────────▼──────────────────────┐                    ║    │
│     ║  │ ❌ test_ticket(passed=False)        │                    ║    │
│     ║  │   → flag_status = "processing"      │                    ║    │
│     ║  │   → last_failure = test_notes       │                    ║    │
│     ║  │   → El Engineer corrige y reenvía   │                    ║    │
│     ║  └─────────────────────────────────────┘                    ║    │
│     ╚══════════════════════════════════════════════════════════════╝    │
│           │                                                         │
│           ▼ (si pass)                                               │
│                                                                      │
│  🔍 REVIEW                                                          │
│     Engineer revisa el resultado final                              │
│     flag_status = "review"                                          │
│           │                                                         │
│           ▼ deliver_ticket() / close_ticket()                        │
│                                                                      │
│  ✅ DELIVERED                                                       │
│     Resultado entregado al creador. Flag apagado.                   │
│     flag_status = "delivered"                                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Estados del Ticket

| flag_status | Significado | Quién actúa |
|-------------|-------------|-------------|
| `inbox` | Ticket nuevo, sin procesar | Engineer lo recoge |
| `processing` | Engineer está trabajando / asignó a fábrica | Engineer + agente de fábrica |
| `testing` | 🧪 **El agente está probando el resultado** | Agente que recibe el trabajo |
| `review` | Testing pass — Engineer revisa y entrega | Engineer |
| `delivered` | Entregado al creador. Ciclo completo. | — |

### Ejemplo concreto

```
1. 📥 Usuario pide "web browsing" → ticket #42 creado (flag=inbox)
2. 🔧 Engineer recoge ticket #42 (flag=processing)
3. 🔧 Engineer verifica si Chrome existe → sí, CDP disponible
4. 🔧 Engineer conecta el recurso existente
5. 🧪 Engineer envía a testing: submit_for_testing("system", "42", "Chrome detectado, CDP conectado")
   → flag_status = "testing"
6. 🧪 Agente prueba: abre Chrome, navega a una URL, verifica que funciona
7. 🧪 Agente reporta: test_ticket("system", "42", "Chrome responde, CDP funcional", passed=True)
   → flag_status = "review" ✅
   ─── O, si falla ───
7b. 🧪 Agente reporta: test_ticket("system", "42", "Chrome no responde - error de permisos", passed=False)
    → flag_status = "processing" ❌ (con last_failure documentado)
8. 🔍 Engineer revisa resultado, cierra y entrega: close_ticket() → flag_status = "delivered"
```

---

## 3. PROTOCOLO DE TESTING

### 3.1 ¿Qué se debe testear?

**Toda herramienta, capability o recurso** que pase por el pipeline S&D debe ser testeada antes de su entrega. Esto incluye:

| Tipo | Ejemplos | ¿Qué testear? |
|------|----------|---------------|
| **Capacidades nuevas** | web_browsing, stt, tts | Que la herramienta se ejecute y devuelva resultado esperado |
| **Recursos existentes** | Chrome/CDP, API keys | Que el recurso responda correctamente |
| **Herramientas generadas** | Cualquier tool creada por Factory | Que el código compile, se ejecute, y haga lo que promete |
| **Skills importadas** | Terceros | SecurityCaja scan + ejecución de prueba |
| **Rotaciones de credenciales** | API key, Telegram token | Validar que la nueva credencial funciona |
| **Agentes internos** | Builder, Auditor, Reviewer | Que el agente se registre en el bus y ejecute su misión |

### 3.2 ¿Quién testea?

| Rol | Prueba |
|-----|--------|
| **Agente que recibe el trabajo** | Ejecuta la prueba y llama a `test_ticket()` |
| **System Engineer** | Revisa el resultado de la prueba y decide entrega |
| **Auditor** | Verifica que el testing quede documentado en los tickets |

### 3.3 ¿Cómo testear?

#### Para herramientas de sistema (capabilities, recursos):

```python
# 1. Engineer envía a testing
engineer.submit_for_testing(profile, tid, work_result)
#   → flag_status cambia a "testing"

# 2. Agente prueba y reporta
engineer.test_ticket(profile, tid, test_notes, passed=True)
#   → flag_status cambia a "review" (si pass)
#   → flag_status cambia a "processing" (si fail)
```

#### Para el usuario final (usando Torre de Control):

```
Usuario: "Quiero web browsing"
Sistema:
  1. Engineer recibe el ticket
  2. Engineer verifica recursos existentes
  3. Engineer conecta Chrome/CDP
  4. Engineer: submit_for_testing()
  5. Agente prueba: navega a una URL de prueba
  6. Agente: test_ticket(passed=True)
  7. Engineer: close_ticket() y deliver_ticket()
  8. Usuario: "Aquí tienes web browsing — ya funciona"
```

### 3.4 ¿Qué debe contener test_notes?

Cuando un agente reporta `test_ticket()`, las `test_notes` deben incluir:

```
✅ Si PASS:
  - Qué se probó (comando, URL, herramienta)
  - Resultado obtenido
  - Evidencia de que funciona

❌ Si FAIL:
  - Qué se probó
  - Qué salió mal (error exacto)
  - Por qué cree que falló (diagnóstico)
  - Qué se necesita para corregirlo (instrucciones)
```

**Ejemplo PASS:**
```
test_notes="Chrome lanzado correctamente. Navegó a google.com y devolvió HTTP 200.
CDP conectado, versión 124. Herramienta web_browsing funcional."
```

**Ejemplo FAIL:**
```
test_notes="Chrome no pudo lanzarse. Error: 'Google Chrome.app' no encontrado en
/Applications/. Posible causa: Chrome no está instalado en esta máquina. Se necesita
instalar Chrome o configurar la ruta alternativa."
```

---

## 4. REGLAS DE ACEPTACIÓN Y RECHAZO

### 4.1 Regla: Aceptar (PASS)

Un ticket **PASA testing** cuando:

- [ ] La herramienta/capability se ejecuta sin errores
- [ ] Devuelve el resultado esperado
- [ ] No hay efectos secundarios no deseados
- [ ] La seguridad no se ve comprometida
- [ ] El recurso existe y responde

**Acción:** `test_ticket(profile, tid, test_notes, passed=True)`
→ El ticket sube a `review` y el Engineer lo entrega.

### 4.2 Regla: Rechazar (FAIL)

Un ticket **FALLA testing** cuando:

- [ ] La herramienta no se ejecuta (error de código, dependencia faltante)
- [ ] El recurso no está disponible (Chrome no instalado, API key inválida)
- [ ] El resultado no es el esperado
- [ ] Hay problemas de seguridad
- [ ] El comportamiento es impredecible

**Acción:** `test_ticket(profile, tid, test_notes, passed=False)`
→ El ticket vuelve a `processing` con `last_failure` documentado.
→ El Engineer corrige y reenvía a testing.

### 4.3 Regla: Reintento

- Un ticket puede fallar testing **múltiples veces**
- Cada fallo se documenta en `test_results[]` (historial completo)
- No hay límite de reintentos — pero el Engineer debe asegurarse de que cada intento sea una mejora real
- Si un ticket falla 3+ veces por la misma razón, el Engineer debe escalar al usuario

### 4.4 Regla: Entrega Final

- Solo el **System Engineer** puede cerrar un ticket y entregarlo
- `close_ticket()` requiere `flag_status == "review"` o `"delivered"` (guardia S&D)
- El cierre sin testing solo es posible con `force=True` (reservado para sistema/auditoría)

---

## 5. S&D GUARDS (PROTECCIONES)

### 5.1 Guardia en close_ticket()

```python
def close_ticket(profile, tid, resolution, force=False):
    """
    🧪 S&D GUARD: No se puede cerrar sin pasar por testing
    
    Por defecto, solo tickets con flag_status = 'review' o 'delivered'
    pueden cerrarse (han pasado por testing).
    
    Usa force=True para bypass (sistema, auditoría, etc.).
    """
```

**¿Cuándo usar `force=True`?**
- ✅ Rotación de credenciales (Engineer ya validó la key)
- ✅ Creación de agentes internos (Factory ya creó el agente)
- ✅ Tickets de disclojure (solo auditoría)
- ✅ Resolución por sistema

**¿Cuándo NO usar `force=True`?**
- ❌ Herramientas que van a ser usadas por un agente
- ❌ Capabilities que se entregan al usuario
- ❌ Cualquier trabajo que deba ser verificado antes de entregarse

### 5.2 Guardia en submit_for_testing()

```python
def submit_for_testing(profile, tid, work_result):
    """
    🧪 S&D: SUBMIT FOR TESTING
    
    Precondición: flag_status == 'processing'
    Postcondición: flag_status == 'testing', se guarda work_result
    
    Si el ticket no está en 'processing', la operación falla.
    """
```

### 5.3 Guardia en test_ticket()

```python
def test_ticket(profile, tid, test_notes, passed):
    """
    🧪 S&D: TEST TICKET
    
    Precondición: flag_status == 'testing'
    
    ✅ PASSED:  flag_status → 'review'
    ❌ FAILED:  flag_status → 'processing' (con last_failure)
    
    Si el ticket no está en 'testing', la operación falla.
    """
```

### 5.4 Resumen de Guards

| Operación | Requiere flag_status | Si falla |
|-----------|---------------------|----------|
| `submit_for_testing()` | `processing` | Retorna `False`, log warning |
| `test_ticket()` | `testing` | Retorna `False`, log warning |
| `close_ticket()` | `review` o `delivered` | Retorna `False`, log warning + instrucciones |
| `deliver_ticket()` | cualquiera | Entrega directa (sin guardia) |

---

## 6. FLUJO POR TIPO DE HERRAMIENTA

### 6.1 Capacidad Web (web_browsing, cdp)

```
1. Engineer recibe capability request
2. Engineer: _check_existing_resource("web_browsing")
   ├── ✅ Chrome detectado → conectar recurso existente
   │      └── submit_for_testing() → test_ticket(passed=True) → close_ticket()
   └── ❌ No Chrome → pedir instalación o crear recurso
3. Agente prueba: navegar a una URL, verificar que CDP responde
4. Engineer entrega
```

**Test mínimo:**
```python
# El agente verifica:
# 1. Chrome/Chromium está instalado
# 2. CDP responde en el puerto por defecto (9222)
# 3. Se puede navegar a una URL de prueba
# 4. Se puede extraer contenido de la página
```

### 6.2 Capacidad de Voz (stt, tts)

```
1. Engineer recibe capability request
2. Engineer: _check_existing_resource("stt_audio_input")
   ├── ✅ API key configurada → recurso existe
   │      └── submit_for_testing() → test_ticket(passed=True) → close_ticket()
   └── ❌ No API key → pedir configuración
3. Agente prueba: transcribir un audio de prueba, generar voz de prueba
4. Engineer entrega
```

**Test mínimo:**
```python
# El agente verifica:
# 1. API key con acceso a Whisper/TTS
# 2. Transcripción de un archivo de audio corto
# 3. Generación de voz desde texto
# 4. Los formatos soportados funcionan (mp3, wav, m4a)
```

### 6.3 Herramienta Generada por Factory

```
1. Factory genera código de tool
2. Factory ejecuta Builder → Auditor → Reviewer pipeline
3. Factory devuelve el código generado
4. Engineer: submit_for_testing("system", tid, "Código generado por Factory")
5. Agente prueba:
   a. ¿El código compila/importa sin errores?
   b. ¿Los parámetros son correctos?
   c. ¿La herramienta ejecuta su función principal?
6. Agente: test_ticket(passed=True/False)
7. Engineer: close_ticket() + register_capability()
```

**Test mínimo:**
```python
# El agente verifica:
# 1. El módulo se importa sin errores de sintaxis
# 2. La función principal existe y es llamable
# 3. Los parámetros coinciden con la definición
# 4. La herramienta devuelve un resultado (aunque sea error controlado)
```

### 6.4 Skill Importada de Terceros

```
1. SecurityCaja.scan_skill() → resultado
2. Si 🔴 critico: bloque + explicación (no pasa a testing)
3. Si 🟢/🟡 seguro: Engineer asigna testing
4. submit_for_testing() → test_ticket(passed=True/False)
```

**Test mínimo:**
```python
# El agente verifica:
# 1. SecurityCaja reporta nivel verde o amarillo
# 2. El skill no contiene código malicioso evidente
# 3. Las funciones del skill se importan correctamente
# 4. El skill no altera archivos del sistema
```

### 6.5 Rotación de Credenciales

```
1. Engineer crea ticket de rotación
2. Engineer valida nueva credencial (test de conexión)
3. Si válida → guarda en CajaSeguraInfo
4. Engineer cierra ticket con force=True (ya fue validada)
5. NO necesita testing adicional — Engineer ya la probó
```

---

## 7. DIAGRAMA DE DECISIONES

```
¿Ticket nuevo?
│
├── ¿Es rotación de credencial?
│   └── ✅ Engineer valida + force=True → entregado
│
├── ¿Es auditoría/disclosure?
│   └── ✅ force=True → entregado
│
├── ¿Es creación de agente interno?
│   └── ✅ Factory crea + force=True → registrado
│
└── ¿Es herramienta, capability o recurso?
    │
    ¿Existe el recurso? (_check_existing_resource)
    ├── ✅ Sí → conectar existente
    │         └── submit_for_testing()
    │               └── test_ticket(passed=True) → close_ticket()
    │
    └── ❌ No → crear nuevo
          └── Engineer asigna a fábrica
          └── Fábrica produce resultado
          └── submit_for_testing()
                └── ¿Pasa la prueba?
                      ├── ✅ Sí → test_ticket(passed=True)
                      │         └── close_ticket() → entregado
                      └── ❌ No → test_ticket(passed=False, test_notes="razón")
                            └── Engineer corrige
                            └── submit_for_testing() (reintento)
                                  └── ¿Pasa? → entregado
                                  └── ¿Falla 3+ veces igual? → escalar a usuario
```

---

## 8. RESPONSABILIDADES

### System Engineer

- **Recibe** todos los tickets del inbox
- **Verifica** recursos existentes antes de crear nuevos
- **Asigna** trabajo a agentes de fábrica
- **Envía a testing** con `submit_for_testing()` 
- **Revisa** resultados de testing
- **Decide** si entregar o reenviar a corrección
- **Entrega** resultados finales con `close_ticket()` / `deliver_ticket()`
- **NO puede** cerrar tickets que no hayan pasado por testing (excepto `force=True`)

### Agente de Fábrica (Builder, Auditor, Reviewer)

- **Recibe** tickets asignados por el Engineer
- **Trabaja** en la tarea asignada
- **Prueba** el resultado de su trabajo
- **Reporta** con `test_ticket()`: pasa o falla, siempre con `test_notes`
- **Documenta** por qué falló si es el caso

### Torre de Control

- **Ejecuta** el ciclo del Engineer cada ~300s
- **Monitorea** tickets en testing
- **Verifica** que el pipeline S&D se cumpla
- **Bloquea** operaciones que violen las reglas del sistema

---

## 9. SOLUCIÓN DE PROBLEMAS

### "No puedo cerrar un ticket — close_ticket() devuelve False"

**Causa:** La guardia S&D detecta que `flag_status != "review"`.

**Solución 1 (recomendada):** Completar el ciclo S&D
```python
engineer.submit_for_testing(profile, tid, "trabajo completado")
engineer.test_ticket(profile, tid, "todo ok", passed=True)
engineer.close_ticket(profile, tid, "entregado")
```

**Solución 2 (bypass):** Solo si es sistema/auditoría
```python
engineer.close_ticket(profile, tid, "razón", force=True)
```

### "submit_for_testing() devuelve False"

**Causa:** El ticket no está en `flag_status == "processing"`.

**Verificar:**
```python
ticket = engineer._load_ticket(profile, tid)
print(ticket.get("flag_status"))
# ¿Es "inbox"? → engineer.pickup_ticket(profile, tid) primero
# ¿Es "testing"? → ya está en testing, usa test_ticket()
# ¿Es "review"? → ya pasó testing, usa close_ticket()
```

### "test_ticket() devuelve False"

**Causa:** El ticket no está en `flag_status == "testing"`.

**Verificar:**
```python
ticket = engineer._load_ticket(profile, tid)
print(ticket.get("flag_status"))
# ¿Es "processing"? → usa submit_for_testing() primero
# ¿Es "review"? → ya fue probado, usa close_ticket()
```

### "Un ticket falló testing 3 veces — ¿qué hago?"

1. Revisar `test_results[]` para ver el historial de fallos
2. Identificar el patrón: ¿siempre falla por lo mismo?
3. Si es el mismo error → escalar al usuario
4. Engineer puede crear un ticket de ayuda humana
5. No forzar el cierre con `force=True` — eso saltaría la validación

---

## 10. APÉNDICE: COMANDOS RÁPIDOS

### Ciclo S&D completo

```python
# 1. Engineer recoge ticket
engineer.pickup_ticket(profile, tid)

# 2. Engineer asigna a fábrica (si aplica)
engineer.assign_ticket(profile, tid, "builder")

# 3. Engineer envía a testing
engineer.submit_for_testing(profile, tid, "Resultado del trabajo")

# 4. Agente prueba
engineer.test_ticket(profile, tid, "Prueba exitosa", passed=True)
#   — o —
engineer.test_ticket(profile, tid, "Fallo: ...", passed=False)

# 5. Engineer entrega
engineer.close_ticket(profile, tid, "Entregado exitosamente")
```

### Ver estado de tickets

```python
# Ver pipeline completo
engineer.flag_summary()
# → 📥 Inbox: 2  🔧 Processing: 1  🧪 Testing: 3  🔍 Review: 1  🚀 Delivered: 10

# Ver tickets en testing
engineer.get_open()  # filtrar por flag_status == "testing"

# Ver historial de testing de un ticket
ticket = engineer._load_ticket(profile, tid)
print(ticket.get("test_results", []))
```

### Verificar recurso existente

```python
# Antes de crear cualquier cosa
from digos_lib.core_tower import TorreDeControl
existing = TorreDeControl._check_existing_resource("web_browsing")
if existing.get("exists"):
    print(f"✅ Recurso existe: {existing.get('resource')}")
    # Conectarlo, no crearlo
else:
    print("❌ Recurso no existe — crear nuevo")
```

---

## REGLA DE ORO FINAL

> **Ninguna herramienta se entrega sin ser testeada.**
> **Ningún ticket se cierra sin pasar por testing.**
>
> Si pruebas y funciona → entrégala.
> Si pruebas y falla → documenta por qué, corrígelo, vuelve a probar.
> La calidad del sistema depende de esta disciplina.
>
> — Manual de Operaciones S&D v1.0
