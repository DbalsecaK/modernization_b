# Plan del hito M6 — COBOL CICS

- **Estado:** en ejecución (2026-09-30). Se avanza de corrido. Al terminar sigue M6b (PR apilada sobre esta rama).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 5 (grafo y 5.2.1 visualización), 8.2 y 8.3 (COBOL
  CICS; CICS + BMS como una familia), 11.3 (veredicto), 20 (M6).
- **Rama:** `m6-cobol-cics`, apilada sobre `m5-bms-pantallas`. Un commit por paso y PR al terminar.
- **Decisiones del aprobador (2026-09-30):**
  - **Referencia:** una aplicación COBOL/CICS ficticia escrita para el repo, que usa los mapas `PAGOSET` de M5.
    Entra al CI. Ningún código de cliente.
  - **Modelos:** hasta **10 USD en total** para las grabaciones de M6, M6b y M6c. Se avisa antes de cada
    grabación.
- **Foco del aprobador:** terminar la aplicación (frontend, backend e integraciones).

## 1. Alcance

| Incluye | No incluye (hitos posteriores) |
|---|---|
| Adaptador COBOL/CICS determinista: formato fijo, `COPY`, `DATA DIVISION` (PIC, COMP-3, OCCURS, REDEFINES, 88), párrafos, `PERFORM`, `CALL`, `EXEC CICS` (LINK, XCTL, RETURN, SEND/RECEIVE MAP, READ/WRITE/REWRITE, SYNCPOINT), definiciones de transacciones (CSD) | COBOL batch con JCL y GnuCOBOL (Ola 2) |
| Inventario, tipos neutrales, clasificación, slicing y datos de un rango (el contrato 8.2 completo) | Ejecución real de CICS |
| Transacción → Programa → Mapa en el grafo (`STARTS`, `CALLS`, `PERFORMS`, `COPIES`, `USES_MAP`, `EXEC_CICS`, `READS`, `WRITES`) | |
| Pipeline de análisis independiente del lenguaje: la fase elige el adaptador por detección | |
| Importación de trazas CICS como golden master; el veredicto no pasa de PARTLY PROVEN si el legacy no corrió | |
| API del grafo (nodos, aristas, huérfanos, impacto, reglas por nodo) con authz y aislamiento | |
| Pestaña Inventario conectada: grafo completo de 5.2.1 (círculos y capas, flujos, foco por regla, filtros, huérfanos, detalle e impacto) | |
| Visor de trazabilidad Legacy \| Regla \| Destino completo para COBOL | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan y ADR-0015 |
| 2 | Aplicación COBOL/CICS ficticia (programas, copybooks, CSD, trazas) y su spec de referencia |
| 3 | `packages/adapters/source/cobol`: parser determinista del subconjunto documentado |
| 4 | Adaptador completo: inventario, tipos, clasificación, slicing, datos; etiquetas y aristas del grafo |
| 5 | Pipeline independiente del lenguaje: selección por detección, resumen neutral, lectura de `.cbl/.cpy/.csd` |
| 6 | Trazas CICS como golden master (runner de trazas) y techo PARTLY PROVEN en la verificación |
| 7 | API del grafo: nodos, aristas, huérfanos, impacto, reglas por nodo |
| 8 | Web: pestaña Inventario con el grafo completo (5.2.1) |
| 9 | Web: visor de trazabilidad Legacy \| Regla \| Destino para COBOL |
| 10 | Aceptación de punta a punta con la aplicación ficticia (grabada, con aviso previo) |
| 11 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Medición contra la spec de referencia CICS (omisiones, alucinaciones, precisión) | Evaluación en la aceptación grabada |
| Veredicto máximo PARTLY PROVEN si no hay ejecución del legacy | Verificación con golden master de trazas; aceptación |
| El inventario tiene Transacción → Programa → Mapa, copybooks y archivos con archivo y línea | Tests del adaptador contra la referencia |
| El grafo responde impacto, huérfanos y reglas por nodo, aislado por tenant | API del grafo, matriz de autorización |
| La pestaña Inventario muestra el grafo real con sus vistas y filtros | e2e con axe |
