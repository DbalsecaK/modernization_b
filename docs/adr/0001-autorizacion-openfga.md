# ADR-0001 — Autorización con OpenFGA (D-15)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 16 (RBAC), 15.1, 19.2, M0

## Contexto

La plataforma es multi-tenant y multi-proyecto. Los permisos dependen de relaciones: un usuario es miembro de
un tenant, tiene un rol en un proyecto concreto, el administrador del tenant hereda permisos sobre sus
proyectos y hay segregación de funciones (quien lanza una generación no aprueba su compuerta). Además de "¿puede
X hacer Y sobre Z?", varias pantallas necesitan "¿qué proyectos o eventos puede ver X?": listados, buscador
global, panel de actividad y Mis tareas.

## Decisión

Usar **OpenFGA** (modelo de relaciones estilo Google Zanzibar) para la jerarquía plataforma → tenant → proyecto.

- **Fuente de verdad de roles y membresías:** PostgreSQL (`membership`, `project_member`, `role`,
  `role_permission`), con RLS por `tenant_id`.
- **Sincronización:** un único módulo de la API escribe la fila y la relación de OpenFGA en la misma
  operación mediante **outbox**; un job de **reconciliación** detecta y corrige diferencias.
- **Modelo versionado** en `infra/openfga/`, con tests del modelo (permitido/denegado) en CI.
- **Uso:** cada endpoint consulta OpenFGA con el usuario y el tenant de la sesión; las denegaciones y las
  acciones sensibles se registran en la auditoría.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Casbin | Bueno para RBAC/ABAC con políticas por archivo, pero las relaciones jerárquicas y la pregunta inversa ("¿qué puede ver X?") se resuelven peor; habría que construir la lista de objetos a mano |
| Permisos solo en PostgreSQL | Simple al principio, pero mezcla la lógica de autorización en consultas y endpoints y no escala a herencia y segregación de funciones |
| Oso / Cerbos | Válidos, pero la especificación, el prototipo y el roadmap ya están diseñados con OpenFGA |

## Consecuencias

- Un servicio más que operar (en dev, en Docker Compose; en producción, con su propia base).
- Consistencia eventual entre PostgreSQL y OpenFGA, acotada por el outbox y la reconciliación.
- Los tests de autorización de cada endpoint (regla de `CLAUDE.md`) corren contra un OpenFGA real en CI.

## Cómo se valida (M0)

Tests de autorización permitido y denegado por endpoint; test de aislamiento entre tenants; un cambio de rol se
refleja en OpenFGA y la reconciliación corrige una diferencia forzada.
