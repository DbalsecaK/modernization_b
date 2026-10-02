# Plan del hito M15 — Air-gapped y exportación a Figma

- **Estado:** cerrado (2026-10-02).
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

## 4. Cierre

**Lo que se entrega**

- **Licencia offline** (`nexti_core.license`, `nexti_core.signing`):
  - JSON firmado con Ed25519 (firma separada en `<archivo>.sig`) con cliente, perfil, fechas, máximos de tenants y
    proyectos y funciones; CLI `keygen | sign | verify` que nunca imprime la clave privada;
  - la API la verifica al arrancar (evento `license.verify` en la cadena de auditoría de plataforma) y en cada acción
    protegida (iniciar ejecuciones, crear proyectos o tenants, el chat de prototipos). Vencida, adulterada, de otra
    clave o fuera de límites → `403 license_read_only`, auditado; las lecturas siguen. Sin licencia configurada nada
    cambia;
  - Operación de plataforma muestra el estado de la licencia, su uso y sus funciones (en/es).
- **Paquete de actualización firmado** (`nexti_core.update_bundle`, `scripts/airgap/bundle.py`): imágenes de la
  plataforma y de los sandboxes leídas del chart, el chart empaquetado, los SBOM y un manifiesto con SHA-256 firmado.
  `verify` revisa la firma y cada hash sin extraer; `load` se niega antes de tocar Docker si algo no coincide, y carga
  y reetiqueta por id de imagen. Guía en `docs/guias/air-gapped.md`.
- **Modelos locales:** proveedor `openai-compatible` en el gateway (vLLM, Ollama) con URL base por conexión, clave
  opcional en OpenBao, modelos del servidor o cargados a mano con su precio (0 por defecto) y el mismo registro de
  uso; catálogo por tenant con RLS (migración 0018); verificación de la URL contra SSRF; pantallas de configuración
  de IA (en/es).
- **Perfil `air-gapped` de Helm:** OpenRouter, OSV y la lectura de Figma apagados, hosts privados permitidos para los
  servidores de modelos, y la licencia montada desde un Secret.
- **Exportación a Figma:** `GET /projects/{id}/screens:figma-export` (`project.view`, auditada) devuelve un plugin
  (`manifest.json` sin acceso a red y `code.js` determinista). El plugin crea los estilos del sistema de diseño, una
  página por módulo y un frame por pantalla con sus campos, acciones y estados. Lo descarga el botón de la pestaña de
  diseño de UI.

**Evidencia**

- Licencia: válida habilita; vencida, adulterada, de otra clave, ausente o fuera de límites deja solo lectura con el
  código del problema, y el rechazo queda auditado.
- Paquete: un archivo cambiado, uno de más o de menos, una firma ajena, un manifiesto editado o una ruta insegura se
  rechazan antes de cargar.
- Modelos locales: un servidor compatible responde por el gateway y el registro de uso guarda tokens y costo; otro
  tenant no ve el catálogo local; con OpenRouter apagado los modelos locales siguen funcionando.
- Figma: `code.js` corrió en el sandbox de frontend contra una API de Figma simulada y creó un frame por pantalla con
  sus campos, acciones y estados.
- Helm: `lint --strict` y kubeconform en los cinco perfiles.

**Cambios respecto del plan**

- La licencia se expone dentro del estado de plataforma existente, sin un endpoint nuevo.
- El paquete se arma desde un script porque solo los módulos aislados pueden lanzar procesos (prueba de arquitectura).
- La exportación a Figma usa `project.view`: lleva lo mismo que ya muestra la pestaña de pantallas, sin código.

**Queda para después**

- Un portal de emisión de licencias y la clave pública de producción horneada en la imagen.
- Probar el plugin dentro de Figma de escritorio (se probó contra la API simulada).
