# ADR-0025 — Flujo 4: validación independiente (IV&V) de una migración hecha por un tercero

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 3.1 y 3.3 (flujos y su preparación), 6 (Flujo 1), 11.3 (veredicto), 15.5 (sandbox), 20 (Posterior)
- **Relacionadas:** ADR-0012 (grabaciones), ADR-0015 (trazas), ADR-0021 (packs y sandbox)

## Contexto

El Flujo 4 valida una migración que hizo otro, sin usar artefactos de la plataforma. La sección 3.3 pide dos cosas:

- que la extracción de reglas corra sobre dos códigos distintos y se compare;
- que la validación reciba un "destino" externo.

La plataforma ya tiene, para el legado:

- el inventario y la extracción de reglas con revisión;
- el golden master, con su motor o con trazas.

No tiene cómo ejercitar un destino que no generó. El harness de equivalencia llama por reflexión las clases del diseño
propio.

## Decisión

### Insumos y fases

- **El flujo `independentValidation`** recibe dos archivos:
  - el código del legado (`source_archive`);
  - el destino del tercero (`target_archive`): su código fuente y, para la prueba dinámica, su artefacto ejecutable
    (un *fat jar* de Spring Boot).
- **Fases:**
  - preflight;
  - inventario y extracción de reglas del legado, con revisión y C1;
  - caracterización (golden master);
  - **ingesta del destino;**
  - **mapeo (C2);**
  - **reglas del destino;**
  - **verificación independiente (C4: sign-off);**
  - **informe.**

### Destino y mapeo

- **Ingesta del destino, por código (adaptador `nexti_adapter_target`).** Detecta la pila (Spring Boot; ASP.NET Core
  en el inventario) y arma su inventario:
  - los endpoints con su método, ruta y campos de entrada y salida;
  - las tablas;
  - los métodos que sirven de *slices* para extraer reglas.
- **Mapeo propuesto por código y aprobado por una persona (C2).** Para cada programa legado:
  - el endpoint que lo reemplaza;
  - de qué parámetro sale cada campo del pedido;
  - qué campo de la respuesta corresponde a cada salida;
  - qué tabla y qué columnas del destino corresponden a cada tabla legada.

  Si el destino trae un `ivv-mapping.yaml`, ese manda. La persona corrige el mapeo antes de aprobar: sin un contrato
  aceptado no hay comparación justa.

### Prueba y comparación

- **Prueba de caja negra en el sandbox.** El artefacto del tercero corre en `nexti-sandbox-java` con PostgreSQL:
  - el esquema es el del propio destino;
  - el harness de un solo archivo usa HTTP y JDBC.

  Por cada caso del golden master:
  1. carga las filas iniciales traducidas a las tablas del destino;
  2. llama al endpoint;
  3. lee la respuesta y las tablas;
  4. lo traduce de vuelta a la observación del legado.

  La comparación usa las mismas diferencias y máscaras del Flujo 1. Las entradas nuevas corren cuando hay motor para
  el legado.
- **Reglas de los dos códigos.**
  - Los agentes de extracción corren sobre los *slices* del destino con el mismo procedimiento del Flujo 1.
  - El código compara las reglas del destino con las aprobadas del legado y deja tres listas: presentes, faltantes y
    comportamiento extra.

  Es evidencia complementaria: la que decide es la ejecución.

### Veredicto

El código lo calcula con un juego de chequeos propio, `IVV_CHECKS`:

- `target_runs`: el destino arrancó y respondió;
- `contract_mapped`: el mapeo aprobado cubre cada programa del golden master;
- `same_behaviour`: los casos golden reproducidos;
- `fresh_inputs`;
- `rules_covered`: cada regla aprobada tiene un caso golden reproducido por el destino;
- `rules_compared`: las reglas extraídas del destino, sin reglas legadas faltantes;
- `source_intact`.

El canario del Flujo 1 no aplica: el artefacto del tercero no se muta. El informe IV&V y el paquete de prueba
acompañan el veredicto.

## Alternativas consideradas

- **Compilar el código del tercero en el sandbox.** Sus dependencias no están en el repositorio sin red. El artefacto
  ejecutable ya las trae, y el código fuente sigue sirviendo para el inventario y las reglas.
- **Comparar solo las reglas extraídas.** Sin ejecución, el veredicto sería una opinión de modelos. La ejecución del
  golden master es la evidencia; las reglas son el complemento que pide la sección 3.3.
- **Exigir que el tercero adopte el contrato de la plataforma.** No es independiente. El mapeo se adapta al destino
  tal como es.

## Consecuencias

- **Un tercer flujo** en el catálogo, la composición, los proyectos y la web, con un tipo de insumo nuevo
  (`target_archive`).
- **La prueba dinámica cubre destinos HTTP de Spring Boot.** ASP.NET Core y otros quedan en inventario y reglas hasta
  tener su harness.
- **El mapeo es una decisión humana auditada,** porque de él depende la justicia de la comparación.

## Cómo se valida

- **Pruebas del adaptador del destino:** inventario de un proyecto Spring Boot y de un ASP.NET Core.
- **Pruebas del mapeo propuesto y del harness de caja negra:**
  - un destino correcto y uno con un error introducido;
  - el veredicto los distingue.
- **Aceptación grabada:**
  - una migración "de terceros" de la aplicación ficticia, escrita a mano con otra estructura, más su jar;
  - las respuestas del legado vienen de M4.
