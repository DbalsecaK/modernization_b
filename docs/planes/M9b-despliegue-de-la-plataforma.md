# Plan del hito M9b — Despliegue de la plataforma

- **Estado:** cerrado (2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`, secciones:
  - 14.3, 14.4 y 14.5: despliegue;
  - 15.5: sandbox;
  - 15.7: cadena segura;
  - 18.x: Operación de plataforma;
  - 20: M9.

  Decisiones: ADR-0023, ADR-0024, D-42 y D-43.
- **Rama:** `m9b-despliegue`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0024. El aprobador pidió avanzar sin preguntas.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Imágenes de API, worker y web; Compose con perfil `platform` | Un clúster real en una nube (lo crea el cliente con los módulos) |
| Chart de Helm con plano de control y plano de datos, y perfiles de despliegue | GCP (mismo diseño, cuando un cliente lo pida) |
| Módulos OpenTofu de la plataforma para AWS y Azure, validados con fitness functions | Air-gapped y licencias (posterior) |
| SBOM en cada PR; imágenes firmadas (cosign keyless) y SBOM atestado en `main` | Pentest externo (lo contrata el cliente o NexTI fuera del repositorio) |
| DAST con ZAP baseline en el CI | |
| Instancias y versiones en Operación de plataforma | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0024 y D-43 |
| 2 | Imágenes de API, worker y web; Compose con perfil `platform` y prueba de humo |
| 3 | Chart de Helm, perfiles y validación (lint, template, kubeconform) en el CI |
| 4 | Módulos OpenTofu de AWS y Azure con sus fitness functions en el CI |
| 5 | Cadena segura: imágenes y SBOM en cada PR; release firmado en `main`; ZAP baseline |
| 6 | Operación de plataforma: `platform_instance`, latido y página |
| 7 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Las tres imágenes arrancan y la web sirve la API por el mismo origen | Prueba de humo del Compose `platform` en el CI |
| Cada perfil produce manifiestos válidos | `helm lint`, `helm template` y kubeconform en el CI |
| Los módulos de la plataforma validan y cumplen las fitness functions | Pruebas de los módulos (`tofu validate` en el sandbox) |
| Las imágenes tienen SBOM; las de `main` van firmadas | Job de imágenes del CI y workflow de release |
| ZAP baseline sin alertas altas | Job de DAST del CI |
| Operación de plataforma muestra las instancias con su versión | Pruebas de `platform_instance` y de la página |

## 4. Cierre

**Lo que se entrega**

- **Imágenes** (`infra/images`), multi-etapa, fijadas por digest y sin root:
  - `nexti-api`;
  - `nexti-migrate`: las migraciones, que también crean las tablas del checkpointer del worker;
  - `nexti-worker`: la CLI de Docker para los sandboxes, con `TMPDIR` compartido con el daemon en la misma ruta;
  - `nexti-web`: nginx sin root, con la API en el mismo origen y cabeceras de seguridad en todas las respuestas.
- **Compose con perfil `platform`:** la plataforma entera en contenedores con las mismas imágenes. Es la prueba de
  humo en el CI y la instalación on-prem más simple.
- **Chart de Helm** (`infra/helm/nexti`):
  - plano de control: API, web, job de migraciones e ingress de un solo origen;
  - plano de datos: el worker, con el daemon Docker rootless como sidecar nativo, las imágenes del sandbox cargadas
    al arrancar y un volumen compartido para las entradas;
  - pods sin root con raíz de solo lectura, y NetworkPolicies;
  - perfiles `shared-saas`, `dedicated-saas`, `customer-cloud` (solo plano de datos) y `on-prem`.
- **Módulos OpenTofu de la plataforma:**
  - AWS: EKS privado, RDS, ElastiCache, S3, KMS y Secrets Manager;
  - Azure: AKS privado con Entra ID, PostgreSQL Flexible, Redis, storage, Key Vault y Log Analytics.

  Los dos validan sin credenciales y cumplen las fitness functions de la IaC que la plataforma genera.
- **Cadena segura:**
  - en cada PR, SBOM SPDX de las imágenes y DAST con el baseline de ZAP contra la plataforma levantada;
  - en `main` y en las etiquetas, las imágenes de la plataforma, de Keycloak y de los sandboxes se suben a GHCR,
    firmadas con cosign *keyless* y con el SBOM atestado.
- **Operación de plataforma:** cada instancia de la API y del worker late con su versión y su perfil, y la página las
  lista.

**Evidencia**

- **Prueba de humo del Compose `platform`** en local y en el CI: la web sirve la app y la API responde por el mismo
  origen, con la preparación completa (PostgreSQL, Redis, Keycloak, OpenFGA, OpenBao, almacenamiento y ClamAV); el
  worker queda en marcha.
- **Chart:** `helm lint --strict`, más render de los cuatro perfiles y kubeconform estricto contra Kubernetes 1.31.
- **Módulos AWS y Azure:** `tofu validate` sin advertencias y las cinco fitness functions.
- **ZAP baseline:** 0 fallas. Quedan advertencias informativas: `unsafe-inline` de los estilos y COEP no aplicado,
  para no romper los prototipos en iframes.
- **Instancias:** las ven los operadores y no el rol de la aplicación, ni el administrador de un tenant.

**Cambios respecto del plan**

- **La migración tiene su imagen** (`nexti-migrate`), porque la 0007 crea las tablas del checkpointer de LangGraph,
  que es dependencia del worker.
- **`OPENFGA_BOOTSTRAP`** permite que una primera instalación cree el store y cargue el modelo. Después se fijan los
  ids.
- **`OPENFGA_MODEL_FILE`** le dice a la imagen dónde está el modelo.
- **`asyncpg` pasa a ser dependencia explícita del worker.** Antes llegaba por el entorno compartido con la API.

**Limitaciones conocidas**

- GCP no tiene módulo (mismo diseño, cuando un cliente lo pida).
- Air-gapped, licencias y el pentest externo son posteriores o ajenos al repositorio.
- El release firmado corre en `main`: la primera firma real ocurre al fusionar este hito.
- El sidecar del sandbox necesita contenedores privilegiados para su daemon rootless. Un clúster que no los permita
  usa un host de sandbox dedicado (`worker.sandbox.dockerHost`).
