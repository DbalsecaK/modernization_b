# Plan del hito M12 — Ola 2, primera parte: MySQL, GCP y serverless

- **Estado:** cerrado (2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 8.4, 8.5, 8.7 y 20 (Posterior);
  - ADR-0027 y D-46.
- **Rama:** `m12-ola2-datos-nube`, encima de `m11-flujo-3`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0027. El aprobador pidió avanzar de corrido hasta terminar.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| MySQL en el pack Spring Boot (tipos, DDL, sandbox, golden master) | MySQL en el pack .NET |
| MySQL Flexible Server en la IaC de Azure | Quarkus y Next.js (M13) |
| GCP en el pack de IaC con sus fitness functions | GKE (Cloud Run alcanza para un servicio) |
| Despliegue serverless en AWS, Azure y GCP | Reescribir el servicio como funciones |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0027 y D-46 |
| 2 | MySQL: módulo del pack, imagen del sandbox, tipos y golden master |
| 3 | GCP: módulo de IaC, fitness functions e imagen `nexti-sandbox-iac:2` |
| 4 | Serverless: variantes de IaC por nube según el eje de arquitectura |
| 5 | Catálogo (niveles de MySQL, GCP y serverless), CI, release y Helm |
| 6 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Los tipos neutrales se traducen a MySQL y las palabras reservadas van entre comillas | `test_mysql.py` |
| El objetivo de referencia reproduce el golden master contra MySQL en el sandbox | `test_mysql.py` |
| La IaC de GCP valida sin red y cumple las fitness functions | `test_iac.py` |
| La IaC serverless de cada nube valida y cumple las fitness functions | `test_iac.py` |

## 4. Cierre

**Lo que se entrega**

- **MySQL en el pack Spring Boot** (`nexti_pack_spring_boot.mysql`, `MYSQL_PACK`):
  - tipos neutrales → DDL de MySQL 8.4 (DECIMAL, TINYINT…BIGINT con UNSIGNED, CHAR/VARCHAR/TEXT, DATE,
    DATETIME(3) en UTC, BOOLEAN), las 262 palabras reservadas de MySQL 8.4 entre comillas invertidas en el esquema, las
    filas y las lecturas, `sql_mode` estricto y zona horaria `+00:00`;
  - imagen `nexti-sandbox-java-mysql:1` (mysql:8.4 fijado por digest, con Temurin 21 y las bibliotecas del pack). El
    motor corre en loopback con los datos en `/work`: **no pide las excepciones de Oracle**;
  - `backend_pack()` elige el pack por la base del destino.
- **GCP en el pack de IaC** (`nexti_pack_iac.gcp`): VPC con acceso privado a servicios, Cloud Run v2 con salida directa
  a la VPC, Cloud SQL (PostgreSQL, MySQL o SQL Server) solo con IP privada y SSL obligatorio, contraseña en Secret
  Manager, bucket de logs con retención y sink, `default_labels`. Oracle en GCP no tiene IaC y la generación lo dice.
- **MySQL Flexible Server en Azure**, con subred delegada y zona DNS privada.
- **Serverless** según el eje de arquitectura: Lambda con imagen de contenedor y API Gateway HTTP en AWS, Container
  Apps con escala a cero en Azure y Cloud Run con mínimo 0 en GCP.
- **Fitness functions** con sus equivalentes de GCP y de Lambda; imagen `nexti-sandbox-iac:2` con el proveedor google
  7.x en el espejo offline.
- **Catálogo:** MySQL y GCP pasan a certificados. CI, release, Helm y el arranque local construyen las imágenes
  nuevas.

**Evidencia**

- `test_mysql.py`: el objetivo de referencia reproduce **12 de 12** casos del golden master contra MySQL en el sandbox
  y sus 7 pruebas JUnit pasan; las palabras reservadas se prueban de punta a punta con una columna `condition`.
- `test_iac.py`: 13 combinaciones (nube, base, arquitectura) validan con `tofu validate` sin red y cumplen las cinco
  fitness functions; las variantes rotas (Cloud SQL pública, contraseña literal, sin labels, sin retención, Lambda sin
  logs) fallan.
- Las salidas de AWS y Azure que no son serverless quedan idénticas: la grabación de M8b no cambia.

**Cambios respecto del plan**

- Cloud Run usa salida directa a la VPC en lugar de un conector: es la forma recomendada hoy y no necesita otro
  recurso.
- El eje de arquitectura no tiene niveles en el catálogo, así que serverless no se marca como certificado.

**Queda para después**

- Una aceptación con modelos que escriban el adaptador JDBC para MySQL (necesita grabación).
- GCP en los módulos de la propia plataforma (`infra/terraform`).
