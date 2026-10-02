# ADR-0031 — SCIM, Oracle en .NET y revisión de seguridad del endurecimiento

- **Estado:** Aceptada · 2026-10-02
- **Secciones:** 8.4 (packs de destino), 13 (identidad: SCIM), 15 (seguridad), 20
- **Relacionadas:** ADR-0017 (pack .NET), ADR-0021 (Oracle), ADR-0022 (identidad empresarial), ADR-0023
  (endurecimiento)

## Contexto

Quedan pendientes menores de hitos anteriores:

- **SCIM:** la sección 13 lo pide junto al aprovisionamiento JIT. Keycloak no trae SCIM nativo.
- **Oracle en el pack .NET:** M8b lo hizo para Spring Boot.
- **Revisión de seguridad del endurecimiento:** M9a dejó pendiente una revisión adversarial de lo construido.

La prueba de identidad con un tenant real de Entra ID necesita credenciales de un tenant de prueba que la plataforma
no tiene; queda fuera de este hito.

## Decisión

- **Endpoint SCIM 2.0 en la plataforma** (`/scim/v2`), por tenant:
  - recursos `Users` y `Groups` (RFC 7643 y 7644), con filtros `eq` sobre `userName`, `externalId` y
    `displayName`, `PATCH` de pertenencia a grupos y desactivación por `active=false`;
  - el IdP del cliente se autentica con un token de portador por tenant, que se guarda con hash y se crea, rota y
    revoca desde Identidad. El token nunca se guarda en claro;
  - los grupos SCIM se traducen a roles con el mismo mapeo de grupos del IdP (`role_assignment.source='scim'`). Un
    usuario desactivado pierde sus sesiones y sus roles, sin borrar su historia;
  - cada cambio se audita.
- **Oracle en el pack .NET**, como en Spring Boot:
  - Oracle.ManagedDataAccess.Core en los adaptadores ADO.NET, tipos neutrales → DDL de Oracle (reutilizando
    `oracle_type`);
  - imagen `nexti-sandbox-dotnet-oracle` sobre Oracle Free 23ai con el SDK de .NET 10 y los paquetes offline, con las
    mismas excepciones de Oracle (red interna y raíz escribible);
  - golden master del objetivo de referencia contra Oracle.
- **Revisión de seguridad:** un revisor adversarial recorre el endurecimiento, la entrega, la licencia, el paquete
  air-gapped, los modelos locales y el SCIM (OWASP ASVS nivel 2). Los hallazgos confirmados se corrigen en este
  hito.

## Consecuencias

- **La gestión de usuarios puede venir del IdP del cliente** sin pasar por invitaciones.
- **Un mismo diseño sale en .NET con SQL Server o con Oracle.**
