# Registros de decisiones de arquitectura (ADR)

Cada decisión relevante tiene un ADR y una fila en la sección 22 de la especificación
(`docs/ESPECIFICACION_PLATAFORMA.md`). Un ADR no se edita para cambiar la decisión: se crea uno nuevo que lo
reemplaza y se marca el anterior como "Reemplazado por ADR-NNNN".

| ADR | Decisión | Estado |
|---|---|---|
| [0001](0001-autorizacion-openfga.md) | D-15 — Autorización con OpenFGA | Aceptada |
| [0002](0002-keycloak-organizations-por-tenant.md) | D-20 — Keycloak: una Organization por tenant | Aceptada |
| [0003](0003-componentes-ui-shadcn-radix.md) | D-14 — Componentes UI con shadcn/ui sobre Radix | Aceptada |
| [0004](0004-autenticacion-por-etapas.md) | D-27 — Autenticación por etapas (Keycloak mínimo en M0, SSO/MFA en M0b) | Aceptada |
| [0005](0005-openrouter-proveedor-inicial.md) | D-28 — OpenRouter como primer proveedor de modelos | Aceptada |
| [0006](0006-identidad-global-sin-tenant-id.md) | D-29 — Identidad global sin `tenant_id`, con visibilidad por RLS | Aceptada |
| [0007](0007-almacen-de-secretos-openbao.md) | D-30 — Almacén de secretos: API de Vault, OpenBao en desarrollo | Aceptada |
| [0008](0008-validacion-de-insumos-clamav.md) | D-31 — Validación de insumos en la API y malware con ClamAV | Aceptada |
| [0009](0009-cola-procrastinate-postgresql.md) | D-13 — Cola de trabajos con Procrastinate sobre PostgreSQL | Aceptada |
| [0010](0010-primer-pack-java-spring-boot.md) | D-06 — Primer vertical Sybase hacia Java Spring Boot; el destino lo elige cada proyecto | Aceptada |
| [0011](0011-kit-de-referencia-fuera-del-repo.md) | Aplicaciones de referencia de clientes en un kit local, fuera del repositorio | Aceptada |
| [0012](0012-respuestas-grabadas-y-evaluacion-a-demanda.md) | Respuestas de modelos grabadas en el CI; evaluación con modelos reales a demanda | Aceptada |
| [0013](0013-prototipos-react-en-iframe-aislado.md) | Prototipos React reales, compilados en el sandbox y mostrados en un iframe aislado | Aceptada |
| [0014](0014-hitos-de-packs-de-destino.md) | Hitos propios para los packs de destino de la Ola 1 (M6b, M6c, M8b) | Aceptada |
| [0015](0015-cobol-cics-parser-y-trazas.md) | COBOL/CICS: parser determinista de un subconjunto y trazas como golden master | Aceptada |
| [0016](0016-packs-de-frontend-react-y-angular.md) | Packs de frontend React y Angular: contrato OpenAPI, cliente tipado y arnés de pantallas | Aceptada |
| [0017](0017-pack-dotnet-y-contrato-de-packs-de-backend.md) | Pack .NET 10 con SQL Server y un contrato común de packs de backend | Aceptada |
| [0018](0018-flujo-2-insumos-citables-y-veredicto.md) | Flujo 2: insumos citables, integraciones del tenant y veredicto por criterios | Aceptada |
| [0019](0019-backlog-jira-azure-devops.md) | Backlog en Jira y Azure DevOps: sincronización idempotente y ciclo del bug | Aceptada |
| [0020](0020-aspx-parser-trazas-y-uplift.md) | ASPX / .NET Framework: parser determinista, trazas como golden master y evaluación de uplift | Aceptada |
| [0021](0021-oracle-e-iac-aws-azure.md) | Oracle en los packs de backend e IaC para AWS y Azure | Aceptada |
| [0022](0022-identidad-empresarial-organizations-sso-mfa.md) | Identidad empresarial: Organizations por tenant, SSO, MFA por nivel de autenticación | Aceptada |
| [0023](0023-endurecimiento-entrega-y-division-de-m9.md) | Endurecimiento y entrega del proyecto; división de M9 | Aceptada |
| [0024](0024-empaquetado-y-despliegue-de-la-plataforma.md) | Empaquetado y despliegue de la plataforma | Aceptada |
| [0025](0025-flujo-4-validacion-independiente.md) | Flujo 4: validación independiente (IV&V) de una migración hecha por un tercero | Aceptada |
| [0026](0026-flujo-3-anadir-a-lo-existente.md) | Flujo 3: añadir funcionalidad a una aplicación existente | Aceptada |
| [0027](0027-ola-2-mysql-gcp-serverless.md) | Ola 2 (primera parte): MySQL, GCP y despliegue serverless | Aceptada |
| [0028](0028-ola-2-quarkus-y-nextjs.md) | Ola 2 (segunda parte): Quarkus y Next.js | Aceptada |
| [0029](0029-ola-3-go-y-mongodb.md) | Ola 3: Go y MongoDB | Aceptada |
| [0030](0030-air-gapped-y-exportacion-a-figma.md) | Air-gapped y exportación a Figma | Aceptada |

Plantilla: contexto, decisión, alternativas consideradas, consecuencias y cómo se valida.
