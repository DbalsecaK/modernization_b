# ADR-0037 — Versiones por eje en el catálogo y en el proyecto

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 8.3 (orígenes), 8.4 (pack de destino), 8.6 (niveles de soporte)
- **Relacionadas:** ADR-0017 (packs), ADR-0012 (grabaciones)

## Contexto

El asistente elegía la tecnología de cada eje (backend, frontend, base de datos, nube) pero no su versión. La
versión existía, fija dentro de cada pack y de su imagen de sandbox (Spring Boot 3.5.6, Quarkus 3.40, .NET 10, Go
1.26, React 19, Angular 22), sin verse en la pantalla. El aprobador pidió poder elegir versiones, por ejemplo de
Spring Boot o de Sybase, con la lección de otra versión del producto en la que se guardaban valores sin respaldo y
quedaban huérfanos.

## Decisión

- **El catálogo declara versiones por opción** (`versions` en `targets.yaml` y `sources.yaml`): clave, nombre,
  nivel y si es la predeterminada. Una versión **certificada** es la que el pack fija y su imagen de sandbox trae;
  una versión **planificada** se lista para que se vea el camino, pero no se puede elegir hasta que tenga imagen y
  grabación de aceptación. No se admite texto libre.
- **El proyecto guarda la versión elegida por eje** (`target.versions`). El motor de composición la valida: una
  versión que no está en el catálogo o está planificada es un problema que bloquea la creación.
- **La corrida la recibe plana** (`backend_version`, `frontend_version`...), para que los packs puedan leerla.
- **Origen:** las versiones del adaptador (Sybase ASE 16.0 certificada, 15.7 planificada; .NET Framework 4.8) se
  muestran junto al origen elegido. La versión del motor del golden master sigue fija en el adaptador.

## Consecuencias

- Añadir una versión es: imagen de sandbox, pin en el pack, grabación de aceptación y pasar la versión de
  `planned` a `certified` en el catálogo. Nada más.
- La pantalla deja de esconder qué versión se genera: lo que se elige es lo que el pack produce.
- Las bases de datos y nubes no tienen versiones en esta entrega: sus imágenes fijan una versión que el catálogo
  describe, y se listarán cuando haya más de una certificada.
