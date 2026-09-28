# ADR-0002 — Keycloak: una Organization por tenant (D-20)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 15.1, 19.2, M0b
- **Relacionada:** D-19 (Keycloak como IdP y broker), ADR-0004 (implantación por etapas)

## Contexto

Cada cliente (tenant) necesita sus propios proveedores de identidad (Entra ID, Okta, SAML), dominios de
correo, modo "solo SSO" y mapeo de grupos a roles. Los usuarios de NexTI trabajan con varios clientes a la vez.
Keycloak ofrece dos formas de separar clientes: un realm por tenant o Organizations dentro de un realm.

## Decisión

- **SaaS compartido:** un realm de la plataforma con **una Organization por tenant**. Cada Organization tiene
  sus IdP y dominios (home-realm discovery por dominio de correo). El token incluye la Organization y de ella
  la API deriva el `tenant_id`.
- **Despliegues dedicados** (nube del cliente, on-prem): una instancia o un realm propio por despliegue; para
  la plataforma sigue siendo un tenant, sin cambios de código.
- **Excepción:** si un cliente del SaaS exige una política que Keycloak solo permite por realm (contraseñas,
  duración de sesión), pasa a realm dedicado.
- **Versión:** Keycloak con Organizations estable (26 o posterior), **fijada** en la imagen y en Helm.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Un realm por tenant | Cientos de realms son pesados de operar (clientes, claves, temas y configuración repetidos) y un usuario de NexTI necesitaría una cuenta por cliente |
| Un realm sin Organizations (grupos por tenant) | No asocia IdP ni dominios por cliente; el home-realm discovery habría que construirlo aparte |

## Consecuencias

- Algunas políticas quedan a nivel de realm (se documenta qué es configurable por tenant y qué no).
- La API siempre toma el tenant de la Organization del token, nunca de un parámetro del cliente.

## Cómo se valida (M0b)

Un IdP por Organization; un dominio "solo SSO" no entra con contraseña; el token trae la Organization; un
usuario con membresía en dos organizaciones solo ve los datos del tenant activo.
