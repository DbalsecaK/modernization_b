# ADR-0049 — Cobertura del destino bajo el golden master

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 11.2 (veredicto), 11.4 (paquete de prueba), 15.5 (imágenes de sandbox)
- **Relacionadas:** ADR-0047 (cobertura del legado), ADR-0048 (quirks del motor), plan aprobado (M29)

## Contexto

ADR-0047 mide qué del legado recorren los casos. Falta la otra mitad: qué del **destino** recorren. Código del
destino que ningún caso del golden master ejecuta puede ser lógica que el legado no tiene (inventada por el modelo)
o una rama que la suite no cubre. Sin medirlo, PROVEN no dice nada de ese código.

## Decisión

1. **Herramienta nativa de cada stack**, en la imagen de su sandbox (sin red):
   - Java: el agente JaCoCo 0.8.13 en `/opt/coverage` (fuera de `/opt/lib`, nunca en el classpath del código
     generado); el informe solo de las clases del destino (`/work/out`), no del arnés.
   - .NET: `dotnet-coverage` 18.12.0 en `/opt/tools`, informe Cobertura; el arnés queda fuera.
   - Go: la cobertura del toolchain (`go build -cover -coverpkg=./...`, `GOCOVERDIR`, `go tool covdata`); el paquete
     del arnés queda fuera.
2. **Solo el arnés del golden master se mide**, no las pruebas unitarias: la pregunta es qué ejecutan los casos del
   legado. El script mide cuando la imagen tiene la herramienta; una imagen anterior sigue funcionando sin medir.
3. **El informe vuelve por la salida**, comprimido (gzip y base64) entre `===COVERAGE <formato>===` y
   `===COVERAGE-END===`, después del arnés, para no chocar con el tope de salida del sandbox.
   `nexti_sandbox.coverage` lo lee y lo reduce a un formato neutro: líneas ejecutables, líneas ejecutadas y regiones
   sin ejecutar por archivo.
4. **Hallazgo, nunca bloqueo.** El veredicto lista la cobertura y hasta 30 regiones del destino que ningún caso
   ejecuta ("lógica que el legado puede no tener, o un caso que la suite no tiene"). El paquete de prueba lleva
   `TARGET_COVERAGE.json` completo. El ADR del veredicto (paso 8 del plan) decide qué exige PROVEN.
5. **Alcance**: los packs principales (Spring Boot con PostgreSQL, .NET con SQL Server, Go). Las variantes (Oracle,
   MySQL, MongoDB, Quarkus) tienen su propio script e imagen; no miden todavía y lo dicen por omisión (sin nota de
   cobertura). Se extenderán con el mismo bloque.

## Consecuencias

- Imágenes reconstruidas (mismas etiquetas: el cambio es aditivo).
- La corrida del arnés es algo más lenta con el agente o el binario instrumentado (segundos).
- El código de infraestructura que el arnés reemplaza (adaptadores, arranque) aparece como no ejecutado: es
  esperado y queda a la vista para que el revisor lo distinga de la lógica de negocio.

## Cómo se valida

Pruebas unitarias de los tres formatos (JaCoCo, Cobertura, perfil de Go), de la extracción desde la salida y de su
ausencia. En el sandbox real, el destino de referencia de cada pack reproduce los 12 casos y la cobertura vuelve con
algo ejecutado y algo sin ejecutar.
