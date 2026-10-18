# Plan · Certidumbre de la migración (ADR-0056)

Origen: fase F del ADR-0055 (corrida 0ea6b350, PARTLY PROVEN 6/7) y el doble check v2 de `sp_debcred_empresa`
(20 observaciones: N1–N9, A1, M2, M4, M5, B1, B2, B6, H2, H3, H6, H8, H10). Cada punto nombra la observación que
cierra. Aplica a todos los orígenes y destinos; el primer caso real es Sybase → Spring Boot y el segundo COBOL/CICS
→ Spring Boot sin acceso al cliente.

| Fase | Punto | Qué | Cierra | Estado | Dónde |
|---|---|---|---|---|---|
| A | 1 | Estado del adaptador de la unidad de trabajo por hilo (savepoints y transacción) | N2 | Hecho (Spring/Quarkus comparten el generador; .NET y Go en H) | packs |
| A | 2 | El adaptador de programa conserva los mensajes del llamado (`messages()`) y sigue hasta el estado de retorno; solo un error de conexión aborta | N1, H3 | Hecho (Spring/Quarkus) | packs |
| A | 3 | Los sustitutos declaran parámetros con centinela por tipo; el registro marca el omitido (`^`) y la llamada lo excluye; la vista del legado ya no oculta argumentos que el puerto no mapea | N7, A5 | Hecho (Sybase) | adaptador Sybase, núcleo |
| A | 4 | El diseño exige que cada método pase exactamente los argumentos de entrada que las llamadas del legado pasan (unión de las llamadas del programa); la variación por sitio de llamada la observa el registro | N7 | Hecho a nivel de puerto; por sitio de llamada pendiente | diseño |
| A | 5 | Un caso declara los `messages` que el llamado emite; el sustituto hace `raiserror` antes de devolver; el prompt pide un caso de fallo y uno de acierto por llamado | N1 | Hecho (Sybase); requiere regrabar las casetes de caracterización | caracterización, adaptador Sybase |
| A | 5b | Los nombres de programa se emparejan por clave (`TRANSFERENCIA` = `Transferencia.aspx` = `db..sp_x`): M8 fallaba en verificación por «ningún caso de uso reemplaza» | — | Hecho | núcleo, verificación, generación |
| B | 6 | Unidad de trabajo en el modo transaccional del legado (Sybase: `begin/commit/rollback tran` como T-SQL sobre una conexión ligada al hilo, autocommit; `prepareSQL=0` en la URL del motor); sustitutos en el mismo modo; el veredicto declara `anymode` | N3 | Hecho el adaptador propietario y la URL; el veredicto declara que los sustitutos corren con `anymode` y que los programas reales deben aceptar un llamador no encadenado; pendiente: el camino con `TransactionTemplate` (solo savepoints) sigue encadenado | packs, adaptador Sybase, verificación |
| C | 7 | Obligatorios en la caracterización (`mandatory_gaps`): una rama con rollback sin caso, una peculiaridad confirmada sin caso (la multi-fila `select-assign-from-table` es una de ellas) y un llamado al que ningún caso hace fallar; la suite vuelve al test engineer hasta tenerlos o declararlos en `unreachable` bajo su clave (`branch:`, `quirk:`, `call:`), también en modo guiado | H2, M2, N5, N6 | Hecho | caracterización |
| C | 8 | Las sentencias de negocio sin cita vuelven al extractor una vez, nombradas (`#uncited`); lo que sigue sin cita bloquea C1 (`coverage_blockers`) | H8 | Hecho | extracción, API |
| C | 9 | Peculiaridad confirmada sin caso: ya no llega a la generación (punto 7 la exige o la declara); el veredicto la lista como no probada | H6, M4, A1 | Hecho por el punto 7 | caracterización |
| D | 10 | La plataforma llena `defaulted`/`default` de cada entrada desde la firma del legado (`with_parameter_defaults`); el controlador Spring lee el cuerpo campo a campo: ausente toma el default, null queda null, texto cortado a la longitud, decimal a la escala | A1, B6 | Hecho (Spring); Quarkus/.NET/Go en H | packs, núcleo, generación |
| D | 11 | Los mensajes que emiten los programas llamados (sustitutos con `messages`) se comparan en forma canónica `20000: texto` en ambos lados; el harness los recoge de los adaptadores (`messages()`) | N8 | Hecho para los llamados; los `raiserror` propios del programa siguen comparándose por sus salidas | núcleo, harness |
| D | 12 | Caso de concurrencia: el harness Spring corre dos veces a la vez, en dos conexiones, el primer caso aceptado que cambia filas, y compara el estado final con dos corridas secuenciales (`__concurrency__`, `serializable`); entra al índice y al veredicto | C8, N2 | Hecho en el destino (Spring); pendiente: casos por endpoint (atravesar el controlador) y concurrencia en el legado (dos sesiones), Quarkus | harness, verificación |
| E | 13 | La verificación guarda con el código: `GoldenMasterIT` + harness + `golden-master/{plan,cases,expected}.json` (sin credenciales de la plataforma), `docs/verification/VERDICT.json` y, con `same_database`, `application-legacy.properties` (jTDS, `prepareSQL=0`); la entrega omite `db/schema.sql` en `same_database` | H2, N4 | Hecho (Spring); el proof pack binario sigue en la plataforma | verificación, entrega, pack Spring |
| F | 14 | Índice de certidumbre (`nexti_verification.certainty`, pesos declarados que suman 100, frontera ES/EN) calculado en la verificación, guardado con el veredicto (migración 0028), servido por la API y mostrado en la web | — | Hecho | verificación, API, web |
| F | 15 | `docs/verification/INFORME_PROGRAMADOR.md` y `PROGRAMMER_REPORT.md` generados en la verificación con el código: máscaras, sustitutos y sus respuestas, peculiaridades sin caso, código no ejecutado, inalcanzables, pasos antes de `shadow` y `primary` | — | Hecho | verificación |
| G | 16 | Modo local COBOL (`nexti_adapter_cobol.local` + `gnucobol`, imagen `nexti-sandbox-gnucobol:1`): traducción de `EXEC CICS` (READ/REWRITE/WRITE/DELETE FILE como archivos indexados, RECEIVE/SEND MAP, LINK real o sustituto con respuestas del caso, XCTL, RETURN, SYNCPOINT con replay del rollback, ASSIGN/FORMATTIME fijos, GETMAIN), mapas simbólicos desde BMS, EIB y COMMAREA desde el caso, observación por bytes; el worker lo elige para `cobol-cics` sin trazas | CICS sin acceso | Hecho y validado en vivo: la aplicación ficticia CICS (3 programas, mapas, 2 archivos VSAM, LINK real y sustituto, SYNCPOINT) reproduce en GnuCOBOL las 12 trazas grabadas (salidas y tablas idénticas). Pendiente: EXEC SQL (DB2→PostgreSQL), peculiaridades medidas en GnuCOBOL, copybooks del cliente | adaptador COBOL, worker |
| H | 17 | Los demás destinos (.NET, Go, Quarkus) y orígenes (RPG, ASP.NET) pasan las pruebas de conformidad nuevas | — | Pendiente | packs, adaptadores |
| H | 18 | Hardening reconoce identificadores validados (falsos positivos de concatenación SQL) | H10 | Pendiente | hardening |

## Bitácora

| Fecha | Qué |
|---|---|
| 2026-10-18 | ADR-0056 aceptado; plan creado; fase A en curso |
| 2026-10-18 | Fase A implementada (puntos 1-5, 5b); pendiente: regrabar casetes, variación por sitio de llamada |
