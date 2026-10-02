# Plan del hito M15 — Air-gapped y exportación a Figma

- **Estado:** en curso (desde 2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 12, 14.3, 14.4 y 20 (Posterior);
  - ADR-0030 y D-49.
- **Rama:** `m15-airgapped-figma`, encima de `m14-ola3-go-mongodb`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0030. El aprobador pidió avanzar de corrido hasta terminar.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Licencia offline firmada, verificada por la API, modo solo lectura | Portal de emisión de licencias |
| Paquete de actualización firmado con verificación y carga | Un registro de contenedores propio |
| Proveedor de modelos `openai-compatible` (vLLM, Ollama) y perfil `air-gapped` | Servir modelos dentro de la plataforma |
| Exportación de pantallas a Figma como plugin | Escribir en Figma por API |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0030 y D-49 |
| 2 | Licencia offline: formato, herramienta de firma, verificación, modo solo lectura, API y web |
| 3 | Paquete de actualización: armado, firma, verificación y carga |
| 4 | Modelos locales y perfil `air-gapped` de Helm |
| 5 | Exportación a Figma: plugin generado, API y botón en la web |
| 6 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Una licencia válida habilita; una vencida, adulterada o de otra clave deja la plataforma en solo lectura | Pruebas de la licencia |
| Un paquete con un archivo cambiado o una firma ajena se rechaza antes de cargar nada | Pruebas del paquete |
| El gateway llama a un servidor compatible con OpenAI y registra el uso | Pruebas del gateway |
| El plugin crea un frame por pantalla con sus campos, acciones y estados | Pruebas de la exportación |
