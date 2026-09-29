# ADR-0008 — Validación de insumos en la API y malware con ClamAV (D-31)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 7.1, 15.4, 19.1, 20 (M2)
- **Relacionadas:** reglas 3 y 5 de `CLAUDE.md`, ADR-0007 (secretos)

## Contexto

M2 recibe los primeros archivos de los clientes: zips de código legacy, documentos y capturas. La especificación
los trata como input hostil (15.4): tamaños y tipos, zip bombs, path traversal, enlaces simbólicos, malware y
secretos, todo antes de que un agente los lea (7.1). No nombra herramientas. Todavía no hay workers (M3).

## Decisión

- **Un único módulo de validación**, `packages/ingest`, determinista y sin red salvo el escáner: detecta el tipo por
  su contenido (no por la extensión), aplica límites de tamaño por tipo, recorre los zips descomprimiendo con tope
  (tamaño real, cantidad de entradas, tasa de compresión), rechaza rutas peligrosas y enlaces simbólicos, valida la
  cabecera de las imágenes (dimensiones máximas), cuenta secretos por patrón (no los guarda) y calcula el sha256.
- **Malware con ClamAV** (`clamd`, protocolo INSTREAM por TCP) en Docker Compose y en CI; en producción, el `clamd`
  del despliegue. Si el escáner no responde, la subida **falla cerrada** (503) y el readiness lo informa.
- **Síncrono en la API** en M2, con límites configurables: validar no es ejecutar un agente (regla 3). Un insumo
  rechazado no llega al object storage; queda su registro con el motivo y la auditoría. En M3 la misma función puede
  correr en un worker para archivos grandes sin cambiar el contrato.
- Los secretos encontrados se **cuentan y se marcan**; el enmascarado antes de enviar contenido a un modelo (15.3)
  llega con los agentes (M3/M4).

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Escaneo en un servicio externo (VirusTotal y similares) | Saca el código del cliente fuera del perímetro: inaceptable para bancos |
| Sin escáner en desarrollo (simulado) | El camino de rechazo quedaría sin probar; ClamAV corre igual en local y en CI |
| Validación asíncrona desde el primer día | Exige una cola y workers que llegan en M3; el tamaño de los insumos de M2 cabe en una petición |

## Consecuencias

- Un servicio más en Compose y CI (la imagen de ClamAV descarga firmas al arrancar: varios minutos la primera vez).
- Windows Defender puede poner en cuarentena archivos de prueba con la firma EICAR: los tests la construyen en tiempo
  de ejecución y nunca la escriben en el repositorio.

## Cómo se valida

Tests de `packages/ingest` (path traversal, rutas absolutas, enlaces simbólicos, zip bomb, tipo falso, imagen
sobredimensionada, EICAR contra el ClamAV real, secretos) y de integración de la subida (422, nada guardado en el
object storage, rechazo auditado; 503 sin escáner).
