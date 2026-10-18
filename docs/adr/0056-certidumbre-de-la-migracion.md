# ADR-0056 · Certidumbre de la migración: oráculo completo, sustitutos fieles, contrato dentro del oráculo y entrega con evidencia

| Campo | Valor |
|---|---|
| Estado | Aceptado (2026-10-18) |
| Decide | Carlos Ruiz (aprobador), con la evidencia de la fase F del ADR-0055 |
| Sustituye / amplía | Amplía el ADR-0055 (equivalencia por estado y unidad de trabajo) y el ADR-0052 (modos de ejecución del legado) |
| Alcance | Todos los orígenes (Sybase, COBOL/CICS, RPG, ASP.NET y los que entren por el contrato de adaptador) y todos los destinos (Spring Boot, Quarkus, .NET, Go, frontends) |

## Contexto

La fase F del ADR-0055 reejecutó `sp_debcred_empresa` sobre la plataforma corregida y obtuvo **PARTLY PROVEN, 6 de 7
comprobaciones**: 57 de 57 casos del golden master reproducidos contra Sybase ASE, 12 entradas frescas iguales,
canario, fuente intacta. Un doble check independiente del código entregado (`doble-check-v2`) concluyó aun así
«~90-95 %, no 100 %» con 20 observaciones. Leídas contra la evidencia de la corrida, las observaciones caen en cinco
causas del **proceso**, no del Java:

1. **El oráculo no ejercita lo que el motor sabe que es peligroso.** El registro de peculiaridades del motor tenía
   13 entradas confirmadas y en todas decía «casos que la ejecutan: ninguno». 35 sentencias de negocio no tenían
   regla que las citara (entre ellas las de la transacción). Las ramas de histórico (BCE, beneficiario) y los
   `select @v = col` con varias filas no tenían caso. Un caso que no existe no puede fallar.
2. **Los sustitutos de los programas llamados son demasiado dóciles.** Devuelven el estado que dice el caso y nunca
   emiten `raiserror`; declaran todos sus parámetros con `= null`, así que «parámetro omitido» y «NULL explícito»
   son indistinguibles en el registro de llamadas; se crean con `sp_procxmode 'anymode'`, que esconde el modo
   encadenado que los procedimientos reales del cliente pueden rechazar.
3. **Hay comportamiento fuera del alcance del oráculo.** El contrato de entrada (defaults de la firma, longitudes,
   escala), el texto que `sp_cerror` envía al cliente y la concurrencia no se observan: el harness llama al
   servicio en el lenguaje destino, no al endpoint, y lo hace en serie.
4. **Lo que el motor midió no obliga al generador.** Una peculiaridad confirmada sobre una línea del programa
   (`varchar-assign-truncates` en la 282) no tuvo caso ni implementación, y nada lo bloqueó.
5. **La entrega no lleva la evidencia ni es reproducible.** El ZIP contenía código y 85 pruebas con stubs; el
   veredicto y el proof pack se quedaron en la plataforma. Faltaba la configuración del datasource y sobraba un
   `schema.sql` de tablas que ya existen en el legado.

Además, hay clientes que **nunca darán acceso a su entorno** (CICS, Sybase productivo). Para ellos la plataforma debe
decir con un número y una frontera explícita qué observó y qué no, y entregar al programador la lista exacta de lo
que debe validar y completar en el entorno del cliente.

## Decisión

### 1. El oráculo cubre lo que el legado hace, no solo lo que las reglas nombran

La caracterización exige, por programa, **un caso por**: cada peculiaridad del motor detectada en el código del
programa (del registro del adaptador de origen), cada punto de rollback y savepoint, cada rama que asigna una
variable desde una consulta que puede devolver varias filas (`select @v = col`, `FETCH` sin orden), cada programa
llamado (al menos un caso en que falla y uno en que acierta) y cada salida de error del programa. El validador de la
suite las enumera con la línea del fuente y el test engineer no puede cerrar la fase sin ellas; una rama declarada
inalcanzable (`unreachable`) lleva su justificación y el veredicto la lista.

Las **sentencias de negocio sin regla que las cite bloquean** la compuerta C1 (hoy son una advertencia): una
sentencia de negocio no citada es un comportamiento que ninguna regla pide reproducir.

### 2. Los sustitutos reproducen cómo falla y qué recibe el programa llamado

- Un caso puede declarar que un programa llamado **emite mensajes de error** (`raiserror` en Sybase, `ABEND` o
  `RESP` en CICS, `*PSSR`/escape message en RPG) además de su estado de retorno. El adaptador generado del destino
  lee esos mensajes como el legado los lee (en Sybase, como `@@error`, sin abortar) y sigue hasta el estado de
  retorno; solo un error de conexión aborta.
- Los sustitutos declaran sus parámetros con un **centinela** en lugar de `null`, de modo que el registro de
  llamadas distingue «omitido» de «NULL enviado». La comparación del golden master compara también **qué
  parámetros se pasaron**, y el adaptador del destino se genera con exactamente los parámetros de cada `exec` del
  legado, ni uno más ni uno menos.
- La unidad de trabajo generada se ejecuta en el **modo transaccional del legado**: en Sybase, `begin/save/commit/
  rollback tran` como T-SQL sobre la conexión del hilo con autocommit (modo no encadenado), `prepareSQL`
  configurado; los sustitutos se crean en el mismo modo que los procedimientos reales y el veredicto declara si
  alguno requeriría `anymode`.
- El estado por petición del adaptador de la unidad de trabajo (savepoints, transacción) vive **por hilo**.

### 3. El contrato y la concurrencia entran al oráculo

- La capa de entrada del destino (REST, mensaje, pantalla) se genera **desde la firma del legado**: default cuando
  el campo falta en la petición (distinto de null explícito), tipos, longitudes y escala con la semántica del motor
  de origen; el texto de los errores que el legado envía al cliente (catálogo `sp_cerror`, `DFHMSG`, mensajes RPG)
  es una salida más del caso.
- El golden master incluye casos **por endpoint** (atraviesan la capa de entrada) y, para todo programa con unidad
  de trabajo, un caso de **dos peticiones concurrentes** sobre la misma clave, comparando el estado final y los
  bloqueos observados.

### 4. Lo medido obliga

Una peculiaridad confirmada en el motor que afecte a una línea del programa necesita un caso del golden master que
la ejercite; si no lo hay, la convergencia de la generación no puede cerrar y el veredicto lo nombra. Lo mismo para
los defaults de parámetros propios y de los programas llamados.

### 5. La entrega lleva la evidencia y es reproducible

El paquete entregado incluye: el golden master como **prueba de integración ejecutable** del propio proyecto
(los casos como `GoldenMasterIT` o su equivalente en cada destino, contra un motor configurable del cliente), el
veredicto y el proof pack, la configuración del datasource (jTDS con `prepareSQL`, charset), sin DDL de tablas que
ya existen cuando la estrategia es `same_database`, y los dos informes de la sección siguiente.

### 6. Índice de certidumbre e informe para el programador (español e inglés)

Cada veredicto lleva un **índice de certidumbre** calculado por la plataforma, nunca estimado por un modelo, con sus
componentes y su frontera:

| Componente | Medida |
|---|---|
| Casos del golden master que coinciden | n de n |
| Líneas del destino ejecutadas por el golden master | cobertura (jacoco, coverlet, go cover, c8) |
| Sentencias de negocio del legado citadas por una regla | n de n |
| Puntos de rollback y savepoints con caso | n de n |
| Peculiaridades del motor con caso que las ejercite | n de n |
| Programas llamados reales frente a sustitutos | n reales de n |
| «Omitido» frente a «NULL» distinguible en las llamadas | sí / no |
| Caso de concurrencia | sí / no |
| Contrato de entrada ejercitado por el oráculo | sí / no |
| Motor de verificación | el del cliente / el mismo motor en local / otro motor (GnuCOBOL) / solo trazas / no observado |

Los pesos son declarados en la plataforma y el resultado se presenta como un porcentaje con su frontera en una
frase («92 %: lógica y transacción observadas en el mismo motor; sin cubrir peculiaridades, concurrencia ni
contrato»). Un veredicto PROVEN exige el 100 % con el motor del cliente; PARTLY PROVEN lleva siempre el índice.

El **informe para el programador** se genera en la entrega, en español e inglés, a partir de los mismos datos:
cada máscara declarada, cada programa sustituido con lo que respondió en cada caso, cada peculiaridad sin caso, cada
sentencia no citada, cada rama del destino no ejecutada, los parámetros omitidos ambiguos, y las pruebas que debe
hacer en el entorno del cliente antes de `shadow` y antes de `primary`, con la línea del legado y el archivo del
destino.

### 7. Orígenes sin acceso al entorno

Cuando el legado no puede ejecutarse donde la plataforma corre (COBOL/CICS sin trazas), el modo local lo da **el
mismo esquema del ADR-0055 con otro motor**: la lógica real compilada en un motor libre (GnuCOBOL para COBOL), las
tablas en la base del sandbox (DB2 → PostgreSQL por traducción ESQL), los servicios del monitor (CICS) como
sustitutos de la plataforma (mapas BMS desde la especificación de pantalla, `LINK/XCTL` como sustitutos con
registro de llamadas, `SYNCPOINT/ROLLBACK` sobre la base del sandbox), y las peculiaridades medidas en ese motor con
las opciones de compatibilidad del compilador original. El veredicto declara el motor y el índice baja en
consecuencia. Sin ejecución de ninguna clase, la equivalencia es «no observada»: el veredicto lo dice y el índice
lo refleja; nunca PARTLY PROVEN.

## Alternativas consideradas

- **Más prompts y revisión humana del código.** Es lo que produjo el falso PROVEN de la primera corrida: el oráculo
  lo escribe quien genera. Descartado como criterio; se conserva como complemento del informe.
- **Pedir al cliente trazas o acceso siempre.** Imposible en una parte de los clientes. El modo local con otro motor
  y el índice honesto lo sustituyen.
- **Un porcentaje estimado por el modelo.** No es verificable ni repetible. El índice se calcula de los artefactos.

## Consecuencias

- La caracterización cuesta más casos por programa; lo compensan la sesión única por suite y el paralelismo ya
  existentes.
- Las grabaciones de aceptación se re-graban al cambiar los prompts del test engineer y del desarrollador.
- Los packs de destino implementan el contrato de adaptadores de programa (mensajes de error, parámetros exactos,
  modo transaccional) y la prueba de integración del golden master; el contrato de conformidad (ADR-0055) crece y
  `docs/COBERTURA_POR_LENGUAJE.md` lo refleja.
- La entrega cambia de forma: evidencia dentro del paquete e informes bilingües.

## Cómo se valida

- Reejecución de `sp_debcred_empresa`: las 20 observaciones del doble check v2 quedan cubiertas por un caso del
  golden master, por una regla de la plataforma que las impide, o nombradas en el informe para el programador; el
  índice de certidumbre sale calculado y el ZIP contiene `GoldenMasterIT`, proof pack e informes.
- Pruebas de conformidad: todo pack de destino pasa las pruebas de sustitutos con error, parámetros exactos y modo
  transaccional; todo adaptador de origen enumera peculiaridades, rollbacks y ramas multi-fila con línea.
- Un proyecto COBOL/CICS sin trazas llega a un veredicto con motor «GnuCOBOL» y su índice; sin motor, el veredicto
  es «no observado».

## Plan

Las fases, con sus puntos y su estado, están en `docs/planes/P-certidumbre.md`:
A (adaptador generado: savepoints por hilo, mensajes de error de los llamados, parámetros exactos; sustitutos con
centinela y comparación de presencia) → B (unidad de trabajo en el modo del legado) → C (caracterización exigente:
casos por peculiaridad, rollback, rama multi-fila, llamado; sentencias no citadas bloquean; lo medido obliga) →
D (contrato desde la firma, casos por endpoint, concurrencia) → E (entrega con `GoldenMasterIT`, proof pack,
configuración) → F (índice de certidumbre e informes bilingües) → G (modo local COBOL con GnuCOBOL) → H (los demás
destinos y orígenes por el contrato de conformidad).
