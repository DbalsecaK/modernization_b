# ADR-0048 — Quirks del motor legado y entorno de ejecución

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 11.3 (golden master), 6.1 fases 9 y 11 (caracterización y generación), 11.2 (veredicto)
- **Relacionadas:** ADR-0042 (generación fiel), ADR-0047 (cobertura del legado), plan aprobado (M28)

## Contexto

Un programa legado depende de comportamientos de su motor que un stack moderno hace distinto: en Sybase ASE,
`x = NULL` es verdadero con `ansinull` apagado, `'a' + NULL` da `'a'`, `''` es un espacio, `select @v = col` sin
filas deja `@v` como estaba. El golden master los muestra solo si un caso pasa por las líneas que los usan, y el
desarrollador los descubre por las diferencias, ronda tras ronda. Además el legado corre bajo ajustes (aislamiento,
formato de fecha, idioma, juego de caracteres, zona horaria, opciones SET, triggers) que nadie registraba.

## Decisión

1. **Contrato neutral.** `SourceAdapter.engine_quirks(files)` devuelve los quirks del catálogo de la tecnología que
   el código usa, cada uno con sus líneas, severidad (critical, high, medium, low), qué hace el motor y qué debe
   hacer el destino. Un adaptador sin catálogo devuelve una lista vacía (COBOL, ASPX, declarativos, por ahora).
2. **Detección por código, confirmación en el motor.** El adaptador encuentra los quirks por sus tokens, nunca con
   un modelo. Cada quirk del catálogo trae una sonda: unas sentencias que el runner ejecuta en el mismo motor que
   graba el golden master, una vez por motor. El registro guarda la respuesta: confirmado, no en este motor (sus
   opciones dicen otra cosa; manda el golden master) o no sondeado.
3. **Inventario de entorno.** El runner mide los ajustes del motor (versión, aislamiento, `datefirst`, idioma,
   juego de caracteres, `textsize`, zona horaria, interpretación de una fecha ambigua) y el adaptador agrega lo que
   el programa y sus fuentes fijan (opciones SET, triggers). Todo queda en el golden master
   (`quirks`, `environment`; omitidos si están vacíos, así las grabaciones anteriores no cambian).
4. **Casos que los resuelven.** Con la cobertura de ADR-0047, un quirk está resuelto cuando un caso confiable entra
   en la rama más interna que contiene una de sus líneas (una línea fuera de toda rama la recorre cada caso). Los
   quirks que ningún caso alcanza van en la misma única ronda de M27b al test engineer. Los pares de quirks critical
   o high que coinciden en una rama necesitan un caso que entre en ella (combinaciones).
5. **Generación.** Las notas del motor (quirks con su estado y ajustes) van junto al programa numerado al tester, al
   desarrollador y a la convergencia; `docs/legacy-engine.md` documenta el registro y el entorno en la entrega.
6. **Veredicto.** Los quirks sin caso y las combinaciones sin caso figuran en lo que el veredicto no prueba. El ADR
   del veredicto (paso 8 del plan) decidirá si bloquean PROVEN.

## Catálogo de Sybase ASE

| Quirk | Severidad | Sonda (respuesta esperada en ASE 16) |
|---|---|---|
| null-compare | critical | `if @n = null` con `@n` nulo → true |
| null-concat | high | `'a' + null` → `a` |
| empty-string | high | `datalength('')` → 1 |
| select-assign-from-table | high | `select @v = id ... where 1 = 2` deja 5 |
| error-continues | high | sin sonda |
| nested-tran | high | dos `begin tran` y un `rollback` → `@@trancount` 0 |
| rowcount-option | high | `set rowcount 1` limita un update a 1 fila |
| char-padding | medium | `'a' = 'a  '` → true |
| integer-division | medium | `7 / 2` → 3 |
| date-style | medium | estilo 103 → `05/03/2024` |

## Catálogo de RPG / IBM i (R4 del plan RPG, 2026-10-08)

Detectado en el programa analizado, sin sonda: el puente de IBM i (ADR-0053) ejecuta programas, no sentencias
sueltas, así que cada quirk queda «no sondeado» y el golden master muestra lo que hizo el sistema. Con trazas, el
worker agrega el catálogo del adaptador al golden master (las trazas no traen quirks).

| Quirk | Severidad | Se detecta por |
|---|---|---|
| rpg-cycle | critical | archivo primario (F con designación P), cálculos LR |
| decimal-truncation | critical | aritmética sin (H): ADD, SUB, MULT, DIV, Z-ADD, EVAL que calcula |
| level-breaks | high | cálculos con nivel L1-L9 |
| half-adjust | high | (H) en el código de operación o en la columna 53 (RPG III) |
| fixed-overflow | high | aritmética de formato fijo (pierde dígitos altos sin error) |
| move-semantics | high | MOVE, MOVEL, MOVEA |
| record-not-found | high | CHAIN y lecturas (no fallan; los campos conservan su valor) |
| ebcdic-order | high | comparaciones `<` `>` de texto, SORTA, LOOKUP, lecturas en secuencia por clave |
| errors-handled-by-program | high | extensor (E), MONITOR, %ERROR, indicadores resultantes, *PSSR |
| immediate-writes | high | escrituras a tablas sin control de compromiso |
| commitment-control | high | COMMIT, ROLBK |
| intermediate-precision | medium | EVAL con división |
| division-remainder | medium | MVR |
| initialization-subroutine | medium | *INZSR |
| page-overflow | medium | OFLIND en un archivo de impresora |

El entorno del programa sale de sus palabras clave de control (DATFMT, EXPROPTS, FIXNBR, TRUNCNBR, CCSID...) y, si
no fija DATFMT, del formato por omisión *ISO.

## Consecuencias

- Un lote más por arranque del motor (sondas y entorno, segundos).
- El desarrollador recibe el comportamiento del motor antes de la primera diferencia.
- Los quirks confirmados en otra tecnología se agregan como catálogo de su adaptador (pasos 11 y RPG del plan).

## Cómo se valida

Pruebas unitarias de detección sobre código ficticio (comparación con NULL frente a asignación, UPDATE ... SET que
no es opción de sesión), del runner con un motor falso (registro, estado por sonda, una sola vez por motor), del
núcleo (casos por quirk, combinaciones, notas, serialización sin cambios) y de la ronda de caracterización; y en
vivo con Sybase ASE 16: cada sonda del catálogo responde lo esperado y el entorno se mide completo.
