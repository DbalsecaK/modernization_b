# ADR-0024 — Empaquetado y despliegue de la plataforma

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 14.3 (modelos de despliegue), 14.4 (empaquetado), 14.5 (orden), 15.5 (sandbox), 15.7 (cadena
  segura), 18.x (Operación de plataforma), 20 (M9)
- **Relacionadas:** ADR-0023 (división de M9), ADR-0021 (IaC y fitness functions)

## Contexto

La plataforma solo corre en desarrollo:

- el Compose levanta los servicios (PostgreSQL, Keycloak, OpenFGA y los demás);
- la API, el worker y la web corren en la máquina.

La sección 14.4 pide:

- contenedores con Helm;
- un módulo OpenTofu por nube;
- perfiles de despliegue que eligen servicios administrados;
- versiones exactas por corrida.

La 15.7 pide:

- imágenes firmadas;
- SBOM;
- DAST en el CI.

La 14.5 ordena empezar por el SaaS compartido y por el plano de datos en la nube del cliente.

Hay una dificultad propia de esta plataforma. El worker ejecuta el código generado en sandboxes de Docker (15.5) y en
Kubernetes no hay un Docker por defecto.

## Decisión

### Imágenes y Compose

- **Tres imágenes propias:** `nexti-api`, `nexti-worker` y `nexti-web`.
  - Son multi-etapa, con las bases fijadas por digest.
  - Corren sin root, con raíz de solo lectura donde se puede.
  - La web se sirve con nginx sin root, con la API detrás del mismo origen (el BFF necesita las cookies
    same-site).
- **Compose con perfil `platform`.** La plataforma entera corre en contenedores con las mismas imágenes. Es la prueba
  de humo de las imágenes y el modo on-prem más simple.

### Helm

- **Un chart, `infra/helm/nexti`**, con dos componentes que se encienden por separado:
  - el *plano de control*: API, web y migraciones;
  - el *plano de datos*: worker y sandbox.
- **Perfiles de despliegue** como archivos de valores:
  - `shared-saas` y `dedicated-saas`: los dos planos;
  - `customer-cloud`: solo el plano de datos, con conexión saliente al plano de control (14.3);
  - `on-prem`.

  Los servicios externos (PostgreSQL, Redis, almacenamiento, Keycloak, OpenFGA, OpenBao) son administrados o
  propios según el perfil. El chart no los instala.
- **El sandbox en Kubernetes.** El worker usa un daemon Docker en un sidecar `docker:dind` *rootless*, solo en el pod
  del worker. Los contenedores del sandbox conservan su contrato: sin red, sin privilegios y con límites. Un clúster
  que lo prohíba puede apuntar el worker a un host de sandbox dedicado (`sandbox.dockerHost`).
- **Seguridad de los pods:** `runAsNonRoot`, `readOnlyRootFilesystem`, sin capacidades y `seccompProfile:
  RuntimeDefault`. Cada componente tiene su NetworkPolicy, y los secretos llegan como Secret de Kubernetes,
  normalmente sincronizados desde el almacén de la nube.

### OpenTofu de la plataforma

- **Un módulo por nube, `infra/terraform/{aws,azure}`:**
  - un clúster administrado (EKS o AKS);
  - PostgreSQL administrado, cifrado y privado;
  - Redis;
  - almacenamiento de objetos cifrado;
  - el almacén de secretos;
  - los logs.
- Se valida como la IaC del destino: `tofu validate` en `nexti-sandbox-iac` sin credenciales y las fitness functions
  de `nexti_pack_iac`, en el CI.
- GCP queda para cuando un cliente lo pida; el diseño del módulo es el mismo.

### Cadena segura

- **En cada PR** se construyen las tres imágenes y se genera su SBOM (Syft, formato SPDX).
- **En `main` y en las etiquetas** se suben a GHCR, se firman con cosign *keyless* (OIDC de GitHub) y se adjunta el
  SBOM como atestación.
- **DAST con OWASP ZAP baseline** contra la API y la web en el CI. Las alertas altas fallan el build; las demás quedan
  en el informe.

### Operación de plataforma

- Cada instancia (API o worker) se registra al arrancar y late cada minuto en la tabla `platform_instance`: nombre,
  componente, versión, perfil y último latido.
- La página de Operación de plataforma las muestra con su versión.

## Alternativas consideradas

- **gVisor o Kata como runtime del sandbox en Kubernetes.** Dependen del clúster del cliente. El sidecar rootless
  funciona en cualquier clúster que permita contenedores de usuario, y la interfaz `Sandbox` permite cambiarlo
  después.
- **Instalar PostgreSQL, Keycloak y los demás desde el chart.** Mezcla el ciclo de vida de los datos con el de la
  aplicación. Los perfiles los toman administrados (nube) o de su propio chart (on-prem).
- **Firmar con una llave guardada en el repositorio o en un secreto de GitHub.** *Keyless* con OIDC no deja una llave
  que custodiar y queda en el registro de transparencia.

## Consecuencias

- El CI suma la construcción de imágenes, el SBOM, `helm lint`, kubeconform, `tofu validate` de los módulos y ZAP.
- La firma y la subida a GHCR solo ocurren en `main` y en las etiquetas, así que un PR no publica imágenes.
- El sidecar `docker:dind` rootless es un componente más que mantener al día.

## Cómo se valida

- La prueba de humo del Compose `platform`: las tres imágenes arrancan y la web sirve la API (health) por el mismo
  origen.
- `helm lint` y `helm template` de cada perfil, más kubeconform contra el esquema de Kubernetes, en el CI.
- `tofu validate` y las fitness functions de los módulos AWS y Azure.
- El job de ZAP sin alertas altas.
- Las pruebas de `platform_instance` (registro, latido, la página).
