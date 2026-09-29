# ADR-0012 — Respuestas de modelos grabadas en el CI; evaluación con modelos reales a demanda

- **Estado:** Aceptada · 2026-09-29 (decisión del aprobador)
- **Secciones:** 11, 12.7, 13, 20 (M4), 21.4
- **Relacionadas:** ADR-0005 (OpenRouter), regla de `CLAUDE.md` "toda llamada a modelos pasa por el gateway"

## Contexto

Desde M4 los agentes llaman a modelos reales. Un CI que llamara a modelos en cada PR gastaría dinero en cada push y
daría resultados distintos entre corridas, con tests que fallan por la variabilidad del modelo y no por el código.
A la vez, la evaluación contra la spec de referencia (21.4) solo tiene sentido con modelos reales.

## Decisión

- El gateway (`packages/model_gateway`) gana un modo **grabar / reproducir** para tests: en reproducción responde con
  la respuesta grabada para la misma petición (clave: agente, modelo, parámetros y un hash de los mensajes) y falla
  si no la tiene; en grabación llama al proveedor y guarda la respuesta. Fuera de tests el modo no existe (la
  configuración de producción no lo acepta).
- Las **grabaciones del repo** solo contienen respuestas sobre la aplicación ficticia; las de la referencia de un
  cliente quedan en su kit (ADR-0011).
- El **CI de cada PR** reproduce: sin costo y determinista.
- La **evaluación con modelos reales** corre a demanda (local o en un job manual) con un **tope de presupuesto por
  corrida** (5 USD por defecto) aplicado por el gateway; al alcanzarlo, la corrida se detiene y lo informa.
- La prueba de humo contra OpenRouter real de M1 (`test_openrouter_live.py`) se mantiene en el CI.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Modelos reales en cada PR | Costo en cada push y tests inestables |
| Modelos falsos escritos a mano | No prueban los prompts ni el parseo de respuestas reales |

## Consecuencias

- Cambiar un prompt obliga a regrabar las respuestas afectadas (un comando lo hace con presupuesto acotado).
- Las métricas publicadas en el catálogo salen solo de corridas reales.

## Cómo se valida

- Test del gateway: en reproducción sin grabación, la llamada falla y no toca la red.
- La evaluación se detiene al alcanzar el tope de presupuesto.
