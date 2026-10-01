# ADR-0018 — Flujo 2: insumos citables, integraciones del tenant y veredicto por criterios

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 7.1 a 7.5 (Flujo 2), 7.7 (historias), 11.4 (validación), 15.4 (insumos), 20 (M7)
- **Relacionadas:** ADR-0007 (OpenBao), ADR-0008 (validación de insumos), ADR-0016 (frontend), ADR-0017 (packs)

## Contexto

El Flujo 2 construye una funcionalidad nueva desde documentos, historias de usuario y Figma, sin código legado. La
plataforma ya tiene historias con Gherkin validado (D-26), plan por olas, prototipos (M5) y packs de backend y
frontend. Le faltan tres cosas:

- leer insumos que no son código y citarlos con la misma trazabilidad del Flujo 1;
- guardar las credenciales de herramientas externas del cliente, como Figma;
- un veredicto que no depende de un golden master, porque no hay legado que observar.

## Decisión

- **Cada insumo se vuelve un texto con líneas.** La regla, la historia o la pantalla cita `archivo:línea`, igual que
  en el Flujo 1, y el código verifica que la cita exista. La conversión depende del insumo:
  - Markdown y texto se leen tal cual en el worker.
  - Word y Excel son ZIP con XML. Se convierten dentro del sandbox sin red con la biblioteca estándar de Python:
    - Word da un párrafo por línea, y cada fila de una tabla en una línea con `|`.
    - Excel da cada hoja con su encabezado y una línea por fila.
  - PDF se convierte en el sandbox `nexti-sandbox-docs`, con `pypdf` fijado por versión, y marca cada página.
  - Figma se lee con la API REST de lectura (`GET /v1/files/:key`). El árbol de nodos se convierte en una línea por
    nodo: tipo, nombre, id, texto y destino de la navegación del prototipo.
- **Integraciones del tenant.** La tabla `tenant_integration` guarda el tipo (figma, jira, azure_devops, github,
  gitlab), el nombre, el estado y la ruta del secreto. El token vive solo en OpenBao, nunca en la base de datos ni en
  las respuestas.
  - Solo un administrador del tenant la gestiona (OpenFGA). Cada alta, prueba y baja queda en la auditoría.
  - El worker lee el token por la ruta guardada.
  - M7b usa la misma tabla para Jira y Azure DevOps.
- **Veredicto del Flujo 2, calculado por código** con 6 chequeos:
  - tests;
  - criterios cubiertos: cada criterio de cada historia activa tiene un test que lleva su id (`ac_US001_2`) y pasó;
  - contratos: cada operación del OpenAPI derivado del diseño tiene su endpoint;
  - canario;
  - preguntas cerradas;
  - trazado a insumos.

  PROVEN, PARTLY PROVEN y NOT PROVEN mantienen el significado de 11.3. El frontend conserva su propio veredicto
  (ADR-0016).
- **Los pedidos del Flujo 1 no cambian.** El diseño sin legado usa su propio prompt (`solution-architect-feature`).
  El test engineer recibe los criterios solo en el Flujo 2. Así las grabaciones de M4 a M6c siguen valiendo.

## Alternativas consideradas

- **Una imagen con todas las bibliotecas de documentos (python-docx, openpyxl).** Agrega dependencias nativas
  (lxml) al sandbox. Word y Excel se leen bien con la biblioteca estándar; solo PDF necesita una biblioteca.
- **Citar documentos por sección o por párrafo.** Obliga a una segunda forma de referencia y a otro verificador.
  Las líneas del texto convertido sirven para todos los insumos.
- **Guardar el token de Figma en el proyecto.** La conexión es del cliente y la usan varios proyectos, así que va en
  el tenant, como las conexiones de IA.
- **Medir los criterios con un juez de IA.** El veredicto debe salir del código. El juez puede sugerir, pero no
  decide.

## Consecuencias

- La conversión de un PDF con fuentes sin mapa de caracteres puede perder texto. El insumo queda con un aviso y la
  persona lo revisa en C1.
- La fidelidad visual contra Figma no se mide píxel a píxel. Lo que se verifica es que cada frame aprobado tenga su
  pantalla y cada campo esté presente (chequeos del frontend).
- La lectura de capturas con visión espera a que el gateway mande imágenes (M7b).

## Cómo se valida

- Pruebas de cada lector con documentos ficticios. Las de DOCX, XLSX y PDF corren en el sandbox.
- Pruebas de API de las integraciones: OpenFGA, aislamiento entre tenants y auditoría.
- Pruebas unitarias de la normalización y la consolidación.
- `test_acceptance_m7.py`: el ejemplo «Simulador de crédito» de punta a punta con modelos reales grabados.
