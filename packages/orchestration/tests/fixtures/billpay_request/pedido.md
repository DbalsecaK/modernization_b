# Pedido: consulta del estado de una orden de pago (BillPay, ficticio)

Contoso BillPay ya cobra órdenes de pago de servicios por `POST /api/v1/payments`. Los canales necesitan saber, antes
de cobrar, en qué estado está una orden.

## Historia

**Como** canal de atención (web u oficina), **quiero** consultar el estado de una orden de pago de una empresa,
**para** no intentar cobrar una orden que ya fue pagada o que no existe.

## Reglas

1. La consulta recibe el número de orden y el código de la empresa.
2. Si la orden existe, se devuelve su estado tal como está guardado, sin espacios: `P` (pendiente) o `A` (pagada).
3. Si la orden no existe para esa empresa, la respuesta es "no encontrada" (HTTP 404) y no se devuelve ningún estado.
4. La consulta no modifica ninguna orden ni llama al core bancario.

## Criterios de aceptación

- Dada la orden 1001 de la empresa 10 en estado pendiente, al consultarla el estado es `P`.
- Dada la orden 1001 de la empresa 10 ya pagada, al consultarla el estado es `A`.
- Dada una orden que no existe para la empresa 10, la consulta responde "no encontrada".
- Consultar una orden no ejecuta ninguna actualización ni ningún débito.

Todo en este documento es inventado para las pruebas de la plataforma NexTI.
