# ADR-0042 — Generación fiel al programa (behaviour-preserving) en la extracción guiada

- **Estado:** Aceptada · 2026-10-06
- **Secciones:** 10.3 (generación), 11.1 (verificación en el bucle), 11.3 (verificación independiente)
- **Relacionadas:** ADR-0033 (extracción guiada), ADR-0035 (máscaras), ADR-0041 (ronda de corrección), ADR-0017 (packs)
- **Sustituye, en modo guiado:** la generación "desde las reglas" de M4 (el desarrollador recibía diseño, reglas y
  pruebas, nunca el programa)

## Contexto

Cinco corridas reales sobre un procedimiento de 2 173 líneas terminaron NOT PROVEN con 65/65 casos distintos. Las
15 reglas aprobadas citan 1 482 líneas pero las resumen en prosa (una regla por ≈500 líneas), 690 líneas no tienen
regla (entre ellas `@p_deb = isnull(@p_deb, @p)`, de la que dependen las ramas que fallan) y el desarrollador no veía
el programa: reconstruía desde la prosa, inventaba inicializaciones (`@o_x = 0` donde el legado deja NULL),
reescribía el SQL (`IN (5 valores)` → cinco `UPDATE`) y reordenaba llamadas. El plugin oficial de modernización
hace lo contrario en `modernize-transform`: quien escribe el código lee el módulo, las pruebas de caracterización
salen de las ramas del código ("cada IF/EVALUATE/switch recibe un caso") y la comparación viejo‑vs‑nuevo corre
**dentro** del bucle de construcción, antes de la verificación independiente. El prompt de modernización NexTI
(behaviour‑preserving, R01–R12) exige que el código fuente sea la fuente de verdad del comportamiento.

## Decisión

Con la opción `guided_extraction`, en el Flujo 1:

1. **Política behaviour‑preserving como system prompt.** `prompts/behavior-preserving.md` (R01–R12, preservaciones
   específicas, política de evidencia, clasificación de hallazgos), parametrizado con la pila de origen y de
   destino, precede al prompt del `test-engineer` y del `backend-dev`.
2. **El programa a la vista.** El test engineer y el desarrollador reciben el programa legado del caso de uso,
   numerado: entero hasta 3 000 líneas; más allá, un extracto con las líneas que citan las reglas del caso de uso
   (±10) y toda sentencia de control (ramas, bucles, llamadas, retornos, asignaciones de parámetros), declarado
   como extracto. El test engineer escribe pruebas por rama y por frontera; las reglas se nombran para la
   trazabilidad. El desarrollador aplica las obligaciones: defaults y normalizaciones de parámetros antes de
   cualquier regla, orden de llamadas, salidas NULL, errores solo donde el programa los lanza, predicados SQL
   idénticos.
3. **El golden master dentro del bucle de generación.** Cuando el proyecto completo compila y pasa sus pruebas, se
   ejecuta contra el golden master (la caracterización precede a la generación). Si hay casos distintos, el
   desarrollador corrige con el programa, las diferencias agrupadas (causas antes que consecuencias), los casos
   enteros y los extractos del legado; la corrección se acepta solo con **cero** casos distintos y el progreso
   parcial se conserva. A lo sumo `max_iterations` intentos por ronda; al agotarse, la pregunta de escalado
   (reintentar o parar) la decide una persona, como en toda verificación del bucle (11.1).
4. **Registro de hallazgos.** Cada corrección devuelve `findings.json`: `TECHNICAL_MAPPING`, `SEMANTIC_RISK`,
   `PLATFORM_DIFFERENCE`, `UNRESOLVED_DEPENDENCY`, `UNRESOLVED_FUNCTIONAL_INFORMATION`,
   `REQUIRES_EXTERNAL_DEFINITION`, `POTENTIAL_SOURCE_DEFECT` y `ERROR_MAPPING` (un mapa explícito de cada error del
   origen —código de retorno, parámetro de salida, error lanzado— a su forma en el destino). Se guarda como
   documento de la corrida (`generation/findings.json`), visible en la pestaña de código.
5. **La verificación independiente no cambia.** La ronda de corrección de ADR‑0041 solo actúa si aún quedan
   diferencias (con cero no se invoca).

Sin la opción, ninguna petición cambia: las grabaciones (M4, M6, M6c, M8b, M10, M11, M18) valen igual.

## Consecuencias

- La generación deja de ser "reimaginar desde la prosa" y pasa a "traducir con el programa a la vista y cerrar
  contra el golden master": lo que el plugin oficial llama `transform`, no `reimagine`.
- Costo acotado por corrida: una petición más larga (el programa) para pruebas y servicio, y hasta
  `max_iterations` correcciones con su equivalencia en sandbox; la persona decide al agotarse.
- El código del cliente viaja solo en peticiones en tiempo de ejecución y en documentos de la corrida del propio
  tenant; nada entra en repositorio, fixtures ni logs (ADR‑0011).
- Límite honesto: un programa mayor que el extracto pierde fidelidad en lo no mostrado, y un error de mapeo de
  entradas en el diseño no se corrige aquí: aparecerá como diferencias persistentes y escalará a la persona.
- Los flujos 3 (baseline), 2 (evidencia y ambigüedades) y 4 (clasificación de hallazgos) se alinearán en hitos
  posteriores (M25, M26).


## Precisión P31 (2026-10-07): las pruebas se compilan antes de que el desarrollador las vea

Una corrida real gastó los tres intentos del desarrollador (1,3 USD) en un archivo de pruebas que no compilaba por
sí mismo: el test engineer usó un campo que no había declarado en su propio helper, y el paso del servicio solo
deja al desarrollador escribir el servicio. Desde P31, en modo guiado, el paso de pruebas verifica cada respuesta
del test engineer compilándola en el sandbox contra los contratos del diseño y un **servicio de relleno** que el pack
genera con la forma que fijan los prompts (constructor con los puertos en el orden del caso de uso, `execute`): un
archivo que no compila vuelve al test engineer con el diagnóstico del compilador, con los mismos intentos y
escalado que cualquier otro paso. El modo no guiado no cambia (las grabaciones siguen iguales). Pendiente: el
servicio de relleno en los packs .NET y Go (sin él, el paso se comporta como antes).
