# Plan P1 — Arranque local y guía de prueba

- **Estado:** en curso (desde 2026-10-01).
- **Objetivo:** que el aprobador levante la plataforma en su máquina con un solo comando y la recorra de punta a punta
  en el navegador, sin ayuda y sin costo de modelos, siguiendo una guía.
- **Rama:** `p1-arranque-local`, apilada sobre `p2-pantallas-conectadas` (PR #9). Un commit por paso y PR al terminar.
- **Decisión del aprobador (2026-09-30):** P2 primero, luego P1. No cambia la especificación ni la API: son
  herramientas de desarrollo y documentación.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| `scripts/start-local.ps1`: servicios Docker, `.env`, migraciones, datos de desarrollo, imágenes de sandbox, API, worker y web | Despliegue fuera de la máquina local (M9) |
| `scripts/stop-local.ps1` y `scripts/status-local.ps1` | Linux y macOS: la guía da los comandos equivalentes, sin script |
| **Datos de demo** (`pnpm demo:seed`): proyectos completos reproducidos desde las grabaciones, a costo cero | Ejecuciones con código real de clientes (el kit Bolivariano sigue pendiente de autorización) |
| Archivos de entrada de las aplicaciones ficticias para probar el modo real desde el asistente | |
| `docs/GUIA_PRUEBA_LOCAL.md` con escenarios paso a paso y README actualizado | |

## 2. Datos de demo

Las grabaciones de las aceptaciones (ADR-0012) se reproducen contra la base de desarrollo, en el cliente ficticio
Andes Bank y con María Torres como responsable. El pipeline corre completo (worker en el mismo proceso, sandboxes
Docker reales, compuertas aprobadas por la API como en las aceptaciones), pero las respuestas de los modelos salen de
las grabaciones: no hay llamadas de red a proveedores ni gasto.

| Proyecto de demo | Grabación | Qué deja para recorrer |
|---|---|---|
| Demo · Pagos Sybase → Spring Boot | M4 | Inventario, especificación, arquitectura, código Java, trazabilidad, validación PROVEN, costos |
| Demo · Pagos COBOL/CICS → Spring Boot | M6 | Grafo CICS, pantallas BMS y prototipos, especificación, arquitectura, código, validación PARTLY PROVEN |
| Demo · Pagos frontend React y Angular | M6b | Pantallas, código React y Angular, contrato OpenAPI, veredictos de frontend PROVEN |

Es idempotente: un proyecto de demo que ya existe no se repite; `--reset` lo borra y lo vuelve a crear.

## 3. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan |
| 2 | Datos de demo (`tools/demo/seed_demo.py`, `pnpm demo:seed`) y entradas de las aplicaciones ficticias (`pnpm demo:inputs`) |
| 3 | Scripts de arranque, estado y parada |
| 4 | Guía de prueba y README |
| 5 | Prueba en limpio en esta máquina, cierre y PR |

## 4. Criterios de aceptación

| Criterio | Evidencia |
|---|---|
| Un comando deja la plataforma lista en `http://localhost:5173` | Corrida de `start-local.ps1` registrada en el cierre |
| Los tres proyectos de demo quedan con su veredicto y todas sus pestañas con datos | `seed_demo.py` verifica los veredictos al terminar; recorrido E2E de las pestañas |
| La demo no llama a ningún proveedor de modelos | Reproducción sin red hacia proveedores (credencial de marcador) y costo grabado, no gastado |
| La guía permite recorrer los escenarios sin ayuda | Recorrido de la guía en limpio |
