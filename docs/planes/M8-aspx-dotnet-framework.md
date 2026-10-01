# Plan del hito M8 — ASPX / .NET Framework

- **Estado:** cerrado (2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 8.2 y 8.3 (adaptadores de origen), 11.3 (verificación) y
  20 (M8); ADR-0020.
- **Rama:** `m8-aspx`. Un commit por paso y PR al terminar.
- **Decisiones (opción recomendada, 2026-10-01; el aprobador pidió avanzar sin preguntas):**
  - **Ejemplo ficticio «Transferencias».** Una aplicación WebForms con dos páginas (`.aspx` y code-behind
    `.aspx.cs`), una clase de lógica en `App_Code` y un `web.config`. No contiene código de clientes.
  - **Sin runner Windows.** WebForms no corre en Linux ni en .NET 10, y este entorno no tiene contenedores Windows. El
    golden master sale de trazas grabadas, como en CICS (ADR-0015): techo PARTLY PROVEN, y el veredicto lo dice.
  - **Uplift frente a reescritura.** Una evaluación determinista lista lo que impide llevar cada archivo tal cual a
    .NET 10 (System.Web, ViewState, controles de servidor) y lo que sí puede llevarse (la lógica de `App_Code`). Las
    páginas se reescriben con los packs existentes (.NET 10 y React).
  - **Presupuesto de grabación:** hasta 3 USD.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Adaptador `nexti_adapter_aspx`: detección, inventario (páginas, controles, eventos, tablas), tipos de C# a neutrales, slices por manejador de evento | Ejecutar WebForms en un runner Windows |
| Pantallas desde el markup: campos, validadores (obligatorio, rango, expresión), botones y navegación | ASCX y master pages más allá de su detección |
| Golden master desde trazas grabadas (pedido, respuesta y efectos en datos) | Uplift automático del código |
| Evaluación de uplift frente a reescritura, por archivo | |
| Aceptación grabada del ejemplo de punta a punta | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0020 y D-39 |
| 2 | Ejemplo ficticio «Transferencias» con sus trazas |
| 3 | Adaptador ASPX: parser de markup y de code-behind, inventario, tipos, slices y pantallas |
| 4 | Golden master desde trazas y evaluación de uplift |
| 5 | Orquestación: el adaptador en el pipeline y sus pantallas en la fase UI |
| 6 | Aceptación grabada y demo local |
| 7 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El markup de cada página da su especificación de pantalla, con sus validadores | Pruebas del adaptador |
| El code-behind da slices por evento con las líneas citables | Pruebas del adaptador |
| La evaluación de uplift separa lo que bloquea de lo que se puede llevar | Pruebas del adaptador |
| El ejemplo pasa de ASPX a .NET 10 + React con un veredicto calculado por código | `test_acceptance_m8.py`, grabada |

## 4. Cierre

**Aceptación grabada.** `test_acceptance_m8.py` corre el pipeline de modernización completo con el ejemplo
«Transferencias» y reescribe la aplicación a .NET 10 + SQL Server con frontend React.

- **Inventario y especificación:**
  - El adaptador ASPX inventaría 2 páginas, 1 clase de App_Code y 2 tablas, con su evaluación de uplift: las páginas
    se reescriben, App_Code se lleva tal cual y Web.config se reemplaza.
  - Las 2 páginas quedan como pantallas con sus validadores.
  - Los agentes extraen y revisan las reglas de los manejadores.
- **Compuertas:** se aprueban C1, C2, C3 y C4 por la API.
- **Veredicto del backend: PARTLY PROVEN.** Es el máximo posible sin runner Windows (ADR-0020):
  - 28 tests en un build limpio;
  - 8 de 8 reglas verificadas por casos golden;
  - los 12 casos de las trazas reproducidos;
  - el canario cambió el chequeo de saldo y el test del saldo exacto se puso en rojo;
  - el legado intacto.

  Las entradas nuevas no se observan porque WebForms no corre aquí.
- **Veredicto del frontend:** PROVEN con los 6 chequeos.

La corrida final hace 37 llamadas por 1,10 USD. El gasto real de M8 fue de unos 2,2 USD, contando el intento anterior al
ajuste de las trazas, dentro de los 3 USD asignados.

**Lo que destapó la grabación**

- **El archivo de fuentes no aceptaba `.aspx`, `.cs` ni `.config`.** Ningún adaptador reconocía el proyecto; se
  agregaron esas extensiones.
- **Dos detalles de las trazas de una página:**
  - el número de la transferencia que la página pasa en su redirección (`Comprobante.aspx?numero=N`) es parte de lo
    que responde, y la traza debe registrarlo;
  - una página que muestra un error de negocio en vez de completar es un rechazo (`returns: -1`) y solo muestra el
    mensaje.

**Cambios respecto del plan**

- El lector de trazas de CICS se generalizó a cualquier motor de trazas (`cics-trace`, `aspx-trace`). El veredicto
  queda en PARTLY PROVEN para los dos.
- El sandbox .NET tiene 1500 s (antes 900), por los runners lentos del CI. Cuando un build de equivalencia no
  compila, el veredicto dice por qué.

**Limitaciones conocidas**

- No hay runner Windows: el techo es PARTLY PROVEN y solo se comparan los casos trazados.
- El parser cubre un subconjunto de WebForms: páginas, controles de entrada, validadores, botones, enlaces y
  ADO.NET. Master pages, controles de usuario y de terceros se detectan como problemas del inventario.
- El uplift es una evaluación: no se ejecuta un uplift automático del código.
