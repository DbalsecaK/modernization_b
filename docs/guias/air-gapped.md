# Guía — Instalación air-gapped: licencia offline y paquete de actualización

Referencias: especificación 14.3 y 14.4, ADR-0030, plan M15 (pasos 2 y 3).

En una instalación air-gapped el cliente opera la plataforma sin salida a internet. NexTI entrega dos cosas
firmadas con la **misma clave Ed25519**:

- la **licencia** (`license.json` + `license.json.sig`);
- el **paquete de actualización** (`nexti-<versión>.tar`), con las imágenes, el chart de Helm y los SBOM.

La clave privada vive fuera de la plataforma, en un equipo de NexTI. La plataforma solo conoce la clave pública.
Nunca se commitea la clave privada ni se la envía al cliente.

## 1. Clave de firma (NexTI, una sola vez)

```bash
export NEXTI_SIGNING_PASSPHRASE=...   # opcional: cifra la clave privada
.venv/Scripts/python -m nexti_core.license keygen --out nexti-license --passphrase-env NEXTI_SIGNING_PASSPHRASE
```

Genera `nexti-license.key` (privada, permisos 0600) y `nexti-license.pub` (pública), e imprime la clave pública en
base64. Ese valor es el que se configura en la plataforma.

## 2. Emitir una licencia (NexTI)

```bash
.venv/Scripts/python -m nexti_core.license sign --key nexti-license.key --passphrase-env NEXTI_SIGNING_PASSPHRASE \
  --customer "Andes Bank" --profile air-gapped --expires 2027-12-31 \
  --max-tenants 2 --max-projects 20 --feature modernization --feature figma-export --out license.json
.venv/Scripts/python -m nexti_core.license verify --public-key nexti-license.pub --license license.json
```

Formato de `license.json` (la firma cubre los bytes exactos del archivo; cualquier cambio la invalida):
`format`, `license_id`, `customer`, `deployment_profile`, `issued_at`, `expires_at`, `max_tenants`, `max_projects`,
`features`. Los campos desconocidos se rechazan.

## 3. Instalar la licencia (cliente)

Montar `license.json` y `license.json.sig` en el pod de la API (por ejemplo, desde un Secret) y definir:

| Variable | Valor |
|---|---|
| `LICENSE_FILE` | ruta de `license.json` |
| `LICENSE_SIGNATURE_FILE` | opcional; por defecto `<LICENSE_FILE>.sig` |
| `LICENSE_PUBLIC_KEY` | clave pública de NexTI (PEM o base64 de los 32 bytes) |

La API verifica la licencia al arrancar (queda registrado en la auditoría de plataforma como `license.verify`) y
muestra el estado en **Operación de plataforma**. Sin `LICENSE_FILE` (SaaS, desarrollo) no se exige licencia.

Estados: `valid`, `missing`, `invalid`, `expired`, `over_limits` y `not_required`. Si la licencia está configurada
y no es válida, la plataforma pasa a **solo lectura**: se puede ver todo, pero iniciar ejecuciones, pedir cambios al
prototipo y crear proyectos o tenants responde `403 license_read_only`. Con una licencia válida, crear el proyecto o
tenant que supera un límite responde `403 license_limit_reached`. Cada rechazo queda auditado.
Para cambiar la licencia se reemplazan los archivos y se reinicia la API.

## 4. Armar el paquete de actualización (NexTI)

Con las imágenes de la versión ya presentes en el Docker local (las de `infra/helm/nexti/values.yaml`: componentes
de la plataforma, el daemon de sandbox y las imágenes de sandbox) y `helm` instalado:

```bash
.venv/Scripts/python scripts/airgap/bundle.py build --key nexti-license.key --passphrase-env NEXTI_SIGNING_PASSPHRASE \
  --sbom-dir sbom/ --out nexti-0.9.0.tar
```

El `tar` contiene `images/*.tar` (`docker save`), `chart/nexti-<versión>.tgz` (`helm package`), `sbom/*`,
`manifest.json` (versión, imágenes con su id y el SHA-256 y tamaño de cada archivo) y `manifest.sig`.

## 5. Verificar y cargar (cliente, sin internet)

```bash
python scripts/airgap/bundle.py verify --public-key nexti-license.pub nexti-0.9.0.tar
python scripts/airgap/bundle.py load --public-key nexti-license.pub nexti-0.9.0.tar \
  --registry registry.local:5000 --push --chart-out charts/
```

`verify` comprueba la firma y todos los hashes sin extraer nada. `load` vuelve a verificar, extrae solo los archivos
del manifiesto (recalculando el hash mientras escribe) y recién entonces hace `docker load`, etiqueta cada imagen con
su nombre original y, con `--registry`, con `registry.local:5000/<nombre>:<tag>` (y la sube con `--push`). Un
archivo cambiado, uno de más o de menos, una ruta insegura o una firma ajena hacen que se rechace todo el paquete.

Después, `helm upgrade` con el chart copiado y el perfil air-gapped, apuntando `image.registry` y
`worker.sandbox.image` al registro local.
