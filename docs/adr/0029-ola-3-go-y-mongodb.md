# ADR-0029 — Ola 3: Go y MongoDB

- **Estado:** Aceptada · 2026-10-02
- **Secciones:** 8.4 (packs de destino), 8.5 (matriz de compatibilidad), 8.7 (olas de certificación), 20 (Posterior)
- **Relacionadas:** ADR-0017 (contrato de packs), ADR-0021 (variantes de base), ADR-0028 (Quarkus y Next.js)

## Contexto

La ola 3 (8.7) suma Go y MongoDB. La matriz de compatibilidad (8.5) dice dos cosas:

- Go tiene su propio pack con convenciones idiomáticas: no es una traducción del pack Java;
- MongoDB exige un paso adicional de modelado de agregados: qué se embebe y qué se referencia.

## Decisión

- **Pack Go (`nexti-pack-go`)** con el mismo contrato de packs que Spring Boot y .NET:
  - estructura idiomática: `cmd/server` para el arranque, `internal/domain`, `internal/ports` (interfaces),
    `internal/app` (un servicio por caso de uso) y `internal/adapters` (`net/http` y `database/sql` con pgx);
  - decimales exactos con `github.com/shopspring/decimal` y errores de negocio como valores con código;
  - pruebas con `go test` y su salida JSON convertida al mismo reporte de pruebas que JUnit;
  - golden master con un arnés Go que llama al servicio de cada caso contra PostgreSQL en loopback;
  - canario con cambios de una línea propios de Go;
  - imagen `nexti-sandbox-go:1`, con el toolchain y los módulos en una caché offline (`GOFLAGS=-mod=mod`,
    `GOPROXY=off`) y PostgreSQL en loopback.
- **MongoDB como base del pack Spring Boot**, con el driver oficial de Java en los adaptadores:
  - **modelado de agregados por código:** cada entidad del diseño es una colección. Las entidades que el diseño marca
    como parte de otra se embeben; las demás se referencian por clave. El diseño lo registra como decisión;
  - el golden master se compara por colección, con la misma traducción de filas a documentos en la carga y en la
    lectura (una tabla legada es una colección; una fila, un documento);
  - imagen `nexti-sandbox-java-mongodb:1` con `mongod` en loopback y los datos en `/work`;
  - la IaC usa el servicio compatible de cada nube (DocumentDB en AWS, Cosmos DB for MongoDB en Azure). GCP no tiene
    uno gestionado propio, así que no tiene IaC y la generación lo dice.

## Consecuencias

- **Un mismo diseño (C3) sale en Java (Spring Boot, Quarkus), .NET o Go.** El veredicto mide lo mismo en todos.
- **Con MongoDB la equivalencia es por documento y no por fila.** Las transacciones necesitan un conjunto de
  réplicas, así que el `mongod` del sandbox arranca como réplica de un solo nodo.
- **Las aceptaciones con modelos nuevos necesitan grabación aparte.** Este hito usa objetivos de referencia escritos
  a mano.
