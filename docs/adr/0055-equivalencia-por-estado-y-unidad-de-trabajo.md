# ADR-0055 — Equivalencia por estado de la base y unidad de trabajo

- **Estado:** Aceptada · 2026-10-17
- **Secciones:** 6.1 fases 9 a 12 (caracterización, generación, verificación), 8.2 (contrato del adaptador), 11.2 y
  11.3 (veredicto y golden master), 7.1 (configuración del proyecto), 3.1 a 3.4 (los cuatro flujos)
- **Relacionadas:** ADR-0042 (generación fiel), ADR-0044 (base reevaluada), ADR-0046 (fase no disponible), ADR-0047
  (cobertura del legado), ADR-0048 (quirks del motor), ADR-0050 (veredicto con decisiones firmadas), ADR-0052
  (ejecución del legado por proyecto), ADR-0026 (flujo 3), ADR-0025 (flujo 4)
- **Reemplaza en parte:** la decisión P29 de reportar las llamadas externas en el instante en que ocurren

## Contexto

La ejecución 44027f4f migró `sp_debcred_empresa` (Sybase ASE, 2.173 líneas) a Java Spring Boot con veredicto
**PROVEN 6/6**, 76 casos del golden master iguales y 111 pruebas unitarias en verde. Una revisión externa
independiente (doble check, 2026-10-14) encontró 30 diferencias de comportamiento, 8 de ellas críticas:

- El SP trabaja dentro de **una transacción** (`begin tran`, `save tran`, `rollback tran @savepoint`, `rollback tran`
  total, `commit tran`). El Java no tiene ninguna frontera transaccional: cada llamada JDBC confirma por separado. En
  todos los caminos de error el débito que el legado revierte queda confirmado; en el reproceso (122004) hay doble
  débito.
- Los adaptadores JDBC no funcionan: `sp_grb_mov_y_frmpgo` se llamaría sin sus 33 parámetros, `sp_eventos` con los
  parámetros desplazados, ningún `SimpleJdbcCall` captura el *return status* (un débito rechazado se lee como éxito),
  el `pom.xml` trae el driver de PostgreSQL mientras el código invoca procedimientos Sybase.
- Unas veinte semánticas de T-SQL no se reprodujeron: NULL en concatenación, última fila en `select @v = col`,
  truncamiento por tipo, blancos finales, defaults de parámetros y omitido frente a NULL, errores en el llamado que
  no abortan al llamador.
- Convenciones de los stubs de convergencia (`"answered N"`) quedaron en el código productivo.

La revisión acierta: **se migró la lógica de decisión, no el comportamiento.** Las causas están en la plataforma,
confirmadas en su código:

1. **La equivalencia se mide en la frontera equivocada.** El golden master compara la conversación con los puertos
   (qué programas externos se llamaron, con qué argumentos, qué devolvieron) y las tablas propias del programa. Los
   programas llamados son stubs. El destino se prueba contra puertos en memoria. Un débito revertido y un débito
   confirmado se ven idénticos. La decisión P29 de reportar cada llamada en el instante en que ocurre, tomada para
   que un `rollback` no la borrara de la comparación, hizo al rollback invisible.
2. **La transacción es "infraestructura".** `INFRASTRUCTURE_KINDS` en `nexti_adapter_sybase.analysis` incluye
   `begin_tran`, `save_tran`, `commit` y `rollback`; `sp_cerror` está entre las llamadas de infraestructura. No
   entran en reglas, cobertura ni en lo que recibe el arquitecto. Lo mismo ocurre con `SYNCPOINT` en CICS y con
   `COMMIT`/`ROLBK` en RPG (R4 lo detecta como quirk, pero solo avisa).
3. **El diseño no tiene dónde expresar una unidad de trabajo ni una estrategia de datos.** Aunque el arquitecto la
   entienda, no puede declararla y el generador no puede exigirla. El proyecto eligió PostgreSQL como destino y el
   código llama procedimientos Sybase: nadie preguntó si los datos se migran o se quedan.
4. **Los adaptadores nunca se ejecutan.** La sonda de SQL (P32) prepara SQL embebido; no prueba llamadas a
   procedimientos, el binding ni el driver. El hardening es estático.
5. **La convergencia optimizó contra el arnés.** El desarrollador aprendió las convenciones de los stubs; el fixture
   convertía la excepción de vuelta y ocultaba la diferencia del contrato de error.
6. **El veredicto afirmó más de lo que midió.** "PROVEN" significaba "equivalente en la frontera de puertos", pero
   nadie lo leyó así, y «Lo que esto no prueba» no decía que las transacciones ni los adaptadores quedaron fuera.

Todo PROVEN emitido hasta hoy debe leerse como «equivalente en lógica de decisión». El defecto es del núcleo y
alcanza a los cuatro orígenes, a los cuatro destinos y a los cuatro flujos: a Validación Independiente, que certifica
a terceros; y a Agregar a una aplicación existente, donde cada cambio debe demostrar que lo demás no cambió.

Condición del cliente: el Java migrado seguirá llamando a los procedimientos que permanecen en Sybase, y en esta POC
no hay acceso a una base de prueba del banco.

## Decisión

### 1. La equivalencia se mide sobre el estado final de la base

La observación de un caso es el **estado final de todas las tablas que el programa y sus llamados tocaron**, más las
salidas y el código de retorno. Las llamadas a programas externos quedan como información de diagnóstico, no como
criterio de comparación. Las tablas que tocan los llamados se descubren por el motor (`sp_depends` en cascada en
Sybase, su equivalente en cada motor) y, como red de seguridad, por diferencia completa de las bases involucradas.

El rollback se vuelve visible: una llamada a un programa externo se registra **dentro de la transacción**; si el
programa hace rollback, el registro desaparece, como ocurre con cualquier efecto revertido. Esto reemplaza la decisión
P29.

El destino se prueba contra el **mismo motor** con los **mismos programas llamados**, no contra puertos en memoria. Los
adaptadores JDBC se ejecutan de verdad: binding nombrado, captura del return status, bases calificadas. Las
convenciones de stub quedan prohibidas en el código productivo por una regla de la generación.

### 2. La transacción es negocio P0

En todo adaptador de origen, las sentencias que abren, confirman o revierten una unidad de trabajo son negocio de
prioridad P0, nunca infraestructura: `begin/save/commit/rollback tran` y `sp_cerror` en Sybase, `EXEC CICS SYNCPOINT`
en CICS, `COMMIT`/`ROLBK` y los archivos bajo control de compromiso en RPG, `TransactionScope`/`SqlTransaction` en
.NET, `BEGIN/COMMIT/ROLLBACK WORK` en Informix 4GL. Entran en las reglas, en la cobertura y en el texto que recibe el
arquitecto. **Cada punto de rollback es una rama que necesita un caso**; la caracterización lo exige por código al
test engineer.

### 3. El contrato del adaptador gana la unidad de trabajo y los efectos de las llamadas

El contrato de 8.2 se completa con `unit_of_work()` (dónde empieza, dónde confirma, dónde revierte parcial y total) y
con los efectos de cada llamada externa (qué tablas toca, del fuente o del motor). Un **conjunto de pruebas de
conformidad** verifica que todo adaptador cumple el contrato completo: inventario, tipos, clasificación con la
transacción como negocio, unidad de trabajo, llamadas con efectos, quirks del motor (obligatorios, ya no opcionales),
pantallas, los tres modos de ejecución y la observación por estado.

### 4. El diseño declara la unidad de trabajo y la estrategia de datos

El `Design` gana dos campos obligatorios cuando el fuente los exige:

- **Unidad de trabajo** por caso de uso: inicio, savepoint, puntos de rollback parcial, rollback total y commit, cada
  uno citando la línea del fuente. El validador por código la exige cuando el programa tiene transacción, igual que
  hoy exige una entidad por tabla leída.
- **Estrategia de datos**: `misma base existente con capa anticorrupción` (los datos y los programas llamados se quedan
  donde están; el destino usa el driver y los nombres reales calificados) o `migración a la base destino`. Decide el
  driver, los nombres de tablas y cómo se llaman los procedimientos. El pack recibe la unidad de trabajo y **debe**
  generar la transacción; el verificador comprueba que lo hizo.

**Precisión de la fase F (2026-10-18).** El estado de retorno del propio programa es dato cuando el legado lo
entrega junto con sus salidas (devuelve un parámetro de salida, o devuelve 0 con el código del error en uno:
`select @o_error = @w_num_error  return 0`). En ese caso el caso de uso declara una salida con el nombre reservado
`return`, el destino devuelve estado y salidas en cada camino (esas salidas de error no son excepciones) y, como el
legado confirma o revierte antes de devolver, el servicio es dueño de la transacción: el puerto `UnitOfWork` tiene
`begin()`, `commit()` y `rollback()` además de los savepoints, el adaptador REST y el harness no envuelven el caso
de uso, y la transacción empieza donde el legado la empieza (en `sp_debcred_empresa`, después de las consultas de
comisión y configuración contable: una excepción que la deshiciera borraría llamadas que en el legado sobreviven).
Un programa que falla con estado distinto de cero y sin salidas sigue siendo una excepción de negocio. La
comparación canoniza los argumentos del registro de llamadas del motor con el tipo del parámetro del sustituto
(un `char(4)` registrado como `C1  ` es el `C1` que grabó la caracterización).

### 5. La ejecución del legado tiene tres modos para todo origen

La configuración «Ejecución del legado» (ADR-0052) se extiende a cada origen con `kind` propio: `sybase`, `cics`,
`ibmi`, `dotnet`, `informix`. Para cada uno, tres modos con su veredicto máximo:

| Modo | Qué corre | Veredicto máximo |
|---|---|---|
| **Sistema del cliente en vivo** | El programa y sus llamados **reales**, en la base de prueba del cliente | PROVEN |
| **Motor local** | El programa en el contenedor de la plataforma; los llamados son **sustitutos transaccionales** generados por código a partir de su firma (graban sus parámetros en una tabla propia, devuelven el código que el caso pide, participan en la transacción) | PARTLY PROVEN, con la razón: «los procedimientos X, Y, Z fueron sustitutos» |
| **Trazas** | Lo grabado en el sistema del cliente; la traza debe traer el estado final de las tablas | PARTLY PROVEN |

La configuración del proyecto pregunta si hay conexión al sistema del cliente; si no, usa el motor local y lo deja
registrado. Los mismos sustitutos sirven para probar el destino.

### 6. El veredicto declara su frontera

PROVEN exige, además de lo de ADR-0050: equivalencia medida sobre el estado de la base, programas llamados reales, y
un caso por cada punto de rollback. Si falta cualquiera, PARTLY PROVEN, y «Lo que esto no prueba» dice exactamente
cuál: «transacciones y programas llamados no verificados», «los procedimientos X, Y, Z fueron sustitutos», «los
puntos de rollback de las líneas N, M no tienen caso». La concurrencia (dos peticiones sobre la misma unidad) se
prueba con un caso específico y, si no existe, se declara.

### 7. El análisis de impacto y el orden por el grafo son del núcleo

El análisis de impacto (hoy solo sobre el legado, M17) existe también sobre la **aplicación destino**: qué clases,
tablas y transacciones alcanza un cambio, en cascada. Define el alcance del golden master en el flujo 3, qué debía
probar el tercero en el flujo 4 y el **orden de migración** en el flujo 1: de las hojas del grafo de llamadas hacia
arriba, de modo que al migrar un programa sus llamados ya están migrados y probados, y los sustitutos solo quedan en
la frontera no migrada. Es lo que hace viable el enfoque con miles de programas: el estado de base se acota a las
tablas del programa y sus llamados, los casos de error crecen con los puntos de rollback y no con las líneas, y la
caracterización corre en lotes por nivel del grafo.

### 8. Los cuatro flujos sobre el mismo núcleo

| Flujo | Qué es «antes» y «después» | Qué cambia |
|---|---|---|
| Modernización | Legado ↔ destino | Todo lo anterior |
| Validación independiente | Legado ↔ destino del tercero | Lo mismo; hoy certifica a terceros con la frontera ciega |
| Agregar a una aplicación existente | Aplicación **antes** del cambio ↔ aplicación **después** | Línea base de la aplicación actual (reglas, unidad de trabajo, grafo de datos), impacto sobre el destino, golden master antes/después en el alcance del impacto, **cero diferencias fuera del delta**. Es el flujo más exigente y el que más se ejecutará en la vida de cada aplicación; debe aceptar aplicaciones que no nacieron en la plataforma |
| Nueva funcionalidad | No hay «antes» | Unidad de trabajo en el diseño y prueba del código contra base real; sin equivalencia |

### 9. La semántica de cada motor es un manual ejecutable por código

Lo que ADR-0048 empezó como catálogo de quirks pasa a ser obligatorio para todo lenguaje y a llegar al arquitecto, al
desarrollador y al verificador. Un quirk se da por resuelto cuando el destino se comporta igual en su caso, no cuando
un caso pasa por su línea. El catálogo de Sybase incorpora lo que la revisión listó: defaults de parámetros y omitido
frente a NULL, errores en el llamado que no abortan al llamador, `money` a `int` y a `char`, `@@rowcount` de la última
sentencia, `substring` vacío a NULL.

### 10. Los lenguajes entran contra el contrato completo, nunca antes

Ningún origen se anuncia como soportado si no pasa las pruebas de conformidad del contrato. Un documento público de
cobertura dice, por lenguaje y por pieza del contrato, qué está hecho. El orden por demanda: Sybase completo →
Informix 4GL + SPL → .NET Framework 4.x con EF6 (uplift y reescritura) → cierre de RPG (R2 validado en IBM i,
*SRVPGM, 5250 en vivo) → paquetes PL/SQL de Oracle (sin Forms ni Reports) → Natural, PL/I, VB6, PowerBuilder,
Progress según demanda. Como destino se agrega .NET Core (6/8 LTS) por el eje de versión del pack .NET, y la estrategia
«misma base existente» como pack transversal.

## Alternativas consideradas

- **Corregir el Java generado a mano** siguiendo los 30 hallazgos. Entrega un resultado correcto para esta POC, pero
  no cambia la plataforma: el siguiente programa saldría igual. Rechazada por el cliente y por este ADR.
- **Dar la semántica al modelo como instrucciones y confiar en que la aplique.** Necesaria (punto 9) pero
  insuficiente: el fuente con `begin tran` ya estaba en el prompt del diseño y el desarrollador escribió un comentario
  falso sobre una frontera transaccional inexistente. Sin medición independiente no se sabe cuándo falla.
- **Exigir siempre los fuentes de los programas llamados.** Imposible en este caso y en la mayoría: los llamados siguen
  en producción. Basta con que existan compilados (modo cliente) o con sustitutos transaccionales (modo local).
- **Mantener P29** (reportar llamadas al instante) y agregar el estado de base como segundo criterio. Dejaría dos
  verdades contradictorias en el mismo golden master; se opta por el estado como criterio y las llamadas como
  diagnóstico.

## Consecuencias

- Todo veredicto anterior a este ADR se relee como «equivalente en lógica de decisión». La ejecución 44027f4f se
  reejecuta con la plataforma corregida y se contrasta con los 30 hallazgos como lista de verificación independiente.
- La caracterización cuesta más por programa (programas llamados reales o sustitutos, estado de tablas, casos de
  error). Lo compensan la sesión única por suite (plan 3b), la caché por caso y el paralelismo por nivel del grafo.
- Sin la base de prueba del cliente no hay PROVEN. Es un requisito de contrato, no una limitación técnica, y el
  veredicto lo dice.
- Las grabaciones de aceptación actuales (M4, M6, M8, M11) siguen válidas como pruebas de regresión del
  comportamiento anterior; las nuevas pruebas de aceptación miden estado de base.
- El flujo 3 deja de estar limitado a aplicaciones Spring Boot nacidas en la plataforma.
- Cambio de especificación: D-88, y precisiones a 8.2, 8.3, 11.2 y 11.3.

## Cómo se valida

- **Reejecución de `sp_debcred_empresa`** en modo local con sustitutos: los hallazgos C1 a C8 y A1 a A6 desaparecen
  del código generado, o la plataforma los marca como diferencia antes de dar un veredicto.
- **Pruebas de conformidad del contrato** sobre los cuatro adaptadores existentes.
- **Golden master de estado** en el motor local: un caso donde el programa llama y luego revierte deja la base
  idéntica al estado inicial; un destino que no revierte se marca como diferente.
- **Casos por rollback**: una suite sin caso para un punto de rollback no pasa la caracterización.
- **Veredicto**: en modo local el veredicto es PARTLY PROVEN y nombra los sustitutos; en modo cliente con todos los
  casos, PROVEN.
- **Flujo 3**: un cambio que toque una transacción compartida con un módulo no modificado produce una diferencia
  antes/después fuera del delta, y el veredicto la bloquea.

## Plan

Las fases, con sus puntos, están en `docs/planes/P-equivalencia-por-estado.md`. Orden: A (transacción como negocio,
veredicto honesto) → B (modos de ejecución, rollback visible, sustitutos) → C (estado de base, casos por rollback) →
D (unidad de trabajo y estrategia de datos en el diseño) → E (destino contra la base) → F (reejecución de
`sp_debcred_empresa`) → G (impacto, orden por grafo, contrato completo) → H (flujos 3, 4 y 2) → I (semántica
obligatoria, cierre de los cuatro adaptadores) → J (lenguajes nuevos y documento de cobertura).
