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

Plantilla: contexto, decisión, alternativas consideradas, consecuencias y cómo se valida.
