# Plan del hito M6 — COBOL CICS

- **Estado:** cerrado (2026-09-30), ver la sección 4. Sigue M6b (PR apilada sobre esta rama).
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

## 4. Cierre de M6 (2026-09-30)

Los criterios de la sección 3 se cumplen con tests automatizados. Corren en CI contra los servicios reales
(Neo4j incluido), los sandboxes Java y web, y la grabación de la corrida real.

| Criterio | Evidencia (tests) | Estado |
|---|---|---|
| Medición contra la spec de referencia CICS | `test_acceptance_m6.py`: recall 0,9 (9 de 10 reglas), sin omisiones P0, precisión 0,53 (el modelo divide las reglas en 17 más finas; 5 errores de precisión) | ✅ medido |
| Veredicto máximo PARTLY PROVEN sin ejecución del legacy | Aceptación: **PARTLY PROVEN**. Tests: 48. Golden master: 14 casos reproducidos. Reglas del alcance: 16 de 16. Canario detectado. Fuente intacta. Entradas frescas no verificadas porque el golden master sale de trazas. `test_verification.py` (techo) y `test_traces.py` | ✅ |
| Transacción → Programa → Mapa, copybooks y archivos con archivo y línea | `test_cobol.py` contra `reference_inventory.json`, escrito a mano; `test_graph.py` (familia CICS en Neo4j) | ✅ |
| Impacto, huérfanos y reglas por nodo, aislado por tenant | `test_graph_api.py`; matriz de autorización (2 rutas nuevas); aislamiento por el alcance de packages/graph | ✅ |
| Pestaña Inventario con el grafo real, vistas y filtros | `e2e/inventory.spec.ts` con axe: flujo recorrido, foco por regla, impacto e ida a Origen ↔ destino | ✅ |

**Aceptación grabada.** Se grabó con `anthropic/claude-sonnet-5.5`. La corrida final tiene 51 llamadas y su
reporte suma 1,88 USD. El gasto real de M6, contando los intentos que destaparon los defectos, fue de 2,95 USD de
los 10 asignados a M6, M6b y M6c. Quedan 7,05 USD.

Las grabaciones destaparon cuatro defectos de la plataforma, corregidos con sus tests:

- La cobertura exigía casos para reglas de programas sin trazas. Ahora hay alcance del golden master: el programa
  caracterizado más lo que llama con LINK o CALL.
- El parseo de Sybase leía cualquier archivo del zip.
- Una traza no tiene código de retorno: el rechazo se compara como "rechazó o no", más su mensaje.
- Los nombres COBOL con guion no coincidían con los del diseño y las trazas.

**Capturas** en `docs/m6/`, generadas por el e2e: la pestaña Inventario con el grafo CICS y un flujo de negocio
recorrido.

**Cambios respecto del plan**

- Los pasos 3 y 4, 5 y 6, y 8 y 9 se hicieron juntos. El visor de trazabilidad ya era independiente del lenguaje:
  el paso 9 quedó en probarlo con COBOL, con una regla citada en dos programas.
- Se agregaron el alcance del golden master (`nexti_orchestration.scope`) y la regla de rechazos de las trazas
  (ADR-0015).
- La pestaña Inventario conecta el componente del prototipo, y el lienzo cambió de rol `img` a `group` porque
  tiene nodos interactivos (axe).

**Limitaciones conocidas**

- El parser cubre el subconjunto de la aplicación ficticia: no incluye COBOL batch con JCL (Ola 2), `EXEC SQL`
  con análisis de tablas, ni `EVALUATE` anidado complejo. Lo que no reconoce lo reporta como problema.
- Las reglas de programas sin trazas (el menú) quedan fuera del veredicto del módulo y así lo dice "lo que no
  prueba". Para verificarlas hace falta exportar sus trazas.
- Los flujos de negocio salen de las transacciones y del orden del código, no de un análisis de personas o
  procesos. No hay descripciones en lenguaje de negocio de los nodos: el agente analista todavía no las escribe.
- El estado de migración del grafo se deriva de reglas, artefactos y veredictos del proyecto, no de cada nodo.
- La precisión de la extracción (0,53) refleja que el modelo divide reglas. La consolidación puede mejorarla en
  un hito de calidad.
