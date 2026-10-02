# ADR-0030 — Air-gapped y exportación a Figma

- **Estado:** Aceptada · 2026-10-02
- **Secciones:** 5.x (UI, exportar a Figma), 12 (modelos), 14.3 y 14.4 (despliegue y licenciamiento), 20 (Posterior)
- **Relacionadas:** ADR-0005 (OpenRouter), ADR-0024 (empaquetado y despliegue), ADR-0016 (contrato de pantallas)

## Contexto

Quedan dos pendientes de la sección 20:

- **Air-gapped (14.3).** El cliente opera el plano de control y el de datos. Las actualizaciones llegan por paquete
  firmado, la licencia es un archivo firmado (14.4) y los modelos son locales.
- **Exportar a Figma.** La API REST de Figma es de lectura; para escribir hace falta un plugin.

## Decisión

### Air-gapped

- **Licencia offline:**
  - es un archivo JSON firmado con Ed25519, con cliente, perfil de despliegue, vencimiento, tenants y proyectos
    máximos, y funciones habilitadas;
  - la clave pública va en la imagen. La API verifica la licencia al arrancar y la expone en Operación de plataforma.
    Vencida o inválida, la plataforma pasa a solo lectura: se ve todo y no se crean ejecuciones;
  - la firma se hace fuera de la plataforma, con una herramienta de línea de comandos que NexTI usa con su clave
    privada.
- **Paquete de actualización firmado:**
  - un `tar` con las imágenes de la plataforma y de los sandboxes (`docker save`), el chart de Helm, los SBOM y un
    manifiesto con el SHA-256 de cada archivo;
  - el manifiesto se firma con Ed25519, con la misma raíz de confianza que la licencia, porque la firma *keyless* de
    cosign necesita internet;
  - el script de carga verifica la firma y los hashes antes de cargar las imágenes en el registro local.
- **Modelos locales:**
  - un proveedor `openai-compatible` en el gateway, con URL base propia por conexión (vLLM, Ollama u otro servidor
    con la API de chat de OpenAI);
  - el catálogo de modelos de esa conexión se carga a mano (no hay OpenRouter); el costo es cero o el que el tenant
    declare;
  - el perfil `air-gapped` de Helm apaga lo que sale a internet: OpenRouter, OSV y la descarga de Figma.

### Exportación a Figma

- **Plugin de Figma generado por la plataforma:** un ZIP con `manifest.json`, `code.js` y los datos de las pantallas.
- Al correrlo en Figma (escritorio), el plugin crea una página por módulo y un frame por pantalla. Cada frame lleva sus
  campos (etiqueta, tipo, obligatorio), sus acciones como botones y sus estados (vacío, cargando, error, éxito) como
  variantes, con los tokens del sistema de diseño como estilos.
- El código del plugin es determinista y no lleva datos del cliente fuera de las pantallas del proyecto.
- Se prueba ejecutando `code.js` contra una API de Figma simulada en el sandbox de frontend.
- Se descarga con `GET /api/v1/projects/{id}/screens:figma-export`: pide `project.view` (son las mismas pantallas que
  ya lee quien ve el proyecto) y queda auditada (`screens.figma_export`). Sin pantallas responde 404. Una pantalla
  sin estados declarados recibe los cuatro; los colores y tipografías salen del sistema de diseño del proyecto sobre
  los tokens base de NexTI.

## Consecuencias

- **La misma imagen sirve para SaaS y para air-gapped.** Lo que cambia es el perfil y la licencia.
- **La exportación a Figma necesita que una persona corra el plugin.** Figma no ofrece escritura por API.
