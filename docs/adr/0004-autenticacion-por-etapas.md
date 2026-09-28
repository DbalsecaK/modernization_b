# ADR-0004 — Autenticación por etapas: Keycloak mínimo en M0, SSO y MFA en M0b (D-27)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 15.1, 18.7, 20 (M0, M0b)
- **Relacionadas:** D-19 (Keycloak), ADR-0002 (Organizations), regla 11 de `CLAUDE.md`

## Contexto

Para avanzar rápido con las funcionalidades se planteó autenticar al principio contra una base de datos propia
(usuarios y contraseñas en el proyecto) y cambiar a SSO al final. Eso contradice D-19 y la regla 11 (la
plataforma no guarda contraseñas) y obligaría a rehacer el login, las sesiones y los tests, y a migrar
credenciales. La identidad, además, es de la que salen el `tenant_id`, la autorización y la auditoría.

## Decisión

Usar **Keycloak desde M0, con lo mínimo**, y dejar lo empresarial para **M0b**:

- **M0:** Keycloak en Docker Compose con realm importado al arrancar (`infra/keycloak/`); cuentas locales con
  usuario y contraseña **guardadas en Keycloak**; BFF con cookie `httpOnly`, logout, sesión y CSRF. La
  plataforma tiene su **módulo de usuarios y permisos** (usuarios enlazados por `sub`, tenants, membresías,
  roles, permisos, invitaciones, rol por proyecto) sincronizado con OpenFGA.
- **Modo `dev-auth`:** solo con `APP_ENV=development` o `test`, inicia sesión con un usuario sembrado sin
  contraseña y emite la misma cookie. La API no arranca si `dev-auth` está activo en otro entorno; cada uso
  queda en la auditoría marcado como `dev-auth`.
- **M0b** (después de los hitos funcionales y antes de M9, o antes si un piloto lo requiere): SSO con Entra ID
  y otros IdP, MFA, Organizations por tenant, home-realm discovery, "solo SSO", tema Keycloakify y
  configuración por tenant desde Administración. Es configuración de Keycloak y pantallas, sin cambios en la
  API de negocio.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Login propio con contraseñas en la base del proyecto | Contradice D-19 y la regla 11; hay que construir y asegurar hashing, bloqueo, recuperación y sesiones, y luego migrar credenciales y reescribir |
| Keycloak completo desde M0 | Correcto pero más lento: SSO, MFA, Organizations y Keycloakify no son necesarios para desarrollar las funcionalidades |
| Solo `dev-auth` hasta el final | Los tests de aceptación nunca validarían el flujo real con BFF y cookie |

## Consecuencias

- Las pantallas de login, MFA, recuperación e invitación del prototipo quedan como diseño hasta M0b (tema Keycloakify).
- Los criterios de aceptación de SSO y MFA pasan de M0 a M0b.
- La regla 11 no cambia.

## Cómo se valida

- **M0:** login y logout con cuenta local de Keycloak; ningún token en el navegador; el esquema no tiene
  columnas de contraseña ni secretos; la API no arranca con `dev-auth` fuera de desarrollo/test.
- **M0b:** criterios de SSO, MFA y Organizations del hito.
