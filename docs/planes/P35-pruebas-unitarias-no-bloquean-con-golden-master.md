# Plan de la precisión P35 — Las pruebas unitarias no bloquean antes del golden master

- **Estado:** cerrado (2026-10-07).
- **Fuente:** ADR-0042 (precisión P35), D-69; corrida tras P34: escalación en el paso del servicio por una prueba
  unitaria que esperaba otro argumento.
- **Rama:** `p35-pruebas-unitarias-no-bloquean-con-golden-master`.

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `generation`: `oracle` = generación fiel con golden master; servicio aceptado si compila y las pruebas corren; compilación final igual |
| 2 | `converge`: salida temprana solo si coinciden los casos y pasan las pruebas; la primera petición lleva las pruebas que fallan |
| 3 | Pruebas en `test_fidelity.py`; ADR-0042 (nota P35), D-69 |
