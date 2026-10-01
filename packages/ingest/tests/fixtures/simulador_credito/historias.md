# Historias de usuario — Simulador de crédito

## HU-1 Simular la cuota de un crédito

Como cliente del banco quiero ingresar el monto y el plazo para conocer la cuota mensual antes de solicitar el
crédito.

Criterios de aceptación:

Escenario: Cuota de un crédito a 12 meses
  Dado un monto de 10000.00 y un plazo de 12 meses
  Cuando simulo el crédito
  Entonces la tasa anual es 12.00
  Y la cuota mensual es 888.49
  Y el total a pagar es 10661.88

Escenario: Cuota de un crédito a 24 meses
  Dado un monto de 5000.00 y un plazo de 24 meses
  Cuando simulo el crédito
  Entonces la tasa anual es 14.50
  Y la cuota mensual es 241.25

Escenario: Monto menor al mínimo
  Dado un monto de 500.00 y un plazo de 12 meses
  Cuando simulo el crédito
  Entonces la simulación se rechaza con "El monto debe estar entre 1.000 y 50.000"

Escenario: Plazo mayor al máximo
  Dado un monto de 10000.00 y un plazo de 72 meses
  Cuando simulo el crédito
  Entonces la simulación se rechaza con "El plazo debe estar entre 6 y 60 meses"

## HU-2 Guardar cada simulación

Como oficial de cumplimiento quiero que cada simulación aceptada quede guardada para poder auditarla.

Criterios de aceptación:

Escenario: Una simulación aceptada se guarda
  Dado un monto de 10000.00 y un plazo de 12 meses
  Cuando simulo el crédito
  Entonces queda guardada una simulación con la cuota 888.49 y un número correlativo

Escenario: Una simulación rechazada no se guarda
  Dado un monto de 500.00 y un plazo de 12 meses
  Cuando simulo el crédito
  Entonces no se guarda ninguna simulación
