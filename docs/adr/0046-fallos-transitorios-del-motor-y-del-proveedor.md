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


## Precisión 3b (2026-10-07): caracterización rápida

Medido en la corrida real: unos 25 a 27 minutos de Sybase por intento (un `docker exec` y un `isql` nuevos por
cada uno de los 78 casos), la suite entera repetida tras dos casos con error del motor, y un intento colgado 87
minutos esperando caso por caso a un motor saturado. Desde 3b el adaptador Sybase:

1. Ejecuta los casos en **una sesión de isql por lote** (25 casos), con una marca antes de cada caso que separa la
   salida; cada caso sigue empezando por reiniciar los datos, como cuando corría solo. stderr va a stdout en orden
   para que un mensaje del motor quede en el caso que lo produjo. Un caso cortado por el tiempo se ejecuta solo.
2. **Recuerda lo observado** por huella del caso (mismo código, esquema y stubs): una corrección de la suite solo
   ejecuta los casos que cambiaron, y si ninguno cambió no arranca el motor.
3. Corta como **fallo transitorio** una grabación en la que el motor deja de responder (ni un caso del lote, o un
   caso solo sin respuesta), de modo que la fase reintenta con un motor nuevo en lugar de esperar horas.

Validado con Sybase real: la grabación del fixture se reproduce exactamente.
