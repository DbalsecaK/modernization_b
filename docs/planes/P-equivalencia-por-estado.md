# Plan — Equivalencia por estado de la base y unidad de trabajo

- **Estado:** aprobado por el usuario (2026-10-17); en ejecución desde la fase A.
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

## Avance

| Fase | Puntos | Estado | Dónde |
|---|---|---|---|
| A | 1, 2 | Hecho (2026-10-17) | PR #98: unidad de trabajo como negocio en Sybase, CICS y ASPX; séptimo chequeo «Frontera del comportamiento»; las seis grabaciones de aceptación recalculadas a PARTLY PROVEN |
| B | 5, 6 | Hecho (2026-10-17) | `kind = sybase` (Sybase ASE de prueba del cliente: `SybaseConfig`, `LiveAseRunner`, migración 0027, tarjeta web); rollback visible: el golden master Sybase lee al final del caso las llamadas que sobrevivieron (`NXK|`) y separa en `undone` las que el rollback deshizo; los cinco arneses del destino hacen lo mismo; el comparador juzga las que sobrevivieron; grabaciones de `pago_orden` regrabadas en el ASE real |
| B | 7 | Hecho (2026-10-17) | `StubAnswer.effects` (tabla → filas que deja el programa llamado, por la clave de la tabla); el stub Sybase las escribe dentro de la transacción del llamador (`update` si existe, `insert` si no), el diseño las traduce al destino (`UPDATE` por la clave de la entidad + `INSERT` si no cambió nada) y los arneses Spring, Quarkus, .NET y Go las aplican dentro de su transacción (MongoDB: no soportado, falla con su razón); el test engineer las declara cuando el caso depende de ellas |
| C | 8, 9 | Hecho (2026-10-17) | En el Sybase del cliente el golden master incluye el estado final de las tablas que tocan los programas llamados (texto desde `syscomments`, parseado como los insumos, llamadas seguidas en cascada, columnas del catálogo; `GoldenMaster.called_tables`); un punto de rollback sin caso es obligatorio para el test engineer (marcado en la petición de ramas, con una ronda más); una regla que ninguna entrada alcanza se declara en `unreachable` con su razón y el veredicto la lista como no probada; el parser acepta `insert tabla` sin `into` |
| D | 3, 4 | Hecho (2026-10-17) | `UseCase.unit_of_work` (inicio, commit, savepoints, puntos de rollback con su desenlace) y `Design.data_strategy` (`same_database` / `migration`); el validador los exige con las líneas reales del legado (`unit_of_work` del adaptador) y el arquitecto las recibe en la petición; Spring envuelve el caso de uso en `TransactionTemplate` y Quarkus en `@Transactional`; con `same_database` Spring usa jTDS y genera por código los adaptadores de los programas llamados (binding por nombre, return status comprobado, salidas leídas) y el puerto `UnitOfWork` (savepoints); la generación no pide al modelo los adaptadores que el pack ya escribió |
| E | 10 | Hecho (2026-10-17; prueba de punta a punta en verde: el servicio de referencia con `same_database`, adaptadores T-SQL y el adaptador generado de `sp_debito` reproduce los 12 casos contra el ASE, rollbacks incluidos. Hallazgos del motor real: un procedimiento creado en modo *unchained* rechaza a un llamador JDBC en transacción, así que los sustitutos se crean `anymode` y los procedimientos reales del cliente lo necesitan (`sp_procxmode`), precondición de `same_database` para el manual semántico de la fase I; el adaptador generado toma el result set que trae el status porque el programa llamado puede devolver filas) | Con `same_database` y legado Sybase la verificación arranca el ASE de la plataforma en una red privada del run (`SameEngine`: tablas de la suite, sustitutos transaccionales con los efectos del caso, registro de llamadas; sin el programa legado) y el sandbox Java se une a esa red: el arnés corre los casos contra ese motor vía jTDS (adaptadores reales, incluidos los generados de los procedimientos), prepara cada caso con los lotes del golden master, vuelca las tablas y lee de `nx_call` las llamadas que sobrevivieron a la transacción; `behaviour_boundary` pasa a comparar estado y da por generada la unidad de trabajo declarada. Un archivo productivo escrito por el modelo con convenciones de stub (TODO, placeholder, stub, mock, «answered N», hard-coded) vuelve al desarrollador con las líneas antes de compilarse |
| G | 13 | Hecho (2026-10-17) | Contrato completo del adaptador como código (`nexti_core.conformance`: 8 capacidades obligatorias, 5 opcionales con `unit_of_work` y `call_effects` nuevas) y prueba de conformidad sobre los cuatro adaptadores con sus fixtures; los huecos conocidos quedan afirmados en la prueba |
| J | 21 | Hecho (2026-10-17) | `docs/COBERTURA_POR_LENGUAJE.md` generado por la propia prueba de conformidad (falla si el documento no es el que producen los chequeos) |
| G | 11, 12 | Hecho (2026-10-17) | `nexti_core.impact.target_impact`: qué archivos, tablas y fronteras de transacción del destino alcanza un cambio, en cascada por los nombres que declaran (Java, C#, Go), para el alcance del golden master del flujo 3 y lo que el tercero debió probar en el flujo 4; `nexti_core.order.migration_order`: niveles del grafo de llamadas desde las hojas (externos aparte, ciclos juntos) y su texto para los agentes. Pendiente: exponerlos en la API/web y usarlos en los flujos 3 y 4 (fase H) |
| I | 19 (parte) | Hecho (2026-10-17) | `unit_of_work` en COBOL/CICS (`SYNCPOINT` / `SYNCPOINT ROLLBACK`), ASP.NET (`BeginTransaction`/`TransactionScope`, `Commit`/`Complete`, `Rollback`) y RPG (`COMMIT`/`ROLBK` bajo control de compromiso); con ello la caracterización exige un caso por rollback y el diseño declara la unidad de trabajo en todo origen; cobertura por lenguaje regenerada. Pendiente: `call_effects` en los adaptadores y el manual semántico ejecutable (18) |
| F, H, I (18), J (20) | resto | Pendiente | — |

## Cómo se valida cada fase

Lo dice ADR-0055, sección «Cómo se valida». La prueba de aceptación de todo el plan es la fase F: la misma plataforma,
sobre el mismo SP, genera un Java con unidad de trabajo y adaptadores correctos, lo prueba contra el estado de la base
y su veredicto nombra lo que no pudo probar.
