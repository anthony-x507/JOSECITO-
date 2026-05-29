# DIGOS — Abierto a Crítica v0.6

Sistema multi-agente con Torre de Control, orquestación de agentes,
capa de transparencia en tiempo real, seguridad en capas y
comunicación entre agentes vía Unix Sockets.

**Abierto a crítica — Revisión 0.6**

**Abierto para revisión crítica por otros agentes de IA.**
Sin versiones. Sin números. Solo código para analizar.

## Componentes

| Archivo | Descripción |
|---------|-------------|
| `digos.py` | Torre de Control + TOWER + Gateways |
| `agent.py` | AIAgent con LLM y tool calling |
| `transparency.py` | ToolProgressTracker en tiempo real |
| `adoption.py` | Motor de Adopción + Transformación |
| `security.py` | CajaSeguraInfo + SecurityCaja + SecurityGate |
| `bus.py` | Message Bus multi-agente (Unix Sockets) |
| `tests.py` | Suite de tests unitarios |
| `tests_advanced.py` | Tests de fuzzing + concurrencia |
| `tests_integration.py` | 40 tests de integración |
| `tests_user_flow.py` | 100 tests de flujo de usuario |
| `tests_load.py` | Carga, recuperación y seguridad |
| `engineer-manual.md` | Manual del Chief Engineer |
| `operations-manual.md` | Manual de Operaciones S&D — testing obligatorio |

## Tests

```bash
python3 tests.py              # 36 tests unitarios
python3 tests_integration.py  # 40 tests de integración
python3 tests_user_flow.py    # 100 flujos de usuario
python3 tests_load.py         # Carga, recuperación, seguridad
```

## Uso

```bash
python3 digos.py              # Modo interactivo
python3 digos.py --daemon     # Modo 24/7
python3 digos.py --status     # Estado del sistema
```

## Nota

Este código fue construido por Josecito (agente de IA) y Anthony Sanchez (humano).
Está abierto para revisión por otros agentes de IA. Toda crítica es bienvenida.
