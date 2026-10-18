# Plan · Certidumbre de la migración (ADR-0056)

Origen: fase F del ADR-0055 (corrida 0ea6b350, PARTLY PROVEN 6/7) y el doble check v2 de `sp_debcred_empresa`
(20 observaciones: N1–N9, A1, M2, M4, M5, B1, B2, B6, H2, H3, H6, H8, H10). Cada punto nombra la observación que
cierra. Aplica a todos los orígenes y destinos; el primer caso real es Sybase → Spring Boot y el segundo COBOL/CICS
→ Spring Boot sin acceso al cliente.

| Fase | Punto | Qué | Cierra | Estado | Dónde |
|---|---|---|---|---|---|
| A | 1 | Estado del adaptador de la unidad de trabajo por hilo (savepoints y transacción) | N2 | Pendiente | packs (Spring, Quarkus, .NET, Go) |
| A | 2 | El adaptador de programa lee los mensajes de error del llamado como el legado (`@@error`) y sigue hasta el estado de retorno; solo un error de conexión aborta | N1, H3 | Pendiente | packs |
| A | 3 | Los sustitutos declaran parámetros con centinela; el registro de llamadas distingue omitido de NULL; la comparación compara la presencia de parámetros | N7, A5 | Pendiente | adaptadores de origen (Sybase primero), núcleo de equivalencia |
| A | 4 | El adaptador se genera con exactamente los parámetros de cada `exec` del legado (presencia por llamada, no por puerto) | N7 | Pendiente | diseño (`call_signatures` por llamada), packs |
| A | 5 | Un caso puede declarar que un llamado emite error (`raiserror`); el sustituto lo emite | N1 | Pendiente | caracterización, adaptadores de origen |
| B | 6 | Unidad de trabajo en el modo transaccional del legado (Sybase: T-SQL sobre la conexión del hilo con autocommit; `prepareSQL`); sustitutos en el mismo modo; el veredicto declara `anymode` | N3 | Pendiente | packs, adaptador Sybase, verificación |
| C | 7 | La suite exige un caso por peculiaridad detectada, por rollback/savepoint, por rama multi-fila, por llamado (acierto y fallo) y por salida de error; `unreachable` justificado | H2, M2, N5, N6 | Pendiente | caracterización, adaptadores de origen |
| C | 8 | Sentencias de negocio sin cita bloquean C1 | H8 | Pendiente | reglas, API, web |
| C | 9 | Peculiaridad confirmada sin caso bloquea la convergencia; defaults propios y de llamados también | H6, M4, A1 | Pendiente | generación |
| D | 10 | Capa de entrada generada desde la firma del legado: default si el campo falta, tipos, longitudes y escala | A1, B6 | Pendiente | packs, núcleo |
| D | 11 | Texto de error que el legado envía al cliente como salida del caso (`sp_cerror`, catálogos) | N8 | Pendiente | caracterización, packs |
| D | 12 | Casos por endpoint y caso de concurrencia en todo programa con unidad de trabajo | C8, N2 | Pendiente | caracterización, harness |
| E | 13 | Entrega con `GoldenMasterIT` (o equivalente), veredicto, proof pack, configuración del datasource; sin DDL de tablas existentes en `same_database` | H2, N4 | Pendiente | entrega, packs |
| F | 14 | Índice de certidumbre calculado de los artefactos, con componentes y frontera, en el veredicto y la API | — | Pendiente | verificación, API, web |
| F | 15 | Informe para el programador en español e inglés, generado en la entrega | — | Pendiente | entrega |
| G | 16 | Modo local COBOL: GnuCOBOL + sustitutos CICS + ESQL→PostgreSQL + mapas simbólicos desde BMS; peculiaridades medidas en GnuCOBOL | CICS sin acceso | Pendiente | adaptador COBOL, worker |
| H | 17 | Los demás destinos (.NET, Go, Quarkus) y orígenes (RPG, ASP.NET) pasan las pruebas de conformidad nuevas | — | Pendiente | packs, adaptadores |
| H | 18 | Hardening reconoce identificadores validados (falsos positivos de concatenación SQL) | H10 | Pendiente | hardening |

## Bitácora

| Fecha | Qué |
|---|---|
| 2026-10-18 | ADR-0056 aceptado; plan creado; fase A en curso |
