# Plan del hito M1 — Configuración IA y consumo

- **Estado:** terminado (2026-09-28). Criterios y evidencia en la sección 7.
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 12, 13 y 20 (M1); ADR-0005 (D-28, OpenRouter).
- **Rama:** `m1-configuracion-ia`, un commit por paso, PR a `main` al terminar.

## 1. Alcance

| Incluye | No incluye (hito) |
|---|---|
| Conexión **OpenRouter** por tenant con "probar conexión" y la API key en el almacén de secretos (OpenBao en desarrollo) | Foundry, Bedrock, OpenAI directos (después, mismo modelo de datos) |
| Catálogo familia → versión → oferta sincronizado desde OpenRouter, con capacidades, ventana de contexto y precios versionados | Evaluaciones y prompts versionados (M3) |
| Perfiles con esfuerzo normalizado (tabla de equivalencias por oferta), máximos, timeout, reintentos y cadena de fallback | Ejecuciones, workers y agentes (M3) |
| Cascada Tenant → Proyecto → Fase → Rol y matriz fase × rol | Capa LangChain sobre el gateway (M3, cuando existan agentes) |
| Políticas por tenant: prohibir OpenRouter, proveedores de destino permitidos o prohibidos, ZDR y no entrenamiento | Reconciliación con la facturación de nubes (opcional, posterior) |
| **Gateway único** (`packages/model_gateway`): política, perfil, fallback, presupuesto y libro de consumo | |
| Libro de consumo append-only, presupuestos (tenant o proyecto, mensual o total) y alertas 80 % y 100 % | |
| Pantallas de Configuración IA y de Consumo y costos conectadas a la API | |

## 2. Decisiones de diseño (sin detener el hito)

1. **Almacén de secretos:** OpenBao (bifurcación de Vault con licencia MPL 2.0, misma API KV v2) en Docker Compose;
   en producción puede ser Vault u OpenBao del cliente. La API key nunca va a la base ni vuelve al navegador
   (ADR-0007, D-30).
2. **Capa de base de datos compartida:** los modelos ORM y `scoped_connection` pasan de `apps/api` a
   `packages/core` (`nexti_core.db`), porque el gateway y, en M3, los workers los necesitan.
3. **Catálogo global** (datos públicos del proveedor, como el catálogo de permisos, ADR-0006): versiones exactas
   (`canonical_slug` con fecha de OpenRouter), ofertas por proveedor de destino con su precio. Lo actualiza la
   sincronización con OpenRouter; la tabla de esfuerzo y los precios manuales solo los edita el superadministrador.
4. **El gateway habla HTTP con OpenRouter** (API compatible con OpenAI) para controlar el enrutamiento
   (`provider.order`, `allow_fallbacks: false`, `zdr`, `data_collection: deny`) y leer `usage.cost`. La capa
   LangChain de 12.7 se agrega en M3 como adaptador *sobre* el gateway, para que nada la saltee.
5. **Presupuesto:** antes de cada llamada, si el gasto del periodo alcanzó el tope con corte duro, el gateway
   rechaza la llamada (`BudgetExceeded`) y la registra; en M3 el orquestador pausa la ejecución en su checkpoint
   al recibir ese error.

## 3. Modelo de datos (migración 0004)

| Tabla | Alcance | Notas |
|---|---|---|
| `provider_connection` | tenant (RLS) | proveedor, nombre, `vault_path` (no el secreto), estado y última prueba |
| `model_family`, `model_version`, `model_offering`, `price_version`, `effort_mapping` | global (catálogo) | versiones fijas; precio versionado con vigencia; esfuerzo → parámetro real por oferta |
| `model_profile` | tenant (RLS) | oferta, esfuerzo, máximos, temperatura, timeout, reintentos, `fallback_profile_id` |
| `model_assignment` | tenant (RLS) | nivel tenant, proyecto, fase o rol → perfil |
| `model_policy` | tenant (RLS) | prohibir OpenRouter, proveedores de destino, ZDR, no entrenamiento |
| `usage_ledger` | tenant (RLS) | append-only; tokens por tipo, latencia, reintentos, fallback, `price_version_id`, costo calculado y costo informado |
| `budget`, `budget_alert` | tenant (RLS) | tope por tenant o proyecto, mensual o total; alertas únicas por periodo |

## 4. Endpoints (`/api/v1/ai`, `/api/v1/usage`)

| Recurso | Operaciones | Permiso |
|---|---|---|
| `connections` | listar, crear (con API key), editar, borrar, `:test` (credenciales y llamada mínima) | `models.configure` |
| `catalog` | listar versiones y ofertas con precio y si la política las permite; `:sync`; `versions/{id}:load-offerings` | ver: `models.configure`; sincronizar: `models.configure` |
| `offerings/{id}/effort-mapping` | ver y editar | ver: `models.configure`; editar: superadministrador |
| `offerings/{id}/prices` | historial y precio manual | ver: `models.configure`; editar: superadministrador |
| `profiles` | CRUD | `models.configure` |
| `assignments` | leer y escribir la matriz (tenant y por proyecto) | `models.configure` |
| `policy` | leer y escribir | `models.configure` |
| `usage` | resúmenes por proyecto, modelo, fase y mes; tokens sin dinero con `usage.view`, costos con `cost.view` | `usage.view` / `cost.view` |
| `budgets` | CRUD y alertas | `cost.view` para ver, `models.configure` para editar |

## 5. Criterios de aceptación de M1 → tests

| Criterio | Test |
|---|---|
| Una llamada de prueba por OpenRouter queda registrada con tokens y costo correctos, y el costo coincide con el informado | Integración con OpenRouter simulado (respuestas reales grabadas) y, con `OPENROUTER_API_KEY_FOR_TESTS`, un test con la API real |
| Una política que prohíbe OpenRouter o exige ZDR se respeta | Gateway: llamada rechazada y registrada; la solicitud lleva `zdr: true` y el proveedor fijado |
| Superar un presupuesto pausa la ejecución | Gateway: al alcanzar el tope la siguiente llamada se rechaza (`BudgetExceeded`), alertas 80 % y 100 % una vez por periodo |
| Un agente no puede llamar a un proveedor sin pasar por el gateway | Test de arquitectura: fuera de `packages/model_gateway` no hay clientes de proveedores ni lecturas de la API key |

## 6. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0007 (OpenBao) y capa de base de datos en `packages/core` |
| 2 | OpenBao en Compose y almacén de secretos |
| 3 | Migración 0004 con RLS, catálogo global y libro append-only |
| 4 | Gateway: cliente OpenRouter, costo, política, cascada, presupuesto (tests con OpenRouter simulado) |
| 5 | Gateway: ejecución con fallback, libro de consumo y alertas |
| 6 | Endpoints de configuración IA y de consumo con matriz de autorización y aislamiento |
| 7 | Test de arquitectura: nada llama a un proveedor fuera del gateway |
| 8 | Web: Configuración IA conectada |
| 9 | Web: Consumo y costos conectado |
| 10 | Llamada real a OpenRouter (con la API key), CI y cierre |

Los diez pasos están hechos, un commit por paso en la rama `m1-configuracion-ia`.

## 7. Cierre de M1 (2026-09-28)

Los criterios de aceptación de la sección 20 de la especificación se cumplen con tests automatizados que corren
en CI contra los servicios reales (PostgreSQL, OpenBao, OpenFGA, Keycloak).

| Criterio | Evidencia (tests) | Estado |
|---|---|---|
| Una llamada de prueba por OpenRouter queda registrada con tokens y costo correctos, y el costo coincide con el informado | `apps/api/tests/integration/test_openrouter_live.py` (API real: libro con tokens, versión de precio y costo calculado igual al de OpenRouter) y `test_gateway.py` (respuestas reales grabadas) | ✅ |
| Una política que prohíbe OpenRouter o exige ZDR se respeta | `test_gateway.py` (ZDR: respaldo en Azure con `zdr: true` y proveedor fijado; OpenRouter prohibido: ninguna llamada, fila bloqueada y auditoría) y `test_endpoints_authz.py::test_the_catalog_shows_prices_and_the_tenant_policy` | ✅ |
| Superar un presupuesto pausa la ejecución | `test_gateway.py` (alertas 80 % y 100 % una vez por periodo; la llamada siguiente se rechaza con `BudgetExceeded` y queda registrada) | ✅ |
| Un agente no puede llamar a un proveedor sin pasar por el gateway | `apps/api/tests/test_architecture.py` (fuera de `packages/model_gateway` solo se importa la fachada; nadie más habla con OpenRouter ni con OpenBao) | ✅ |
| Cada endpoint con test permitido y denegado, y aislamiento entre tenants (regla de CLAUDE.md) | `test_endpoints_authz.py` (matriz de todas las rutas nuevas, meta-test de cobertura y `test_ai_configuration_and_usage_of_another_tenant_are_unreachable`) y `test_rls.py` (tablas de IA) | ✅ |
| La API key nunca vuelve al navegador ni queda en la base | `test_endpoints_authz.py::test_the_api_key_goes_to_the_secrets_store_only` (respuestas, fila y auditoría sin la key; OpenBao con la rotada; borrada al eliminar) y `e2e/ai-config.spec.ts` | ✅ |
| Tokens sin dinero para quien no tiene `cost.view` | `test_endpoints_authz.py::test_tokens_without_cost_view_come_without_money` y `e2e/usage.spec.ts` | ✅ |
| Pantallas de Configuración IA y Consumo y costos conectadas, en inglés y español, accesibles | `e2e/ai-config.spec.ts` y `e2e/usage.spec.ts` (API real y axe), `scripts/check-i18n-keys.mjs` e `i18n.test.ts` | ✅ |

**Capturas** en `docs/m1/`: conexión probada, catálogo con proveedores y precios, perfil probado con una llamada
real (14 tokens de entrada y 1 de salida, USD 0,000003), asignación resuelta y consumo del mes.

**Cambios respecto del plan**

- Migración **0005**: `model_version.canonical_slug` deja de ser único. La sincronización con el catálogo real de
  OpenRouter mostró que alias y variantes (`:thinking`, `:free`, el id sin fecha) comparten el slug canónico de
  la versión a la que apuntan; `provider_slug` sigue siendo único.
- La API usa solo la fachada del gateway (`nexti_model_gateway.service`, que también expone `Pricing` y
  `SecretsConfig`), `gateway` (contexto y errores) y `rules`; la URL de OpenRouter por defecto vive solo en el
  gateway.
- Probar un perfil queda auditado (`ai.profile_test`): hace una llamada real y gasta en la cuenta del cliente.
- Cliente de OpenFGA: reintento ante 409 cuando el relay y el reconciliador escriben la misma tupla a la vez
  (apareció como test intermitente).
- La variable del test real es `OPENROUTER_API_KEY_FOR_TESTS` (en el `.env` de Compose, ignorado por git, o como
  secreto de CI); sin ella el test se omite.

**Limitaciones conocidas (pasan a hitos posteriores)**

- Solo OpenRouter; Foundry, Bedrock y las API directas llegan cuando un cliente lo requiera, sobre el mismo modelo.
- Las pestañas *Prompts* y *Evaluaciones* siguen con datos de ejemplo (M3, con los agentes).
- La pausa de ejecuciones al llegar al presupuesto la hace el orquestador en M3 al recibir `BudgetExceeded`; en
  M1 el gateway rechaza la llamada y la registra.
- La capa LangChain sobre el gateway se agrega en M3 (decisión 4).
- `Field` (primitiva de UI) envuelve el control en su `<label>`: el nombre accesible incluye la ayuda y el valor
  elegido. Conviene asociar etiqueta y ayuda por `id` al revisar las primitivas.
