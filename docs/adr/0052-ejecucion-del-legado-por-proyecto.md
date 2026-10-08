# ADR-0052 — Ejecución del legado por proyecto: automática, trazas o sistema del cliente en vivo

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 6.1 fase 9 (caracterización), 11.2 (veredicto), 8.2 (`runner()` del adaptador)
- **Relacionadas:** ADR-0015 (trazas de CICS), ADR-0020 (trazas de ASPX), ADR-0046 (fase no disponible), ADR-0051
  (adaptador RPG), ADR-0007 (secretos); plan de soporte RPG aprobado (R2)

## Contexto

El golden master sale de ejecutar el programa original. Hasta ahora el worker elegía cómo hacerlo solo por los
insumos: si el zip traía trazas, las trazas; si no, el único motor de la plataforma (Sybase ASE). Eso no alcanza para
IBM i: los programas RPG solo corren en el IBM i del cliente, y el cliente decide si da una conexión a un sistema de
prueba (el veredicto puede llegar a PROVEN) o solo exporta trazas (techo PARTLY PROVEN). Las dos formas deben convivir
hasta que las conexiones de cada cliente estén disponibles, y la decisión es del proyecto, no de la plataforma.

## Decisión

1. **Una configuración por proyecto** (`project_legacy_execution`, migración 0026) con el modo:
   - `auto` (o sin configuración): el comportamiento de siempre, por los insumos;
   - `traces`: solo trazas grabadas; sin ellas la fase espera;
   - `live`: el programa corre en un sistema del cliente de un tipo (`kind`), por ahora `ibmi`.
   Vale para cualquier adaptador de origen, no solo RPG.
2. **Dónde está el sistema** va en `config` (host, puerto de los host servers, biblioteca de prueba, biblioteca de
   programas, CCSID, TLS), validado en `nexti_core.legacy_execution`. **Las credenciales** solo en el almacén de
   secretos (`tenants/{t}/legacy/{p}`, JSON usuario/contraseña), escritas por la API y nunca devueltas.
3. **Probar la conexión** abre una conexión TCP al puerto del host server con la misma protección contra direcciones
   internas que las herramientas del tenant (SSRF). Un IBM i suele estar en la red privada del cliente: solo una
   instalación on-premises la permite (`legacy_allow_private_hosts`). Si el host responde y hay credenciales, la
   prueba encola un trabajo: el worker inicia sesión con las credenciales guardadas mediante el runner de su tipo y
   comprueba las bibliotecas, sin llamar a ningún programa, y deja el resultado en la configuración (precisión
   2026-10-08). La API nunca lee las credenciales ni inicia procesos.
4. **El worker nunca cambia de modo en silencio.** `SourceRunner` lee la configuración del proyecto al caracterizar:
   `traces` sin trazas, `live` sin un runner de ese tipo en el worker o sin credenciales, dejan la fase en espera
   (`phaseUnavailable`) con el motivo; corregida la configuración, se reintenta.
5. **El techo sigue en el motor.** Las trazas de IBM i usan el motor `ibmi-trace`, que está en `TRACE_ENGINES`: el
   veredicto con trazas no pasa de PARTLY PROVEN sin ningún cambio en la verificación.
6. **Por etapas.** R2a: la configuración, la API, la tarjeta en Insumos, la elección del runner y las trazas de IBM i.
   R2b: el runner en vivo de IBM i (carga de filas en la biblioteca de prueba, llamada al programa, lectura de
   parámetros y tablas).

## Alternativas consideradas

- **Guardarlo en las preferencias de la composición.** Las preferencias son claves del catálogo que se pasan a los
  agentes como guía; una dirección y unas credenciales no son guía y no deben llegar a un modelo.
- **Un modo por tenant.** Un mismo cliente puede tener proyectos con conexión y otros solo con trazas.
- **Caer a trazas si el sistema en vivo no responde.** Cambiaría el techo del veredicto sin que nadie lo decida.

## Consecuencias

- Un proyecto RPG con trazas ya produce un golden master (PARTLY PROVEN como máximo).
- Un proyecto en `live` espera en la caracterización hasta R2b.
- La conexión de un cliente nunca queda en la base ni en los registros: solo la ruta del secreto.

## Cómo se valida

`apps/worker/tests/test_source_runner.py` (los tres modos y las esperas), `test_inputs.py` (credenciales solo en el
almacén, prueba de conexión sin SSRF, borrado), los casos de permisos de las cuatro rutas y la prueba de trazas de
IBM i en `packages/adapters/source/rpg/tests`.
