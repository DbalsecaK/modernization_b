# ADR-0007 — Almacén de secretos: API de Vault, OpenBao en desarrollo (D-30)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 12.1, 15.3, 19.1, 20 (M1)
- **Relacionadas:** ADR-0005 (OpenRouter), regla 8 de `CLAUDE.md`

## Contexto

M1 guarda la primera credencial de un cliente: la API key de su conexión con OpenRouter. La especificación exige
"secretos en Vault/KMS, nunca en la base ni en el repositorio" y, en desarrollo, "un equivalente local". HashiCorp
Vault cambió su licencia a BUSL 1.1 en 2023; OpenBao es su bifurcación bajo la Linux Foundation, con licencia
MPL 2.0 y la misma API.

## Decisión

- La plataforma habla la **API KV v2 de Vault** a través de un único módulo, `nexti_model_gateway.secrets`: es el
  único código que escribe o lee las credenciales de los proveedores.
- **Desarrollo y CI:** OpenBao en Docker Compose (modo dev, token de desarrollo generado por `init_env.py`).
- **Producción:** Vault u OpenBao (del cliente o de NexTI) con autenticación de la API por AppRole o Kubernetes;
  sin cambios de código.
- En la base solo queda la ruta del secreto (`vault_path`); la API key no vuelve nunca al navegador (la UI solo
  muestra si está configurada).

> **Nota (M2, 2026-09-28):** el cliente KV pasa a `nexti_core.secrets` para guardar también el token Git de un
> proyecto. Sigue siendo el único módulo que habla con OpenBao; las credenciales de proveedores de modelos solo las
> lee el gateway.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| HashiCorp Vault en desarrollo | Funciona igual, pero la licencia BUSL obliga a revisar cada despliegue; OpenBao evita la duda y el cliente puede seguir usando su Vault |
| Columna cifrada en PostgreSQL | Contradice 15.3 ("nunca en la base") y la llave de cifrado quedaría junto a los datos |
| KMS de una nube | Ata el desarrollo local a una nube; se evalúa por despliegue en M9 |

## Consecuencias

- En modo dev OpenBao guarda los secretos en memoria: al recrear el contenedor hay que volver a cargar las API keys
  (se documenta; producción usa almacenamiento persistente).
- Un servicio más en Compose y en el readiness de la API.

## Cómo se valida

Tests de integración: la API key se guarda en OpenBao, la base solo tiene la ruta, ninguna respuesta de la API la
devuelve, y fuera del gateway ningún módulo la lee (test de arquitectura de M1).
