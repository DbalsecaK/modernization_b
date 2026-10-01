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
