# ADR-0006 — Identidad global sin `tenant_id`, con visibilidad por RLS (D-29)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 14.2, 15.1, 16, 19.4; regla 1 de `CLAUDE.md`
- **Relacionadas:** ADR-0001 (OpenFGA), ADR-0002 (Organizations), ADR-0004 (autenticación por etapas)

## Contexto

La regla 1 exige `tenant_id` con Row-Level Security en toda tabla de negocio. Pero una persona puede trabajar
para varios clientes (un usuario de NexTI con membresía en varias organizaciones, ADR-0002), y su cuenta de
Keycloak es una sola. Duplicar el usuario por tenant rompería el enlace por `sub`, la preferencia de idioma que lo
sigue entre dispositivos y la auditoría de quién hizo qué.

## Decisión

Estas tablas **no** llevan `tenant_id`, y cada una tiene su propia forma de aislamiento:

| Tabla | Por qué | Aislamiento |
|---|---|---|
| `app_user` | Identidad global: una persona, varias membresías | RLS forzado: cada usuario se ve a sí mismo y a los usuarios del tenant activo; durante el login solo al que entra (por `sub` o correo verificado) |
| `permission`, `permission_scope` | Catálogo de la plataforma (16.2), igual para todos | Solo lectura para la API (sin grants de escritura) |
| `platform_role_assignment` | Roles de NexTI, no son datos de un cliente | Solo lectura para la API; los asignan operadores con el rol dueño |
| `keycloak_event_cursor` | Estado técnico del lector de eventos | Sin datos de clientes |

- `tenant` también tiene RLS: se ve el tenant activo y aquellos donde el usuario tiene membresía activa.
- Invitar a una persona que ya existe en otro tenant pasa por `ensure_user_for_invitation()` (SECURITY DEFINER),
  que devuelve su id sin exponer la fila.
- Todas las demás tablas cumplen la regla 1 tal cual. Un test de esquema falla si aparece una tabla con
  `tenant_id` sin RLS forzado.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Un `app_user` por tenant | Varias filas por persona: el enlace con Keycloak por `sub` deja de ser único y la preferencia de idioma y la auditoría se fragmentan |
| `tenant_id` nulo en `app_user` con RLS por tenant | Igual necesita la visibilidad por membresía; la columna no aportaría aislamiento |

## Consecuencias

- La regla 1 queda como "toda tabla de negocio con datos de un cliente"; las excepciones son las de este ADR.
- Tabla nueva sin `tenant_id` ⇒ nuevo ADR o ampliar la lista de este (se revisa en code review).

## Cómo se valida

`tests/integration/test_rls.py` (usuarios de otro tenant invisibles, login que solo ve al usuario que entra,
función de invitación sin exposición) y `test_schema.py` (toda tabla con `tenant_id` tiene RLS forzado).
