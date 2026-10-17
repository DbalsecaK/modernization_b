# Cobertura por lenguaje

Generado por `packages/orchestration/tests/test_language_coverage.py` desde las pruebas de conformidad del contrato del adaptador (`nexti_core.conformance`, especificación 8.2, ADR-0055 puntos 13 y 21): ✓ la capacidad pasa sobre el fixture del adaptador, — el adaptador no la implementa (un hueco con nombre), ✗ falla. Un lenguaje solo se anuncia como soportado cuando pasa el contrato completo; hasta entonces este documento dice exactamente qué falta.

| Capacidad | Sybase ASE (T-SQL) | COBOL/CICS | ASP.NET WebForms | RPG/IBM i |
|---|---|---|---|---|
| `detect` (obligatoria): recognises its own technology (confidence above 0.5) | ✓ | ✓ | ✓ | ✓ |
| `inventory` (obligatoria): programs, data and calls with their lines | ✓ | ✓ | ✓ | ✓ |
| `types` (obligatoria): every declared type mapped to a neutral type | ✓ | ✓ | ✓ | ✓ |
| `slices` (obligatoria): units for rule extraction with exact line ranges | ✓ | ✓ | ✓ | ✓ |
| `classification` (obligatoria): statements by label, the transaction as business (ADR-0055) | ✓ | ✓ | ✓ | ✓ |
| `data_of` (obligatoria): tables read and written inside a slice | ✓ | ✓ | ✓ | ✓ |
| `digest` (obligatoria): the inventory in a few lines for the agents | ✓ | ✓ | ✓ | ✓ |
| `engine_quirks` (obligatoria): engine behaviours the code relies on (an empty list when none is catalogued) | ✓ | ✓ | ✓ | ✓ |
| `unit_of_work` (opcional): where a program begins, saves, confirms and undoes its work (ADR-0055) | ✓ | ✓ | ✓ | ✓ |
| `call_effects` (opcional): the tables each external call touches (ADR-0055) | — | — | — | — |
| `screens` (opcional): the screens the programs show | — | ✓ | ✓ | ✓ |
| `coverage_branches` (opcional): the branches an instrumented run can report (ADR-0047) | — | ✓ | ✓ | ✓ |
| `program_quirks` (opcional): quirks and settings per program from the catalog, for traces (R4) | — | — | — | ✓ |

Regenerar: `NEXTI_UPDATE_DOCS=1 uv run pytest packages/orchestration/tests/test_language_coverage.py`.
