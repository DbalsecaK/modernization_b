# Simulador de crédito de consumo — Requisitos

Banco Ficticio S.A. Aplicación de ejemplo: los datos y las reglas son inventados.

## 1. Objetivo

El cliente simula un crédito de consumo antes de solicitarlo: ingresa el monto y el plazo y ve la tasa, la cuota
mensual y el total a pagar.

## 2. Reglas de negocio

- RN-1. El monto debe estar entre 1000.00 y 50000.00 USD, ambos incluidos. Fuera de ese rango la simulación se
  rechaza con el mensaje "El monto debe estar entre 1.000 y 50.000".
- RN-2. El plazo es un número entero de meses entre 6 y 60, ambos incluidos. Fuera de ese rango se rechaza con el
  mensaje "El plazo debe estar entre 6 y 60 meses".
- RN-3. La tasa nominal anual depende del plazo: hasta 12 meses, 12.00 %; de 13 a 36 meses, 14.50 %; de 37 a 60
  meses, 16.00 %.
- RN-4. La cuota mensual se calcula con el sistema francés: cuota = M × i / (1 − (1 + i)^−n), donde M es el monto,
  i es la tasa anual dividida para 12 (en tanto por uno) y n es el plazo. La cuota se redondea a 2 decimales, con la
  mitad hacia arriba.
- RN-5. El total a pagar es la cuota redondeada multiplicada por el plazo, con 2 decimales.
- RN-6. Cada simulación aceptada se guarda con un número correlativo, el monto, el plazo, la tasa, la cuota, el
  total y la fecha y hora, para auditoría. Una simulación rechazada no se guarda.

## 3. Pantallas

- Simulador: campos Monto (USD) y Plazo (meses), ambos obligatorios, y el botón Calcular.
- Resultado: muestra la tasa anual, la cuota mensual y el total a pagar. El botón "Nueva simulación" vuelve al
  Simulador.

## 4. Requisitos no funcionales

- La simulación responde en menos de 1 segundo.
- Los importes se muestran con 2 decimales.
