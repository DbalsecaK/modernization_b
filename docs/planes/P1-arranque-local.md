# Plan P1 — Arranque local y guía de prueba

- **Estado:** cerrado (2026-10-01), ver la sección 5. Sigue M6c (.NET 10 con SQL Server).
- **Objetivo:** que el aprobador levante la plataforma en su máquina con un solo comando y la recorra de punta a punta
  en el navegador, sin ayuda y sin costo de modelos, siguiendo una guía.
- **Rama:** `p1-arranque-local`, sobre `main` después de mergear P2 (PR #9). Un commit por paso y PR al terminar.
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

## 5. Cierre de P1 (2026-10-01)

| Criterio | Evidencia | Estado |
|---|---|---|
| Un comando deja la plataforma lista en `http://localhost:5173` | `start-local.ps1` en esta máquina: herramientas, `.env`, 9 servicios sanos, migraciones, datos de desarrollo, imágenes, API, worker y web; `status-local.ps1` lo confirma | ✅ |
| Los tres proyectos de demo quedan con su veredicto y sus pestañas con datos | `pnpm demo:seed --reset`: Sybase PROVEN, COBOL/CICS PARTLY PROVEN, frontend React y Angular PROVEN, con todas las compuertas aprobadas; `e2e/demo.spec.ts` recorre validación, código, arquitectura, trazabilidad, costos, ejecuciones, inventario y pantallas, y los permisos de Luis Andrade | ✅ |
| La demo no llama a ningún proveedor de modelos | Grabaciones en modo `replay` (una petición sin grabación falla sin salir a la red) y credencial de marcador | ✅ |
| La guía permite recorrer los escenarios sin ayuda | `docs/GUIA_PRUEBA_LOCAL.md`, con sus pasos verificados contra la plataforma levantada por el script | ✅ |

La reconstrucción de las tres demos tarda unos 5 minutos. En esta máquina las imágenes de sandbox ya existían, así
que la construcción inicial de imágenes (unos 10 a 15 minutos, la misma que hace el CI) no se cronometró aquí.

**Hallazgos de la prueba en limpio, ya corregidos**

- Con el worker en marcha, cada aprobación de la demo encolaba un trabajo que el worker tomaba en paralelo, sin las
  grabaciones. La demo ahora descarta esos trabajos, se niega a correr con un worker vivo, y `start-local.ps1 -Demo`
  la ejecuta antes de levantar el worker.
- La segregación de funciones exige que lance la ejecución alguien distinto de quien aprueba: lanza Luis Andrade
  (analista en las demos) y aprueba María Torres (responsable). C4 necesita el rol de responsable del proyecto.
- La demo no pasaba el grafo de conocimiento al worker y la pestaña Inventario quedaba vacía.
- La web mostraba "Project not found" ante un corte de red transitorio del servidor de desarrollo; ahora reintenta
  los errores que no son 4xx.

**Limitaciones conocidas**

- Los scripts son para Windows; en Linux y macOS se usan los comandos de `pnpm` de la sección Desarrollo del README.
- El modo real se prueba con el caso COBOL/CICS. El caso Sybase necesita un motor Sybase vivo, que no forma parte del
  entorno local.
- La pestaña Costos de las demos muestra el costo que tuvo cada ejecución al grabarse, no un gasto en la máquina local.
