# ADR-0026 — Flujo 3: añadir funcionalidad a una aplicación existente

- **Estado:** Aceptada · 2026-10-02
- **Secciones:** 3.1 y 3.3 (flujos y su preparación), 7 (Flujo 2), 11.4 (validación por aceptación), 20 (Posterior)
- **Relacionadas:** ADR-0017 (packs de backend), ADR-0018 (Flujo 2), ADR-0025 (inventario del destino)

## Contexto

El Flujo 3 parte de una aplicación que ya funciona y de un pedido nuevo (historias, documentos). Según la tabla 3.1:

- **entrada:** la spec AS-IS (el inventario) más la spec delta;
- **salida:** solo el delta, reutilizando lo existente;
- **validación:** regresión, aceptación y fitness functions.

La plataforma ya tiene:

- el inventario por código de una aplicación Spring Boot sin extraer reglas (`nexti_ivv.target`, Flujo 4);
- la ingesta, normalización y consolidación de historias con su revisión en C1 (Flujo 2);
- la compilación y las pruebas en el sandbox del pack, la convención de pruebas por criterio y el canario por
  mutaciones (Flujos 1 y 2).

No tiene cómo cambiar un código que no generó sin romper lo que ya hace.

## Decisión

### Insumos y fases

- **El flujo `extendExisting`** recibe:
  - el código de la aplicación existente (`source_archive`); en esta versión, Spring Boot;
  - los documentos del pedido (`document`), como en el Flujo 2.
- **Fases:**
  1. preflight;
  2. **inventario AS-IS:** endpoints, campos, tablas y servicios por código, sin reglas. La **línea base** compila la
     aplicación en el sandbox y corre sus pruebas: las que pasan son las que la regresión exige;
  3. ingesta, normalización y consolidación del pedido (Flujo 2);
  4. revisión de la spec delta (C1);
  5. **diseño del delta (C3);**
  6. **generación del delta;**
  7. **validación (C4);**
  8. entrega.

### Diseño del delta (C3)

El arquitecto propone, a partir de las historias aprobadas y del inventario AS-IS, una lista de cambios. Cada cambio
trae:

- las historias que cubre;
- el endpoint nuevo (método, ruta, campos de pedido y respuesta) o el existente que se extiende;
- las clases existentes que reutiliza;
- las tablas existentes que usa y las nuevas que crea;
- los archivos que espera tocar.

El código lo valida y devuelve los problemas:

- todo criterio de las historias cae en un cambio;
- un endpoint nuevo no choca con uno existente;
- lo que dice reutilizar existe en el inventario;
- no se toca un archivo de pruebas existente.

### Generación del delta

Por cambio, igual que en el Flujo 1:

1. el test engineer escribe las pruebas de aceptación con el id de cada criterio, al estilo de las pruebas
   existentes;
2. el backend developer escribe los archivos nuevos y el contenido completo de los existentes que cambia;
3. el código arma el proyecto (lo existente más el delta), lo compila y corre **todas** las pruebas en el sandbox;
4. si algo falla, vuelve con la salida del compilador o de JUnit (hacer → verificar → corregir).

Solo se guardan los archivos del delta, y nunca se borra un archivo existente.

### Validación (C4)

El código la calcula sin modelos, con un juego de chequeos propio, `EXTEND_CHECKS`:

| Chequeo | Pasa cuando |
|---|---|
| `regression` | Toda prueba que pasaba en la línea base sigue pasando |
| `criteria_covered` | Cada criterio de las historias tiene una prueba que pasa con su id |
| `contract_kept` | Todo endpoint AS-IS sigue con el mismo método, ruta y campos de pedido |
| `fitness` | El delta no borra archivos, no toca pruebas existentes ni el `pom.xml`, y ningún controlador usa SQL |
| `canary` | Un cambio de una línea en el código nuevo pone una prueba en rojo |
| `traced_to_inputs` | Cada historia y cada cambio citan un insumo aceptado |

La persona firma en C4.

### Entrega

El delta sale como rama `nexti/` del repositorio de la aplicación (el *push* de M9a), o como ZIP con solo los
archivos del delta y un `DELTA.md` (archivos nuevos y cambiados, historias, veredicto).

## Consecuencias

- **El Flujo 3 reutiliza el inventario del Flujo 4 y la mitad documental del Flujo 2.** Lo nuevo es el diseño, la
  generación y la validación del delta.
- **Una regresión depende de las pruebas que la aplicación ya tiene.** Sin pruebas, `regression` queda "no
  comprobado" y el veredicto no puede ser PROVEN. El informe lo dice.
- **Solo backend Spring Boot.** El delta de UI y otras pilas quedan para después.
