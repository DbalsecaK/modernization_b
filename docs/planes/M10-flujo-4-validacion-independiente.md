# Plan del hito M10 — Flujo 4: validación independiente (IV&V)

- **Estado:** en curso (desde 2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 3.1 y 3.3, 6, 11.3 y 20 (Posterior);
  - ADR-0025 y D-44.
- **Rama:** `m10-flujo-4`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0025. El aprobador pidió avanzar de corrido hasta terminar.
- **Presupuesto de grabación:** hasta 2 USD.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Flujo `independentValidation` en catálogo, composición, proyectos, insumos y web | Harness dinámico para destinos que no sean Spring Boot (quedan en inventario y reglas) |
| Insumo `target_archive` (código del tercero y su artefacto ejecutable) | Compilar el código del tercero sin red |
| Adaptador del destino: endpoints, campos, tablas, *slices* (Spring Boot; ASP.NET Core) | |
| Mapeo propuesto por código y aprobado en C2 | |
| Prueba de caja negra del golden master contra el artefacto del tercero en el sandbox | |
| Extracción de reglas del destino y comparación con las del legado | |
| Veredicto IV&V (`IVV_CHECKS`), informe y paquete de prueba | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0025 y D-44 |
| 2 | El flujo en el catálogo, la composición, la base (migración), la API y la web; insumo `target_archive` |
| 3 | Adaptador del destino (`nexti_adapter_target`): inventario y *slices* |
| 4 | Mapeo: propuesta por código, `ivv-mapping.yaml`, gate C2 y su API |
| 5 | Harness de caja negra en el sandbox y comparación con el golden master |
| 6 | Fases del flujo, reglas del destino, veredicto IV&V, informe y paquete de prueba |
| 7 | Web: mapeo en C2 e informe IV&V (en/es) |
| 8 | Aceptación grabada, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El inventario del destino tiene sus endpoints, campos y tablas | Pruebas del adaptador |
| El mapeo propuesto empareja programa, endpoint, campos y tablas | Pruebas del mapeo |
| Un destino correcto reproduce el golden master; uno con un error no | Pruebas del harness |
| La migración de terceros de la aplicación ficticia recibe su veredicto IV&V con informe | `test_acceptance_m10.py` |
| C2 y la API del mapeo, con OpenFGA, auditoría y aislamiento | `test_endpoints_authz.py` |
