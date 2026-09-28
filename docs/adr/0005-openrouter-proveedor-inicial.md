# ADR-0005 — OpenRouter como primer proveedor de modelos (D-28)

- **Estado:** Aceptada · 2026-09-28
- **Secciones:** 12.1, 12.6, 13.4, 19.1, 20 (M1)
- **Relacionadas:** D-09 (multi-proveedor con gateway único), regla 2 y regla 10 de `CLAUDE.md`

## Contexto

La especificación preveía empezar M1 con tres proveedores (Azure AI Foundry, AWS Bedrock y OpenAI API), cada
uno con su autenticación y su catálogo. Para probar la plataforma se necesita acceso rápido a modelos de
varias familias sin montar primero tres integraciones. OpenRouter da una sola API, compatible con OpenAI, hacia
modelos de muchos proveedores, e informa el costo de cada llamada.

## Decisión

- **OpenRouter es el primer proveedor implementado** (M1) y el que valida la aceptación del hito.
- Es una **conexión más por tenant**, como las demás (12.1): cada cliente decide si la usa en desarrollo,
  pruebas o producción, o si la prohíbe. La plataforma no la reserva a ningún entorno.
- Pasa por el **gateway de modelos único** (regla 2): política, perfil, fallback, presupuesto y libro de
  consumo igual que cualquier otro proveedor. En LangChain se usa como endpoint compatible con OpenAI.
- **Reproducibilidad (regla 10):** la oferta guarda el ID versionado del modelo y el **proveedor de destino
  fijado** (sin enrutamiento libre ni alias "latest"), para que OpenRouter no cambie de proveedor sin aviso.
- **Datos:** las políticas del tenant (12.6) pueden exigir retención cero (ZDR) y no entrenamiento, y limitar
  los proveedores de destino; la conexión solo enruta a los que cumplen.
- **Costo:** el libro de consumo calcula el costo con la tabla de precios versionada y lo concilia con el
  costo que OpenRouter informa en cada respuesta (13.4).
- Foundry, Bedrock y OpenAI se agregan después sobre el mismo modelo de datos, cuando un cliente lo requiera
  y antes de M9.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Empezar con Foundry, Bedrock y OpenAI a la vez | Tres autenticaciones y catálogos distintos antes de poder probar nada; retrasa M1 |
| Un solo proveedor directo (p. ej. OpenAI) | Limita las pruebas a una familia de modelos; la plataforma quiere comparar modelos por fase y rol |
| OpenRouter solo para desarrollo | La decisión es de cada cliente: algunos lo aceptarán en producción con ZDR y proveedores fijados |

## Consecuencias

- Un tercero más ve los prompts cuando un cliente usa OpenRouter; se mitiga con ZDR, proveedores permitidos
  y la política de datos del tenant, y se documenta en el contrato del cliente.
- El catálogo debe distinguir la oferta de OpenRouter (modelo × proveedor de destino) de la oferta directa del
  mismo modelo, con su propio precio.
- Mientras OpenRouter sea el único proveedor, el fallback entre proveedores (12.3) solo puede cambiar de
  proveedor de destino dentro de OpenRouter.

## Cómo se valida (M1)

Una llamada de prueba por OpenRouter queda en el libro de consumo con tokens y costo correctos, y el costo
coincide con el informado por OpenRouter; una política de tenant que prohíbe OpenRouter o exige ZDR se
respeta; un agente no puede llamar a OpenRouter sin pasar por el gateway.
