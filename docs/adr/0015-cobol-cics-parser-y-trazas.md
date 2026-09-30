# ADR-0015 — COBOL/CICS: parser determinista de un subconjunto y trazas como golden master

- **Estado:** Aceptada · 2026-09-30
- **Secciones:** 8.2, 8.3 (COBOL CICS: "trazas grabadas; techo PARTLY PROVEN si no corre localmente"), 8.6, 11.3,
  20 (M6)
- **Relacionadas:** ADR-0011 (kits de cliente fuera del repo), ADR-0012 (respuestas grabadas)

## Contexto

M6 agrega el origen COBOL/CICS. La spec pide inventario, clasificación, slicing y extracción, y la familia
Transacción → Programa → Mapa en el grafo. Un programa CICS no se puede ejecutar en la máquina del CI: necesita
una región CICS (o un emulador comercial). La spec acepta trazas grabadas en producción o en un ambiente de
prueba, con el veredicto limitado a PARTLY PROVEN.

## Decisión

- **Parser propio y determinista** para un subconjunto documentado de COBOL en formato fijo (columnas 7-72,
  comentarios y continuaciones), `COPY` con resolución de copybooks, `DATA DIVISION` (niveles, PIC, USAGE
  COMP/COMP-3, OCCURS, REDEFINES, VALUE, 88), `PROCEDURE DIVISION` (párrafos, secciones, PERFORM, CALL, GO TO)
  y `EXEC CICS ... END-EXEC` / `EXEC SQL ... END-EXEC` con su comando y opciones. Las definiciones de
  transacciones se leen de un CSD (`DEFINE TRANSACTION(...) PROGRAM(...)`). Lo que el parser no reconoce se
  reporta como problema del inventario, no se inventa.
- **Trazas como golden master.** Una traza es un caso ya observado (entradas del mapa o de la COMMAREA,
  registros de los archivos antes y después, programas llamados con sus respuestas, salidas del mapa). Se
  suben en el zip del código (`traces/*.json`). Un *runner de trazas* implementa el mismo contrato que el runner
  de Sybase: por cada caso que propone el ingeniero de pruebas busca la traza con esas entradas; si no existe,
  el error vuelve al agente con la lista de trazas disponibles.
- **Techo del veredicto.** Con un golden master de trazas, las entradas frescas no se pueden observar en el
  legacy: ese chequeo queda "no verificado" y el veredicto no pasa de PARTLY PROVEN. "Lo que no prueba" lo dice.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| tree-sitter-cobol o ProLeap (ANTLR) | Gramáticas amplias pero sin CICS/CSD integrados, dependencias nativas o JVM en el worker; el nivel *certificado* (8.6) pide un parser cuyo comportamiento controlamos y probamos contra la referencia |
| Análisis solo con LLM | Nivel *experimental*; el inventario y el slicing deben ser deterministas |
| Emular CICS | Fuera del alcance de la Ola 1; las trazas cubren la validación con el techo que fija la spec |

## Consecuencias

- El subconjunto soportado se amplía con cada aplicación de referencia; lo no soportado aparece como problema.
- La aplicación ficticia incluye sus trazas; con clientes, las trazas se exportan de su ambiente de prueba.
- El pipeline de análisis elige el adaptador por detección (Sybase o COBOL) y deja de nombrar Sybase.

## Cómo se valida

- Tests del parser y del adaptador contra la spec de referencia ficticia (programas, párrafos, copybooks,
  transacciones, mapas, archivos, con archivo y línea).
- Test del runner de trazas (caso encontrado, caso sin traza).
- Aceptación grabada: evaluación contra la referencia CICS y veredicto PARTLY PROVEN.
