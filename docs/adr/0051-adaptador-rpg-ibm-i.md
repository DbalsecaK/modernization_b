# ADR-0051 — Adaptador de origen RPG / IBM i

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 8.2 (contrato del adaptador de origen), 8.3 (orígenes), 6.1 fases 2–5 (inventario a extracción)
- **Relacionadas:** ADR-0015 (COBOL/CICS: parser propio y trazas), ADR-0047 (cobertura del legado), ADR-0048
  (quirks del motor), ADR-0011 (kit de referencia fuera del repo); plan de soporte RPG aprobado (R1–R4)

## Contexto

Los clientes con IBM i (AS/400) tienen la lógica de negocio en programas RPG de cuatro épocas que conviven en una
misma biblioteca: RPG III / RPG/400 (OPM, formato fijo con columnas propias), RPG IV en formato fijo (ILE), RPG IV
mixto (especificaciones fijas con cálculo `/FREE` o líneas libres desde la columna 8) y RPG IV totalmente libre
(`**FREE`). Los datos viven en archivos descritos con DDS (físicos PF, lógicos LF), las pantallas en archivos de
pantalla DSPF y los reportes en archivos de impresora PRTF; los jobs los arranca CL/CLLE. Los programas de servicio
(*SRVPGM) exportan procedimientos que otros llaman con `CALLP`/`CALLB`. La plataforma no reconocía ninguno de estos
insumos.

## Decisión

1. **Un adaptador de origen nuevo (`nexti-adapter-rpg`, `rpg-ibmi`), sin cambios en el núcleo.** Implementa el
   contrato de 8.2 igual que Sybase, COBOL y ASPX: `detect`, `inventory`, `types`, `classification`/`classified`,
   `slices`, `data_of`, `engine_quirks`, `coverage_branches` y `digest`. Se registra en `ADAPTERS` y la plataforma
   lo elige por puntaje como a los demás.
2. **Parser propio y determinista de un subconjunto documentado**, como en COBOL (ADR-0015): las cuatro formas de
   RPG (columnas de RPG III y de RPG IV, factor 2 extendido, bloques `/FREE`, `**FREE`), `ctl-opt`/`H`, archivos
   (F / `dcl-f`), campos (D / `dcl-*`, campos definidos en el cálculo con longitud), interfaz de procedimiento y
   `*ENTRY PLIST`, subrutinas, procedimientos y su `EXPORT`, `NOMAIN`, `/COPY` e `/INCLUDE`, y SQL embebido. Lo que
   no reconoce es un problema del inventario con su línea, nunca una suposición. Nunca usa un modelo ni ejecuta.
3. **DDS y CL como parte del mismo origen.** Un PF es una tabla con sus columnas y su clave; un LF deriva de su
   PFILE y sus campos sin longitud toman el tipo del físico; un DSPF es un conjunto de registros de pantalla con
   campos, posiciones, constantes y teclas de función (nodo de mapa, como BMS); un PRTF es un archivo de salida,
   nunca una tabla. De CL se leen `CALL`, `SBMJOB CMD(CALL ...)`, `OVRDBF` y los parámetros del programa.
4. **Tipos neutrales exactos**: empaquetado y zonado con sus dígitos y decimales, binario y entero con su ancho,
   carácter de longitud fija en EBCDIC (los blancos finales cuentan), indicador a booleano, fecha y timestamp; las
   constantes numéricas toman el tipo de su literal. Flotante, gráfico y puntero se informan con una nota, sin
   adivinar un tipo.
5. **Ramas para la cobertura** (ADR-0047): las subrutinas y los procedimientos de cada programa, que es lo que
   reporta una traza o una herramienta de cobertura de IBM i.
6. **Por etapas.** R1 (este ADR): análisis — parser, inventario, tipos, slices y extracción con un espacio de
   trabajo ficticio. R2: golden master de batch y *SRVPGM con dos modos que el proyecto elige — conexión a un IBM i
   del cliente (puede llegar a PROVEN) o trazas grabadas (techo PARTLY PROVEN). R3: programas interactivos (guiones
   5250, pantallas y destino de UI según el proyecto). R4: catálogo de quirks de RPG (ciclo y cortes de nivel,
   redondeo `(H)` contra truncamiento, `MOVE`/`MOVEL`, EBCDIC/CCSID, `*INZSR`, `%ERROR`/INFDS, control de
   compromiso, desborde de página) dentro del contrato de ADR-0048.
7. **Fixtures ficticios** (Cooperativa Andina, inventada) en el repo, una pieza por forma de RPG; código de clientes
   nunca (ADR-0011).

## Alternativas consideradas

- **tree-sitter o un parser de terceros.** No hay una gramática mantenida que cubra las cuatro formas con DDS y CL;
  el soporte quedaría en nivel *Asistido* (8.6) y los números de línea y columnas dependerían de otra herramienta.
- **Extraer con el modelo directamente del texto.** Sin inventario determinista no hay slices, ni `data_of`, ni
  validación de citas; la extracción guiada (M18) depende de ellos.
- **Un adaptador por forma de RPG.** Los cuatro conviven en la misma biblioteca y se llaman entre sí; separarlos
  partiría el grafo.

## Consecuencias

- Un espacio de trabajo IBM i pasa por inventario, clasificación, extracción y diseño como los demás orígenes.
- Hasta R2 no hay golden master para RPG: una corrida de modernización no puede pasar de la caracterización.
- El parser crece por fixtures: cada construcción nueva entra con su caso ficticio y su prueba.

## Cómo se valida

`packages/adapters/source/rpg/tests` sobre el espacio de trabajo ficticio: las cuatro variantes se leen sin
problemas; parámetros por `*ENTRY PLIST` e interfaz; subrutinas y procedimientos exportados; aristas a tablas,
pantallas, reportes y llamadas desde CL; tipos de PF heredados por el LF; `data_of` sin funciones integradas ni
nombres de subrutina. En orquestación, `pick_adapter` elige RPG para IBM i y mantiene COBOL y Sybase en los suyos.
