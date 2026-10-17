# Plan — Equivalencia por estado de la base y unidad de trabajo

- **Estado:** propuesto (2026-10-17), pendiente de aprobación.
- **Fuente:** ADR-0055, D-88; doble check externo de `sp_debcred_empresa` (2026-10-14, 30 hallazgos + H1-H9).
- **Regla:** el Java generado de la ejecución 44027f4f **no se corrige a mano**; la plataforma debe generar el código
  correcto y demostrarlo.

## Fases y puntos

| Fase | # | Punto | Qué logra | Costo |
|---|---|---|---|---|
| **A** | 1 | La transacción es negocio P0 en los cuatro adaptadores (`begin/save/commit/rollback tran`, `sp_cerror`; `SYNCPOINT`; `COMMIT/ROLBK`; `TransactionScope`) | Entra en reglas, cobertura y diseño | — |
| A | 2 | El veredicto declara su frontera: PARTLY PROVEN si los llamados no fueron reales o falta un caso por rollback; «Lo que esto no prueba» lo dice | La plataforma deja de afirmar más de lo que midió | — |
| **B** | 5 | Ejecución del legado con tres modos para todo origen; `kind = sybase` con modo cliente (host, base, credenciales en el almacén) y modo local; la configuración pregunta si hay conexión del cliente | Lo que el cliente pide; reaprovecha ADR-0052 | — |
| B | 6 | Rollback visible: las llamadas externas se registran dentro de la transacción (reemplaza P29) | Un rollback borra la llamada, como ocurre de verdad | — |
| B | 7 | Sustitutos transaccionales generados por código desde la firma de cada llamado (tabla propia, código de retorno por caso, participan en la transacción) | Modo local sin fuentes ni base del cliente | — |
| **C** | 8 | Observación = estado final de todas las tablas tocadas (`sp_depends` en cascada + diferencia completa); el comparador juzga estado + salidas + retorno | Lo que detecta el fallo | — |
| C | 9 | Un caso por cada punto de rollback, exigido por código al test engineer; los sustitutos permiten provocar el fallo | Los caminos de error se prueban | — |
| **D** | 3 | Unidad de trabajo en el contrato del adaptador y en el `Design` (inicio, savepoint, rollbacks, commit, con líneas); el validador la exige | El arquitecto puede y debe declararla | — |
| D | 4 | Estrategia de datos obligatoria: misma base con capa anticorrupción o migración; decide driver, nombres calificados y llamadas | Se acaba el híbrido PostgreSQL + procedimientos Sybase | — |
| **E** | 10 | El destino se prueba contra el mismo motor con los mismos programas (reales o sustitutos); adaptadores ejecutados de verdad; convenciones de stub prohibidas en `src/main` | Cierra el ciclo | — |
| **F** | 22 | Reejecutar `sp_debcred_empresa` de punta a punta en modo local y contrastar con los 30 hallazgos | La demostración para el banco | Modelos: estimar y pedir OK |
| **G** | 11 | Análisis de impacto sobre la aplicación destino, además del legado | Alcance del golden master en flujo 3; qué debía probar el tercero en flujo 4 | — |
| G | 12 | Orden de migración por el grafo de llamadas, de las hojas hacia arriba; caracterización en lotes por nivel | Viable con miles de programas | — |
| G | 13 | Contrato completo del adaptador como especificación y pruebas de conformidad que todo adaptador pasa | Agregar un lenguaje es llenar casillas | — |
| **H** | 16 | Flujo 3: línea base de la aplicación actual, impacto sobre el destino, golden master antes/después, cero diferencias fuera del delta; aplicaciones que no nacieron en la plataforma (Java/Spring primero) | El flujo más exigente y más usado | — |
| H | 15 | Flujo 4 sobre el núcleo nuevo | Certificar a terceros con la frontera correcta | — |
| H | 17 | Flujo 2: unidad de trabajo en el diseño y prueba contra base real | — | — |
| **I** | 18 | Manual semántico por motor, ejecutable por código y obligatorio; quirk resuelto = destino se comporta igual; Sybase incorpora los del doble check | Lo que el agente debe reproducir | — |
| I | 19 | Pasar los cuatro adaptadores por el contrato completo y cerrar sus huecos (CICS `SYNCPOINT`, .NET `TransactionScope`, RPG casos por `ROLBK`) | — | — |
| **J** | 20 | Lenguajes por demanda: Sybase completo → Informix 4GL + SPL → .NET Framework 4.x + EF6 → cierre de RPG → paquetes PL/SQL (sin Forms) → Natural, PL/I, VB6, PowerBuilder, Progress; destino .NET Core por eje de versión; pack «misma base existente» | — | — |
| J | 21 | Documento público de cobertura por lenguaje y por pieza del contrato | El cliente lee lo real | — |

Cada fase va en su rama y PR, con ADR o precisión cuando cambie la especificación, y se fusiona con el CI en verde.
Las fases A a E no usan modelos; la F sí.

## Cómo se valida cada fase

Lo dice ADR-0055, sección «Cómo se valida». La prueba de aceptación de todo el plan es la fase F: la misma plataforma,
sobre el mismo SP, genera un Java con unidad de trabajo y adaptadores correctos, lo prueba contra el estado de la base
y su veredicto nombra lo que no pudo probar.
