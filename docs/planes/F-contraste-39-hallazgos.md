# Fase F · Contraste de la reejecución con los 39 hallazgos del doble check

Proyecto «SP BB test 3» (procedimiento `sp_debcred_empresa`, Sybase ASE), corrida `0ea6b350` del 18 de octubre de 2026
sobre la plataforma corregida en las fases A–I del ADR-0055 (PR #101 a #122). Destino Spring Boot con
`data_strategy = same_database` (driver jTDS, tablas calificadas del legado, procedimientos llamados a través de
adaptadores generados).

## Veredicto

**PARTLY PROVEN**, 6 de 7 comprobaciones en verde.

| Comprobación | Resultado | Evidencia |
|---|---|---|
| tests_ran | passed | 85 pruebas en un build limpio (JUnit) |
| rules_traced | passed | 12 de 12 reglas respaldadas por casos del golden master |
| same_behaviour | passed | 57 de 57 casos del golden master reproducidos contra el motor ASE (estado final de tablas, salidas, estado de retorno y registro de llamadas) |
| fresh_inputs | passed | 12 entradas frescas iguales en legado y destino |
| canary | passed | un cambio deliberado en el destino puso en rojo una prueba |
| source_intact | passed | el legado verificado es el caracterizado (SHA-256) |
| behaviour_boundary | not_checked | los programas llamados (`sp_ndc_ahcc`, `sp_grb_mov_y_frmpgo`, `sp_grb_comision`, `sp_con_confcontable`, `sp_con_comision`, `sp_vi_ndc_automatica`, `sp_graba_tran_servicio`, `sp_eventos`) son sustitutos; su lógica y sus efectos propios solo se verifican con la base de pruebas del banco |

Lo que el veredicto declara como no probado (38 líneas en el proof pack): las 4 máscaras del diseño (`sp_cerror`
como infraestructura, `dt_secuencial` no conservada, `@o_reg_a_proc` nunca asignado, `@o_error` en el camino de
rechazo), los sustitutos, y 770 de 891 líneas ejecutables cubiertas por el golden master (jacoco), con las
regiones no cubiertas nombradas una a una.

Coste de la corrida: 66 invocaciones de modelo, 8,94 USD. La corrida anterior (`fdf69fde`, 17 de octubre) terminó
NOT PROVEN con 38 de 38 casos distintos; las tres causas raíz eran de la plataforma y están cerradas en #120.

## Los 39 hallazgos, uno por uno

Estado: **Cerrado** (la plataforma lo impide o el código generado lo resuelve, con evidencia), **Parcial** (resuelto
en el comportamiento verificado pero con un resto declarado), **Abierto** (no hay caso del golden master que lo
discrimine, o sigue pendiente).

### Transacción e integración (C1–C8)

| Id | Hallazgo | Estado | Evidencia |
|---|---|---|---|
| C1 | Java sin frontera transaccional; autocommit por sentencia | Cerrado | El servicio llama `uow.begin()` donde el legado hace `begin tran` (línea 402), `uow.savepoint("sp_debito_empresa")` y `uow.commit()` donde el legado confirma; `JdbcUnitOfWork` lo implementa sobre el gestor de transacciones del DataSource. El golden master compara el estado final de la base, no llamadas en memoria |
| C2 | Rollback parcial al savepoint cuando falla el débito o la notificación | Cerrado | `uow.rollbackTo(SP)` en el servicio; casos `debit_fails_status_x`, `notify_not_sent_when_debit_fails` reproducidos |
| C3 | `lbl_error` revierte todo (122002, 122003 TRANSWIFT, 122004) | Cerrado | La salida de error `fail()` hace `uow.rollback()` cuando hay transacción; casos `record_movement_fails_122002`, `no_totals_row_122004`, `totals_row_not_in_state_i_122004` |
| C4 | Fallo de `sp_grb_comision`: rollback total y un movimiento X | Cerrado | `uow.rollback()` y registro del movimiento fuera de la transacción; casos `commission_fails_return_nonzero_122003`, `commission_fails_with_error_code` |
| C5 | `@i_savepoint='sp_debito_empresa'` sin savepoint real en la conexión | Cerrado | El savepoint existe en la conexión (`save tran sp_debito_empresa`); el nombre viaja al llamado. El rollback interno del llamado no se verifica (frontera) |
| C6 | Driver PostgreSQL y esquema renombrado | Cerrado | `pom.xml` con jTDS; `schema.sql` y adaptadores con los nombres calificados del legado (`db_biz_pagos..bp_orden`, `db_sat_his..bp_total_orden_his`, …); `same_database` exigido por el destino `sybase` |
| C7 | Adaptadores de llamadas sin binding nombrado ni estado de retorno | Cerrado | Adaptadores generados por la plataforma: `exec @nx_rc = proc @p = ?…`, estado y salidas devueltos como datos; las llamadas se comparan con el registro del motor, canonizadas por el tipo del parámetro |
| C8 | Sin transacción no hay bloqueos; dos peticiones pueden debitar dos veces | Parcial | Consecuencia de C1 (transacción real con bloqueos hasta el commit). No hay prueba de concurrencia en el veredicto |

### Contrato, errores y semántica (A1–A6)

| Id | Hallazgo | Estado | Evidencia |
|---|---|---|---|
| A1 | Defaults de parámetros no migrados | Parcial | El golden master y las entradas frescas aplican los defaults del procedimiento (`parameter_defaults`) y pasan; el contrato REST no declara defaults: un cliente que omita `canal` o `tipo_afec` no recibe `'DIR'` ni `'10'` |
| A2 | `BusinessError` → HTTP 500; `sp_cerror` no invocado; `commit + return @o_error` perdido | Parcial | El estado de retorno del procedimiento es dato: `return 0` con el código en `@o_error` si `@i_aplcobis <> 'S'`, el código como estado si es `'S'` (hallazgo F-002 del registro, verificado en los 57 casos). `sp_cerror` sigue declarado infraestructura: máscara explícita listada en el veredicto |
| A3 | Histórico consultado por `dt_orden_banco`; Java añade `dt_secuencial` y `or_ordenante` | Abierto | `JdbcDetailRepository` sigue uniendo `bp_orden_his` por `or_ordenante` y filtrando por `dt_secuencial`; ningún caso del golden master lo discrimina. Falta un caso de caracterización |
| A4 | Join sobre todos los detalles vs primer detalle con `LIKE` | Abierto | Sin caso que lo discrimine |
| A5 | Parámetros omitidos → `NULL` en lugar del default del llamado | Cerrado | Quirk `param-default-vs-null` medido en el motor; los argumentos de las 57+12 corridas coinciden con el registro del motor |
| A6 | `failCode()` reconoce solo `'answered N'`; `SQLException` real → 500 | Cerrado | Regla de generación: convenciones de stub prohibidas en `src/main`; el servicio no tiene `catch` |

### Semántica T-SQL (M1–M9, B1–B7)

| Id | Hallazgo | Estado | Evidencia |
|---|---|---|---|
| M1 | `patindex` sin guion → `NULL` (no notifica); Java `''` | Cerrado | `indexOf('-')`; sin guion el servicio deja `servSms` nulo y no notifica; quirk `substring-no-match-errors` |
| M2 | `select @v = col` con varias filas asigna la última | Abierto | Sin caso con varias filas en el catálogo |
| M3 | `tb_est_tabla='A'` añadido a todas las consultas | Cerrado | Solo en `ad_notificacion_basica` y `ad_cuentas_bce`, como el legado |
| M4 | `varchar(5)` trunca `@s_term` | Cerrado | `trunc(…, 5)`; quirk `varchar-assign-truncates`; caso `concept_spi_service_from_term` |
| M5 | `varchar(4)` trunca y `=` ignora blancos finales | Cerrado | `rtrim`/`eqTrim` en el servicio; la comparación canoniza los blancos finales |
| M6 | `'COD:'+NULL = 'COD:'` en ASE; Java `null` | Cerrado | `"COD:" + (swiftCode == null ? "" : swiftCode)` |
| M7 | `int = money/money`: Java trunca | Cerrado | Quirk `money-to-int-rounds` medido (2.7 → 3); el servicio redondea; casos `unit_commission_count_exact/_truncated` |
| M8 | `catch(RuntimeException)` traga fallas de infraestructura | Cerrado | Sin `catch` en el servicio |
| M9 | `bp_detalle` y `db_biz_pagos..bp_detalle` como dos tablas | Parcial | Con `same_database` ambos nombres apuntan a las tablas reales, así que el comportamiento es el del legado; el diseño conserva dos entidades porque el procedimiento las nombra distinto |
| B1 | `select @i_comision, @i_valor_ordenado` devuelve un result set | Abierto | El destino no lo emite y el veredicto no compara result sets |
| B2 | `money → varchar(11)` trunca | Cerrado | `money()` con escala 2 y truncado a 11 |
| B3 | `convert(char(2), smallint)` relleno y overflow | Abierto | Sin caso que lo discrimine |
| B4 | `@wRowdbBiz` cuenta solo la consulta actual | Abierto | Sin caso que lo discrimine |
| B5 | `NULL <> 'PAGOPRV'` es desconocido | Cerrado | `service != null && !eqTrim(service, "PAGOPRV")` |
| B6 | Sin normalización de money ni longitudes | Parcial | La comparación canoniza (money a 4 decimales, `char` sin blancos finales); el contrato REST no normaliza |
| B7 | Comparaciones exactas vs blancos finales | Cerrado | `rtrim`/`eqTrim`; canonización en la comparación |

### Herramienta (H1–H9)

| Id | Hallazgo | Estado | Evidencia |
|---|---|---|---|
| H1 | `begin/save/rollback/commit` clasificados como infraestructura | Cerrado | La transacción es negocio P0 (fase A); el diseño declara `unit_of_work` y el validador lo exige con las líneas del fuente |
| H2 | Convergencia contra stubs en memoria; no detecta rollbacks | Cerrado | Golden master por estado de base contra el motor ASE, con sustitutos transaccionales y registro de llamadas que un rollback borra |
| H3 | Adaptadores sin pruebas de integración | Cerrado | Los adaptadores generados corren de verdad contra ASE en las 57+12 ejecuciones |
| H4 | Convenciones de stub en `src/main` | Cerrado | Regla de generación |
| H5 | Sin semántica T-SQL | Cerrado | Manual ejecutable con 21 sondas medidas en ASE 16 (fase I.18) |
| H6 | Defaults fuera del contrato | Parcial | Ver A1 y A5 |
| H7 | Findings que afirman preservación falsa | Cerrado | Registro con 2 hallazgos reales (F-001: prueba alineada con el programa; F-002: estado de retorno conservado), ambos verificados por la convergencia |
| H8 | Sentencias de negocio no citadas sin bloquear | Abierto | `inventory/coverage.json`: 35 de 131 sentencias de negocio sin cita; sigue sin bloquear |
| H9 | PostgreSQL + procedimientos Sybase | Cerrado | Destino `sybase`, `same_database` |

## Resumen

| Estado | Hallazgos |
|---|---|
| Cerrado | 26 (C1–C7, A5, A6, M1, M3–M8, B2, B5, B7, H1–H5, H7, H9) |
| Parcial | 6 (C8, A1, A2, M9, B6, H6) |
| Abierto | 7 (A3, A4, M2, B1, B3, B4, H8) |

Los 10 hallazgos críticos (C1–C8, H1, H2) están cerrados salvo C8, que depende de una prueba de concurrencia que la
plataforma no ejecuta. Los abiertos son todos de la misma naturaleza: comportamientos que ningún caso del golden
master discrimina (A3, A4, M2, B3, B4), un result set que el veredicto no compara (B1) y la cobertura de citas que
no bloquea (H8). El camino para cerrarlos es el mismo que fijó el ADR-0055: casos de caracterización que los
alcancen, no correcciones a mano del Java.

## Lo que cambió en la plataforma durante esta reejecución (18 de octubre)

- #120: el registro de llamadas del motor se canoniza por el tipo del parámetro del sustituto (un `char(4)`
  `C1  ` es el `C1` grabado); el estado de retorno del propio programa es dato (`status_as_data`, salida `return`,
  prompts); el servicio es dueño de la transacción (`UnitOfWork` con `begin/commit/rollback`, controlador y harness
  sin envoltura).
- #120 (segunda parte): con el golden master ya coincidente, el desarrollador corrige solo la prueba unitaria.
- #121: la corrección que iguala todos los casos queda conservada en el diario (sobrevive al reinicio del worker).
- #122: la fase que reanuda tras una espera limpia el texto de la espera en la tarjeta de la corrida.
