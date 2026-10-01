# Plan del hito M8 — ASPX / .NET Framework

- **Estado:** en curso (desde 2026-10-01).
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
