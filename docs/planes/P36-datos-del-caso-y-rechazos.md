# Plan de la precisión P36 — Rechazos por código y mensaje; adaptadores de los datos del caso

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0044 (precisión P36), D-70; corrida tras P35: 9 de 78 casos distintos sin avance en dos rondas.
- **Rama:** `p36-datos-del-caso-y-rechazos`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `equivalence.message_field`, máscara automática `when: rejected` de las salidas no mensaje, `actual_view` solo usa un mensaje de texto |
| 2 | `correction.setup_tables` y su peso en `files_to_correct` dentro de la convergencia |
| 3 | Regla del diseño guiado: `legacy_message` de texto |
| 4 | Pruebas: `test_equivalence.py` del pack, `test_correction.py`, `test_generation.py`; aceptaciones M4 y M6c |
