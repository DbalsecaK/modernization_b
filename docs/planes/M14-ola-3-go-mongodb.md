# Plan del hito M14 — Ola 3: Go y MongoDB

- **Estado:** cerrado (2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 8.4, 8.5, 8.7 y 20 (Posterior);
  - ADR-0029 y D-48.
- **Rama:** `m14-ola3-go-mongodb`, encima de `m13-ola2-quarkus-nextjs`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0029. El aprobador pidió avanzar de corrido hasta terminar.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Pack Go con su imagen, pruebas, golden master y canario | Go con bases distintas de PostgreSQL |
| MongoDB como base del pack Spring Boot, con modelado de agregados | MongoDB en .NET, Quarkus o Go |
| IaC de MongoDB en AWS y Azure | Un servicio MongoDB gestionado en GCP |
| Catálogo, CI, release y Helm | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0029 y D-48 |
| 2 | Pack Go: esqueleto, imagen, objetivo de referencia, golden master y canario |
| 3 | MongoDB: modelado de agregados, adaptadores, imagen, golden master e IaC |
| 4 | Catálogo, CI, release y Helm |
| 5 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El esqueleto Go compila y sus pruebas corren en el sandbox | Pruebas del pack Go |
| El objetivo de referencia en Go reproduce el golden master | Pruebas del pack Go |
| El objetivo de referencia con MongoDB reproduce el golden master por colección | `test_mongodb.py` |
| La IaC de MongoDB valida y cumple las fitness functions en AWS y Azure | `test_iac.py` |

## 4. Cierre

**Lo que se entrega**

- **Pack Go (`nexti-pack-go`):**
  - estructura idiomática: `internal/domain`, `internal/ports`, `internal/app` (un servicio por caso de uso con
    `Execute(ctx, req)`), `internal/adapters/pg` (pgx sobre `database/sql`, la transacción viaja en el contexto) y
    `internal/adapters/httpapi` (net/http; un error de negocio responde 422), cableado en `cmd/server`;
  - tipos como punteros para conservar los nulos del legado, dinero solo con `shopspring/decimal`;
  - `go test -json` convertido a JUnit, así que el resultado de la compilación es el mismo que en los otros packs;
  - arnés de equivalencia en dos partes: un runtime fijo y un pegamento generado por código desde el diseño;
  - canario propio de Go; prompts `backend-dev-go` y `test-engineer-go`;
  - imagen `nexti-sandbox-go:1` (Go 1.26, PostgreSQL 17 en loopback, módulos en caché offline, `GOPROXY=off`).
- **MongoDB en el pack Spring Boot (`MONGODB_PACK`):**
  - una colección por entidad, nada embebido y referencias por clave (el diseño aún no marca "parte de"); índice
    único por clave y validador `$jsonSchema` con tipos, largos y enumerados; la regla queda como decisión del
    diseño;
  - Decimal128 a la escala del tipo y fechas en UTC; transacción por hilo con `MongoTransaction`;
  - imagen `nexti-sandbox-java-mongodb:1` con `mongod` 8.0 como réplica de un nodo en loopback, con los límites
    normales del sandbox;
  - IaC: DocumentDB en AWS (cifrado, privado, TLS, logs de auditoría) y Cosmos DB for MongoDB en Azure (sin acceso
    público, endpoint privado, cadena de conexión en Key Vault). GCP no tiene IaC y la generación dice por qué.
- **Catálogo:** Go y MongoDB pasan a certificados; CI, release, Helm y el arranque local construyen las imágenes.

**Evidencia**

- Pack Go: el objetivo de referencia compila, sus 7 pruebas pasan y reproduce **12 de 12** casos del golden master;
  el canario se detecta.
- MongoDB: el objetivo de referencia reproduce **12 de 12** casos comparando por colección; un adaptador JDBC no
  compila en su imagen; un decimal escrito como double lo rechaza el validador.
- IaC: aws/mongodb y azure/mongodb validan sin red y cumplen las fitness functions; las salidas anteriores quedan
  idénticas.

**Queda para después**

- Embeber entidades cuando el diseño tenga la marca "parte de".
- Inventario de destinos Go en el Flujo 4.
- Aceptaciones con modelos reales sobre Go y MongoDB (necesitan grabación).
