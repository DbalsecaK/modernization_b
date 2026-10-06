# Plan del hito M24 — Generación fiel al programa

- **Estado:** cerrado (2026-10-06).
- **Fuente:** secciones 10.3, 11.1 y 11.3; ADR-0042 y D-61; el prompt de modernización NexTI (behaviour-preserving)
  y los pasos 1–3 de `modernize-transform` del plugin oficial.
- **Rama:** `m24-generacion-fiel-al-programa`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `prompts/behavior-preserving.md` (R01–R12, preservaciones, evidencia, clasificación) y `fidelity.policy_prompt` con la pila de origen y destino |
| 2 | `fidelity.program_text`: el programa del caso de uso numerado, entero o como extracto declarado |
| 3 | Pruebas y servicio con el programa y las obligaciones (solo guiado) |
| 4 | `fidelity.converge`: golden master dentro del bucle de generación con `do_verify_correct` (escalado a la persona); progreso parcial conservado |
| 5 | Registro de hallazgos `generation/findings.json` (incluye `ERROR_MAPPING`), documento de la corrida |
| 6 | Pruebas: `test_fidelity.py` (extracto, prompt, convergencia, escalado, hallazgos), `test_generation.py` (peticiones guiadas vs no guiadas), aceptación M4 y M18 intactas, e2e del web |
| 7 | ADR-0042, D-61; nota en ADR-0041 |

## 2. Cierre

Validado en local con las suites de orquestación, API y web, y con un reintento real desde Generation sobre el
procedimiento de 2 173 líneas que motivó el hito (resultado en el informe de la corrida). Próximos: M25 (Flujo 3
sobre la baseline), M26 (registro común de hallazgos y ambigüedades para los cuatro flujos).
