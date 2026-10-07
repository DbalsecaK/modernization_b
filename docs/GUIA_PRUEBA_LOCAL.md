# Guía de prueba local

Esta guía explica cómo levantar la plataforma en tu máquina y recorrerla de punta a punta en el navegador. Los
escenarios 1 a 5 no tienen costo: usan proyectos de demo reproducidos desde las grabaciones de las aceptaciones. El
escenario 6 usa modelos reales y tiene costo.

## 1. Requisitos

| Herramienta | Versión | Para qué |
|---|---|---|
| Windows 11 con PowerShell | 5.1 o superior | Los scripts de arranque |
| Docker Desktop | Reciente, con al menos 8 GB de memoria asignada | Servicios (PostgreSQL, Keycloak, OpenFGA, OpenBao, MinIO, Neo4j, Redis, ClamAV, Mailpit) y sandboxes |
| Node | 24, con pnpm 10 | La web |
| Python | 3.12, con [uv](https://docs.astral.sh/uv/) | API, worker y datos de demo |
| Git | Reciente | Clonar el repositorio |

Necesitas unos 15 GB libres de disco para las imágenes. Los puertos que usa la plataforma son 5173 (web), 8100 (API),
5440, 6380, 8180, 8190, 8210, 3310, 9100 y 8025 (servicios); deben estar libres.

## 2. Arranque

Desde la raíz del repositorio, en PowerShell:

```powershell
.\scripts\start-local.ps1 -Demo
```

La primera vez construye las imágenes de sandbox (unos 10 a 15 minutos) y reproduce los tres proyectos de demo
(unos 5 minutos). Las veces siguientes basta con `.\scripts\start-local.ps1`, que tarda menos de un minuto.

Si PowerShell no permite ejecutar scripts, usa:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1 -Demo
```

Al terminar, el script muestra las direcciones:

- **Web:** http://localhost:5173
- **API (documentación):** http://127.0.0.1:8100/api/v1/docs
- **Correo de prueba (invitaciones):** http://localhost:8025

| Comando | Qué hace |
|---|---|
| `.\scripts\status-local.ps1` | Estado de los servicios, la API, el worker y la web |
| `.\scripts\stop-local.ps1` | Detiene la API, el worker y la web |
| `.\scripts\stop-local.ps1 -Services` | Además detiene los servicios Docker (los datos quedan en los volúmenes) |
| `.\scripts\start-local.ps1 -Sync` | Después de un `git pull`: reinstala dependencias de Python y Node |
| `pnpm demo:clean` | Borra los proyectos que crean las pruebas E2E (`E2E …`), para que el listado muestre solo los sembrados y los de demo |
| `.\scripts\stop-local.ps1` y luego `pnpm demo:seed --reset` | Vuelve a crear los proyectos de demo desde cero (con el worker detenido; después, arranca de nuevo) |

Los registros de cada proceso quedan en `.local\logs\`.

## 3. Usuarios

En la pantalla de inicio de sesión, la sección **dev-auth** permite entrar como un usuario ficticio sin contraseña.
Solo existe en desarrollo.

| Usuario | Cliente | Qué puede hacer |
|---|---|---|
| **María Torres** | Andes Bank | Administradora del cliente y responsable de los proyectos de demo: ve todo, aprueba compuertas, ve costos |
| **Luis Andrade** | Andes Bank | Analista en los proyectos de demo: lanza ejecuciones y ve código; no descarga código ni ve costos |
| **Carlos Ruiz** | NexTI y Andes Bank | Developer en un proyecto de Andes Bank; cambia de cliente con el selector |
| **Ana Vélez** | Pacific Credit Union | Otro cliente: no ve nada de Andes Bank |
| **Platform Admin** | NexTI | Superadministrador: Operación de plataforma y alta de clientes |

## 4. Proyectos de demo

Entra como **María Torres**: los tres proyectos están en el cliente **Andes Bank** (selector de cliente de la barra
superior) y en **Proyectos** aparecen con el prefijo **Demo ·**. Si entras como Platform Admin, tu cliente activo es
NexTI y no los verás.

| Proyecto | Origen y destino | Veredicto |
|---|---|---|
| Demo · Pagos Sybase → Spring Boot | Un procedimiento almacenado Sybase de pago de órdenes, migrado a Java Spring Boot con PostgreSQL | PROVEN |
| Demo · Pagos COBOL/CICS → Spring Boot | Una aplicación COBOL/CICS ficticia (programas, copybooks, CSD, mapas BMS y trazas) | PARTLY PROVEN |
| Demo · Pagos frontend React y Angular | Las pantallas BMS del caso de pagos, como frontend React y Angular | PROVEN (frontend) |

El pipeline de cada demo corrió completo en tu máquina: inventario, extracción de reglas, compuertas, diseño,
generación de código, compilación en el sandbox y verificación independiente. Lo único que no corrió en vivo son los
modelos: sus respuestas salen de las grabaciones. Por eso la pestaña **Costos** muestra lo que costó la ejecución
cuando se grabó, aunque en tu máquina no se gastó nada.

## 5. Escenarios

### Escenario 1 — Modernización Sybase → Spring Boot (María Torres)

1. Entra como **María Torres** y abre **Proyectos → Demo · Pagos Sybase → Spring Boot**.
2. **Resumen:** el pipeline y su estado.
3. **Especificación:** las reglas extraídas, las historias de usuario, el plan por olas y las preguntas respondidas.
   En **Contratos**, la operación HTTP con las reglas que atiende.
4. **Arquitectura:** el contexto, el servicio, las entidades y puertos, la decisión de diseño y los chequeos del
   veredicto.
5. **Código:** navega los archivos Java generados. Cada archivo indica las reglas que implementa; un clic en una regla
   abre su comparación. Descarga el zip.
6. **Origen ↔ destino:** regla por regla, las líneas del procedimiento Sybase junto al código Java, y el comportamiento
   de ambos en cada caso del golden master.
7. **Validación:** el veredicto PROVEN con sus seis chequeos y el paquete de pruebas descargable.
8. **Ejecuciones:** el historial de la ejecución, con las compuertas que aprobaste y quién las lanzó (Luis Andrade).
9. **Costos:** el consumo por fase, agente y modelo.

### Escenario 2 — COBOL/CICS con pantallas (María Torres)

1. Abre **Demo · Pagos COBOL/CICS → Spring Boot**.
2. **Inventario:** el grafo Transacción → Programa → Mapa. Recorre un flujo de negocio paso a paso, enfoca una regla y
   prueba el análisis de impacto.
3. **Diseño UI:** la pantalla de terminal del legado junto a su prototipo en un marco aislado. Comenta el prototipo.
4. **Especificación → Pantallas:** cada campo con su tipo, longitud, si es obligatorio y si es editable.
5. **Validación:** el veredicto PARTLY PROVEN. Es el techo correcto: el golden master sale de trazas exportadas y el
   legado no se puede ejecutar aquí, así que las entradas nuevas no se pueden comprobar.

### Escenario 3 — Frontend React y Angular (María Torres)

1. Abre **Demo · Pagos frontend React y Angular**.
2. **Código:** la carpeta `frontend/` con las páginas, el cliente tipado y el contrato `openapi.json`.
3. **Validación:** los veredictos `frontend-react` y `frontend-angular`, con los chequeos de compilación, pantallas,
   campos, acciones y accesibilidad.

### Escenario 4 — Vista general (María Torres)

1. **Dashboard:** cambia entre las vistas ejecutiva, de entrega y de administrador.
2. **Buscador** (barra superior): escribe `Pagos`, `RULE-001` o `architect`.
3. **Notificaciones** (campana): los veredictos nuevos y lo que espera tu acción. Marca todo como leído.
4. **Mis tareas**, **Consumo y costos**, **Configuración IA**, **Catálogo** y **Administración**.

### Escenario 5 — Permisos y aislamiento

1. Cierra sesión y entra como **Luis Andrade**: ve los proyectos de demo y su código, pero la pestaña **Costos** le
   pide un permiso y en **Código** no aparece la descarga.
2. Entra como **Ana Vélez**: no ve ningún proyecto de Andes Bank, ni en el listado ni en el buscador.
3. Entra como **Platform Admin**: en el menú aparece **Operación de plataforma**, con workers, colas y trabajos
   fallidos.

### Escenario 6 — Modo real, con modelos (opcional, con costo)

Este escenario corre el pipeline con modelos reales a través de OpenRouter. La grabación equivalente costó unos
3 USD. Necesitas una clave de OpenRouter propia.

1. Entra como **María Torres** → **Configuración IA → Conexiones** y crea una conexión OpenRouter pegando tu clave en
   el formulario. La clave se guarda en OpenBao: no la escribas en ningún otro lugar.
2. Prueba la conexión y define un presupuesto en **Consumo y costos** (por ejemplo 5 USD con corte al 100%).
3. Genera los archivos de entrada con `pnpm demo:inputs`. Quedan en `.local\demo-inputs\`.
4. Crea un proyecto con el **asistente**: modernización, origen COBOL/CICS y BMS, destino Spring Boot.
5. En **Insumos**, sube `.local\demo-inputs\pagos-cobol-cics.zip`.
6. Entra como **Luis Andrade** y lanza la ejecución desde **Ejecuciones**. El worker debe estar en marcha
   (`status-local.ps1`).
7. Vuelve como **María Torres** para responder las preguntas y aprobar las compuertas, desde **Mis tareas** o desde la
   pestaña Ejecuciones.

El caso Sybase (`pagos-sybase.zip`) necesita un motor Sybase vivo para el golden master, que no forma parte del
entorno local. Por eso el modo real se prueba con el caso COBOL/CICS, que trae sus trazas.

### Escenario 7 — Lo nuevo de la verificación (modo real, con costo)

La cobertura del legado, los quirks del motor, las decisiones firmadas y la cobertura del destino **no aparecen en
los proyectos de demo**: las demos reproducen el golden master desde grabaciones y compilan en un sandbox simulado, y
eso no mide cobertura. Se ven en una ejecución real de un procedimiento Sybase con el motor Sybase local y las
imágenes de sandbox reales. El caso real del cliente llegó a PROVEN con 65 USD acumulados en varios reintentos
(un reintento desde una fase costó entre 1 y 5 USD): define antes un presupuesto en **Consumo y costos**.

| Qué revisar | Dónde |
|---|---|
| Cobertura del legado y quirks del motor | **Ejecuciones**, tarjeta de la fase **Caracterización**: «legacy coverage: …» y «engine quirks: N …» (el texto completo al pasar el mouse) |
| Huecos de cobertura sin caso | Al empezar **Verificación** aparece una pregunta en **Ejecuciones → Preguntas de esta ejecución** (y en **Mis tareas**): «Keep them as not proven» deja el veredicto en PARTLY PROVEN; «Sign them as unreachable» los firma con tu nombre. Escribe el motivo en el comentario. Responden owner, arquitecto, analista o revisor de negocio |
| Qué no prueba el veredicto | **Validación**, tarjeta **«Lo que esto no prueba»**: ramas sin caso, quirks sin caso y código del destino que ningún caso ejecuta (cobertura del destino; nunca bloquea) |
| Fila «Legado cubierto» | **Validación**, en los chequeos del veredicto, después de responder la pregunta |
| Código citado de cada regla | **Especificación → Reglas →** una regla **→ Citas en el legado → Ver código** |
| Documentos de la generación | **Código**: el árbol muestra primero el proyecto y aparte **«Documentos de la generación»** (hallazgos, `docs/legacy-engine.md`, notas de convergencia). Mientras la generación corre, un aviso arriba lo indica |
| Evidencia de un agente que agotó intentos | Si pasa, la pregunta trae los paneles **Análisis de la plataforma**, **Diagnóstico**, **Código del último intento** y **Diferencia con la versión anterior** |

La firma final **C4** sigue en **Ejecuciones** (owner o arquitecto, nunca quien lanzó la ejecución); antes de firmar,
lee **«Lo que esto no prueba»** en Validación.

### Escenario 8 — Origen RPG / IBM i (solo análisis)

Desde R1 la plataforma lee programas RPG (RPG III, RPG IV fijo, mixto y libre), sus DDS y el CL que los arranca. El
golden master de RPG llega con R2: una ejecución RPG no puede pasar de la caracterización.

1. Comprime el espacio de trabajo ficticio del repositorio:
   `Compress-Archive packages\adapters\source\rpg\tests\fixtures\cooperativa\* .local\demo-inputs\cooperativa-rpg.zip`
2. Crea un proyecto con el **asistente**: modernización, origen **RPG (IBM i)**.
3. En **Insumos**, sube el zip. Si el insumo es rechazado por las extensiones de RPG (`.rpgle`, `.pf`, `.clle`…),
   avísame: la carga de esas extensiones todavía no se probó de punta a punta.
4. Lanza la ejecución y abre **Inventario** cuando termine esa fase: programas, subrutinas y procedimientos
   exportados, archivos PF/LF como tablas, la pantalla DSPF con su tecla F3, el reporte PRTF y el CL que llama a
   `CALCINT` y envía `ENVIAREP`. La extracción de reglas que sigue usa modelos (con costo): puedes detener la
   ejecución después del inventario.

## 6. Problemas frecuentes

| Síntoma | Qué hacer |
|---|---|
| `Docker is not running` | Abre Docker Desktop y espera a que diga *running* |
| Un puerto ocupado | Cierra el programa que lo usa, o cambia el puerto en `infra/docker-compose/.env` y vuelve a arrancar |
| `uv sync` falla con archivos bloqueados (OneDrive) | Pausa la sincronización de OneDrive y repite con `-Sync` |
| La web no carga o la API no responde | Revisa `.local\logs\web.err.log` y `.local\logs\api.err.log` |
| Una demo falla a mitad | Detén todo con `stop-local.ps1`, ejecuta `pnpm demo:seed --reset` y vuelve a arrancar |
| La demo dice *A worker is running* | La demo corre el pipeline en su propio proceso: detén el worker con `stop-local.ps1` y repite |

## 7. Qué todavía no se puede probar

| Funcionalidad | Cuándo |
|---|---|
| Golden master de RPG (conexión a IBM i o trazas, elegido por proyecto) | R2 |
| Programas RPG interactivos (pantallas 5250) y su destino web | R3 |
| Quirks del motor de RPG | R4 |
| Cobertura y quirks en los proyectos de demo | No aplica: las demos reproducen grabaciones (ver escenario 7) |
| Inicio de sesión con un tenant real de Entra ID | Requiere credenciales del cliente |
