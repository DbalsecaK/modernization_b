# Plan del hito M6c — Pack .NET 10 con SQL Server

- **Estado:** en curso (desde 2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 8.4 (packs de destino), 11.3 (verificación) y 20 (M6c);
  ADR-0017.
- **Rama:** `m6c-pack-dotnet`. Un commit por paso y PR al terminar.
- **Decisiones del aprobador:**
  - 2026-09-30: grabaciones con modelos reales dentro de los 10 USD de M6, M6b y M6c (quedan 6,73).
  - 2026-10-01: avanzar sin detenerse a preguntar; en cada decisión se toma la opción recomendada y se registra
    aquí.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Contrato común de packs de backend; la orquestación deja de nombrar Spring Boot | Uplift de ASPX (M8) |
| Diseño, resultado de build y vistas de equivalencia en paquetes comunes | Entity Framework |
| Pack .NET 10: ASP.NET Core hexagonal, ADO.NET con SQL Server, xUnit | Oracle (M8b) |
| Sandbox `nexti-sandbox-dotnet` con SQL Server 2025 y NuGet sin red | |
| Harness de equivalencia en C# y canario de C# | |
| Prompts `backend-dev-dotnet` y `test-engineer-dotnet` | |
| Destino .NET elegible en el asistente; aceptación con el diseño y el golden master de M4 | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0017 y D-36 |
| 2 | Piezas neutrales en paquetes comunes y contrato de pack; Spring Boot lo implementa sin cambiar sus pedidos |
| 3 | Imagen `nexti-sandbox-dotnet` |
| 4 | Pack .NET: esqueleto, tipos, build con xUnit, harness de equivalencia, canario y sus pruebas con un servicio de referencia |
| 5 | Orquestación por pack, prompts .NET y destino .NET en el catálogo |
| 6 | Aceptación con el diseño y el golden master de M4, grabada (tope 2,50 USD) |
| 7 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El mismo diseño y golden master de M4 generan un destino .NET con veredicto calculado por código | `test_acceptance_m6c.py`, grabada |
| El pack compila, pasa tests y reproduce el golden master con un servicio de referencia | Pruebas del pack en el sandbox |
| Spring Boot no cambia | Replays de M4 y M6, y las pruebas del pack de Java |

## 4. Cierre

**Aceptación grabada.** `test_acceptance_m6c.py` corre el pipeline completo de M4 con el backend cambiado a
`dotnet-10` + SQL Server. Hasta el diseño (C3) y la caracterización usa las respuestas grabadas de M4, porque el
destino no las cambia; desde la generación, las de M6c. Resultado: veredicto **PROVEN** con los 6 chequeos:

- 34 tests pasados en un build limpio (xUnit v3, JUnit XML).
- 11 de 11 reglas verificadas por casos golden.
- 28 casos golden reproducidos en SQL Server.
- 12 entradas nuevas iguales en los dos lados.
- El canario cambió una línea del servicio y un test se puso rojo.
- El legado intacto (SHA-256).

La corrida registra 51 llamadas por 1,53 USD, pero parte de esas llamadas se responden con grabaciones de M4. El
gasto real de M6c fue de unos 1,0 USD. De los 10 USD asignados a M6, M6b y M6c quedan unos 5,7.

**Decisiones tomadas durante la construcción**

- **Sondas de espacio de nombres.** C# no ata una clase a su fichero. Por eso el pack añade un `Probe.cs` que nombra
  el servicio o el adaptador como lo harán el wiring y los controladores. Un espacio de nombres equivocado se vuelve
  un error de compilación que el agente ve y corrige. Los prompts y el pedido del adaptador dicen el espacio de
  nombres exacto.
- **Orden de los ficheros retenidos.** El host, el wiring y los controladores se suman después de todos los
  adaptadores, porque el wiring los referencia a todos.
- **Grabaciones compartidas.** El cliente de grabaciones lee carpetas de otras aceptaciones y nunca escribe en
  ellas (`shared_cassettes`). Así M6c reutiliza las respuestas de M4 sin copiarlas.
- **`/work` con permiso de ejecución** solo en el sandbox .NET, porque xUnit v3 necesita su apphost.
- **SQL Server dentro del sandbox:**
  - `sqlservr` se copia para quitarle la capacidad de fichero que `no-new-privileges` bloquea;
  - arranca desde una semilla preinicializada en un tmpfs;
  - la conexión va por `127.0.0.1,1433`, porque sin red `localhost` falla.
- **Sin rechazo de palabras clave de C#.** Los nombres del diseño que chocan con palabras reservadas se escapan
  con `@` en lugar de rechazarse.
- **La primera aceptación** usaba reglas de referencia sin el pipeline y salió NOT PROVEN. Se cambió al pipeline
  completo de M4, que es lo que el criterio pide.

**Demo local.** `seed_demo.py` incluye la demo «Pagos Sybase → .NET 10», reproducida desde estas grabaciones.

**Limitaciones conocidas**

- La imagen .NET pesa más de 2 GB (SDK y SQL Server). SQL Server tarda unos 20 s en arrancar en cada build de
  equivalencia.
- El paquete NuGet se restaura sin red desde `/opt/nuget`. Un paquete nuevo exige reconstruir la imagen.
- Solo el backend: el pack .NET no genera frontend, que siguen generando los packs de M6b.
