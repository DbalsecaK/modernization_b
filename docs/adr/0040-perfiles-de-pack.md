# ADR-0040 — Packs parametrizables: versiones que llegan al pack y perfiles de pack del cliente

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 8.4 (pack de destino), 8.6 (niveles de soporte), 8.7 (olas de certificación)
- **Relacionadas:** ADR-0017 (packs), ADR-0037 (versiones por eje), ADR-0038 (preferencias), ADR-0039 (adaptadores declarados)

## Contexto

El aprobador pidió autogestionar packs de destino (arquitectura, backend, frontend, base de datos). Un pack es
plantillas deterministas, una imagen de sandbox con el compilador y las dependencias sin red, un arnés de
equivalencia y una aceptación grabada. Un modelo puede escribir plantillas, pero no puede fabricar la imagen ni la
evidencia; y ejecutar en la plataforma plantillas escritas por un modelo rompería la regla de que el código generado
solo corre en el sandbox.

## Decisión

1. **La versión elegida llega al pack.** `BackendPack.configured(target)` devuelve el pack ajustado a la corrida;
   Spring Boot fija la versión del `pom` desde la versión elegida (`backend_version`) entre las que el pack
   soporta; los demás packs devuelven el mismo pack. Añadir una versión es añadir su pin, su imagen y su grabación.
2. **Perfiles de pack del cliente** (`tenant_pack_profile`, RLS; `/api/v1/pack-profiles`, permiso
   `models.configure`): nombre, pack al que aplican, **raíz de paquete** y **convenciones**. El catálogo del cliente
   los ofrece como preferencia `pack_profile` del proyecto; el motor de composición valida la elección.
   - La raíz de paquete la verifica el código: con la extracción guiada, un diseño cuyo `base_package` no empiece
     por ella es un problema que vuelve al arquitecto.
   - Las convenciones son orientación: llegan al arquitecto, al desarrollador y al revisor con la pila del proyecto.
3. **Qué no se promete:** un pack nuevo (otro lenguaje o framework) sigue siendo código de la plataforma con su
   imagen y su certificación; la pantalla de packs lo dice. Un modelo no escribe packs que se ejecuten.

## Consecuencias

- El cliente moldea el código generado (paquetes, convenciones, versión) sin tocar packs ni imágenes.
- Un perfil es dato auditable del proyecto, no texto libre en un prompt.
- El camino para una tecnología de destino nueva queda explícito: pack + imagen + aceptación grabada, en una ola de
  certificación (8.7).
