# ADR-0017 — Pack .NET 10 con SQL Server y un contrato común de packs de backend

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 8.4 (packs de destino), 11.3 (verificación), 20 (M6c)
- **Relacionadas:** ADR-0010 (pack Java Spring Boot), ADR-0014 (hitos de packs), ADR-0012 (grabaciones)

## Contexto

M6c agrega el destino .NET 10 con SQL Server. La orquestación hoy importa el pack de Spring Boot directamente:
- arma el cableado de Spring;
- extrae bloques de código Java de las respuestas;
- nombra los adaptadores `Jdbc<Puerto>`;
- usa el harness y el canario de Java.

El modelo de diseño y las vistas de equivalencia viven dentro del pack de Java, aunque no dependen del lenguaje.

## Decisión

- **Un contrato de pack de backend.** Lo que depende del lenguaje pasa a cada pack:
  - el esqueleto, el cableado y qué archivos esperan a que existan los servicios;
  - las rutas del servicio, del test y de cada adaptador;
  - el bloque de código de una respuesta, los mensajes a los agentes y sus prompts;
  - el build con tests, el golden master en el sandbox y el canario.

  La generación y la verificación eligen el pack por `target.backend`. Spring Boot implementa el contrato con
  exactamente los mismos pedidos al modelo, así las grabaciones de M4 y M6 siguen valiendo.
- **Piezas neutrales en paquetes comunes:**
  - el diseño (`Design`) pasa a `nexti_core.spec.design`; sus nombres rechazan las palabras reservadas de Java y de
    C#;
  - el resultado de un build y la lectura del reporte JUnit pasan a `nexti_sandbox.build`;
  - las vistas de equivalencia (máscaras, vista esperada y vista real) pasan a `nexti_core.spec.equivalence`.
- **Pack .NET 10 (`nexti_pack_dotnet`):**
  - ASP.NET Core con controladores y la misma arquitectura hexagonal que Spring Boot;
  - persistencia con ADO.NET (`Microsoft.Data.SqlClient`), sin Entity Framework;
  - los adaptadores reciben una sesión de base de datos (`Db`) con una conexión y su transacción, así cada caso del
    golden master corre en una transacción local que una rechazo deshace, como en el legado;
  - tests con xUnit v3 y reporte JUnit;
  - un harness de equivalencia en C# escrito por la plataforma, con fakes de los programas externos
    (`DispatchProxy`);
  - un canario con mutaciones de C#.
- **Sandbox `nexti-sandbox-dotnet`:**
  - SDK de .NET 10 copiado de la imagen oficial, sobre SQL Server 2025 (Ubuntu 22.04), sin red al ejecutar;
  - los paquetes NuGet se restauran al construir la imagen, con versiones fijas que los proyectos generados usan
    tal cual;
  - SQL Server queda preinicializado en la imagen: arranca solo para el harness, con su base en `/work`. La conexión
    usa `127.0.0.1,1433`, porque `localhost` no resuelve bien sin red;
  - el límite de memoria del sandbox .NET es de 3 GB.
- **Tipos:**

  | Neutral | C# | SQL Server |
  |---|---|---|
  | decimal | `decimal` | `DECIMAL(p,s)` |
  | entero | `int` / `long` | `SMALLINT` / `INT` / `BIGINT` |
  | texto | `string` | `NCHAR(n)` / `NVARCHAR(n)` / `NVARCHAR(MAX)` |
  | fecha | `DateOnly` | `DATE` |
  | fecha y hora | `DateTime` / `DateTimeOffset` | `DATETIME2` / `DATETIMEOFFSET` |
  | booleano | `bool` | `BIT` |

- **Salida canónica del harness:** decimales en cultura invariante, booleanos en minúscula, fechas ISO y nombres de
  campo como el diseño, para que la comparación con el golden master sea la misma que con Java.

## Alternativas consideradas

- **Entity Framework Core.** Más código generado y una capa que esconde el SQL. ADO.NET deja el SQL a la vista,
  igual que JDBC en el pack de Java, y simplifica la equivalencia.
- **Un sandbox con SQL Server en otro contenedor.** Requiere red entre contenedores; el sandbox no tiene red.
- **Copiar el modelo de diseño en el pack .NET.** Dos copias divergen; un diseño aprobado en C3 debe servir a
  cualquier pack.

## Consecuencias

- Agregar un pack de backend es implementar el contrato; la orquestación no cambia.
- La imagen .NET pesa unos 4 GB.
- La verificación .NET tarda más que la de Java, porque cada corrida del harness arranca SQL Server.

## Cómo se valida

- Las pruebas del pack .NET compilan, testean y reproducen el golden master de M4 con un servicio de referencia
  escrito a mano.
- La aceptación genera el destino .NET desde el diseño y el golden master de M4, y obtiene un veredicto calculado por
  código.
- Los replays de M4 y M6 siguen pasando.
