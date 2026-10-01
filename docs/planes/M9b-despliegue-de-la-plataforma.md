# Plan del hito M9b — Despliegue de la plataforma

- **Estado:** en curso (desde 2026-10-01).
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
