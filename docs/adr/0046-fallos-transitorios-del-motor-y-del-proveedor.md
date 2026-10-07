# ADR-0046 — Fallos transitorios del motor legado y del proveedor de modelos

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 11.1 (ejecución de la corrida), 7 (pasarela de modelos), 6.1 fase 9 (caracterización)
- **Relacionadas:** ADR-0009 (cola), ADR-0034 (reintento de corridas), ADR-0035 (reintento por fase)

## Contexto

La corrida real que cerró en PROVEN perdió dos noches por fallos que no eran del código ni del modelo:

1. **El motor legado tarde.** Con el equipo sin memoria, Sybase no respondió en 300 segundos; la caracterización
   lanzó "fase no disponible" y la corrida quedó esperando a una persona. La API no permitía reintentar una corrida
   en espera y hubo que reencolarla a mano en la base de datos.
2. **Un corte del proveedor.** Dos respuestas 503 seguidas de OpenRouter agotaron en unos 15 segundos los reintentos
   de la pasarela (dos por perfil, espera máxima de 8 s) y el trabajo cerró la corrida "después de errores
   repetidos".

## Decisión

1. **Motor tarde, reintento en la fase.** `LegacyUnavailableError.transient` distingue un motor que no arrancó o no
   respondió a tiempo (`LegacyEngineTimeoutError` en el adaptador Sybase) de uno que no existe o una repetición sin
   grabación. La caracterización reintenta un fallo transitorio tras 60 y 180 segundos, con un evento visible en
   cada espera, antes de esperar a una persona.
2. **Reencolar sin SQL.** `POST /runs/{id}:retry` sobre una corrida en espera por "fase no disponible" la vuelve a
   encolar tal cual (sin reiniciar fases ni compuertas), auditado como cualquier reintento.
3. **Paciencia con el proveedor.** Cuando todos los perfiles de la cadena fallan solo por causas transitorias
   (timeout, 429 o 5xx), la pasarela espera y prueba la cadena otra vez: 30 s, 60 s, 2 min y 4 min. Una negativa o
   una denegación de política falla de inmediato, como antes.

## Consecuencias

- Una corrida soporta cortes del proveedor de hasta unos 7,5 minutos y motores tardíos de unos 4 minutos sin
  intervención; cada espera queda registrada.
- Las grabaciones no cambian: ninguna llamada grabada falla ni ningún motor grabado llega tarde.
- Pendiente (plan aprobado, mejora de la caracterización): plazo por invocación sin progreso y reutilización del
  motor entre intentos.

## Cómo se valida

`test_characterization.py` (motor tarde dos veces y luego graba; motor que nunca llega espera), `test_gateway.py`
(corte 503 superado con paciencia; un 400 falla sin esperar), `test_runs_api.py` (reencolar una corrida en espera).
