# ADR-0020 — ASPX / .NET Framework: parser determinista, trazas como golden master y evaluación de uplift

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 8.2 y 8.3 (adaptadores de origen), 11.3 (verificación), 20 (M8)
- **Relacionadas:** ADR-0015 (COBOL/CICS: parser y trazas), ADR-0017 (pack .NET 10)

## Contexto

Las aplicaciones ASP.NET WebForms reparten el comportamiento en dos lugares:

- el markup (`.aspx`): controles, validadores y navegación;
- el code-behind (`.aspx.cs`): los manejadores de eventos con la lógica y el acceso a datos con ADO.NET.

WebForms solo corre en .NET Framework sobre Windows. No existe en .NET 10 y este entorno no tiene contenedores
Windows, así que el legado no se puede ejecutar en el sandbox para observarlo con entradas nuevas.

## Decisión

- **Un adaptador de origen `nexti_adapter_aspx`, determinista:**
  - **Markup.** Un parser de las etiquetas `asp:` da los controles con su `ID`, tipo, texto, largo máximo y modo.
    - Los validadores (`RequiredFieldValidator`, `RangeValidator`, `RegularExpressionValidator`,
      `CompareValidator`) se asocian a su `ControlToValidate`.
    - Los botones dan las acciones; `PostBackUrl` y `Response.Redirect` dan la navegación.
    - Cada página es una especificación de pantalla (4.1). Los campos no tienen grilla, igual que las pantallas del
      Flujo 2.
  - **Code-behind.** Un lector de C# por llaves y firmas encuentra la clase, sus métodos y los manejadores conectados
    desde el markup (`OnClick`, `OnSelectedIndexChanged`).
    - El SQL de `SqlCommand` da las tablas leídas y escritas.
    - Cada manejador, con los métodos que llama de la misma clase o de `App_Code`, es un slice con líneas citables
      para extraer reglas.
  - **Tipos de C# a neutrales:**

    | C# | Neutral |
    |---|---|
    | `decimal` | `decimal(19,4,signed)` |
    | `int` | `integer(32,signed)` |
    | `long` | `integer(64,signed)` |
    | `string` | `text(var,max,utf8)` |
    | `bool` | `boolean` |
    | `DateTime` | `timestamp(local)` |

    El largo de un campo de pantalla sale de su `MaxLength`.
- **Golden master desde trazas grabadas**, como en CICS (ADR-0015).
  - Cada traza es un pedido a una página (los valores de los controles y el evento) con su respuesta (los valores
    mostrados y los mensajes) y los efectos en la base de datos.
  - El veredicto tiene techo PARTLY PROVEN: no hay entradas nuevas observables, y lo declara.
- **Evaluación de uplift frente a reescritura, por archivo.** Es determinista y sale del uso de APIs:
  - *Bloquea el uplift:* `System.Web.UI`, `Page`, `ViewState`, `Session`, controles de servidor y `web.config` de
    WebForms.
  - *Se puede llevar a .NET 10 con cambios menores:* clases sin `System.Web` (la lógica de `App_Code`) y ADO.NET
    (`System.Data.SqlClient` pasa a `Microsoft.Data.SqlClient`).

  La recomendación queda en el inventario para la revisión de C1: reescribir las páginas con los packs de destino y
  conservar la lógica como referencia de las reglas.

## Alternativas consideradas

- **Un runner Windows con .NET Framework.** Es la opción del roadmap. Exige infraestructura Windows que este entorno no
  tiene. El contrato `LegacyRunner` ya permite agregarlo después sin cambiar el adaptador.
- **Compilar el code-behind en Mono.** Mono no soporta todo WebForms y el comportamiento observado podría diferir del
  legado, lo que daría un golden master engañoso.
- **Uplift automático con herramientas de migración.** Para páginas WebForms no es un uplift sino una reescritura:
  .NET 10 no tiene WebForms.

## Consecuencias

- El veredicto de un módulo ASPX es PARTLY PROVEN como máximo hasta que exista un runner Windows. Las trazas que no
  cubren un caso no lo prueban.
- El parser cubre un subconjunto de WebForms: páginas, controles de entrada, validadores, botones, grillas de solo
  lectura y ADO.NET. Las master pages, los controles de usuario y los controles de terceros se detectan y se listan
  como problemas del inventario.

## Cómo se valida

- Pruebas del adaptador con el ejemplo ficticio: inventario, pantallas con validadores, slices citables, tipos y
  evaluación de uplift.
- `test_acceptance_m8.py`: el ejemplo de punta a punta con modelos reales grabados.
