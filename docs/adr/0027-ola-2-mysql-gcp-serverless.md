# ADR-0027 — Ola 2 (primera parte): MySQL, GCP y despliegue serverless

- **Estado:** Aceptada · 2026-10-02
- **Secciones:** 8.4 (packs de destino), 8.5 (matriz de compatibilidad), 8.7 (olas de certificación), 20 (Posterior)
- **Relacionadas:** ADR-0017 (contrato de packs), ADR-0021 (Oracle e IaC para AWS y Azure)

## Contexto

La ola 2 (8.7) suma Quarkus, Next.js, MySQL, GCP y serverless. Son dos tipos de trabajo distintos:

- **variantes de lo que ya existe:** MySQL es una base más del pack Spring Boot, como Oracle; GCP es una nube más del
  pack de IaC; serverless es otra forma de desplegar el mismo servicio;
- **packs nuevos:** Quarkus y Next.js traen su framework, su imagen de sandbox y su generación.

## Decisión

- **La ola 2 se parte en dos hitos.** M12 hace las variantes (MySQL, GCP, serverless) y M13 los packs nuevos
  (Quarkus, Next.js).
- **MySQL como base del pack Spring Boot**, con el mismo contrato que Oracle:
  - imagen `nexti-sandbox-java-mysql`, con MySQL 8.4 fijado por digest y el JDK y las bibliotecas del pack encima;
  - el motor corre en loopback con los datos en `/work`, igual que PostgreSQL. No pide las excepciones de Oracle
    (red interna, raíz escribible) si arranca así; si no, usa las mismas, solo para su imagen;
  - tipos neutrales → DDL de MySQL (DECIMAL, INT/BIGINT, VARCHAR/CHAR, DATE, DATETIME(3), TINYINT(1)), palabras
    reservadas entre comillas invertidas, `sql_mode` estricto y zona horaria fija en la sesión;
  - el golden master se reproduce contra MySQL con el harness compartido;
  - la IaC de Azure suma MySQL Flexible Server; la de AWS ya lo tenía.
- **GCP en el pack de IaC:**
  - VPC con acceso privado a servicios, Cloud Run con conector de VPC, Cloud SQL (PostgreSQL o MySQL) solo con IP
    privada, Secret Manager, Cloud Logging con retención y `labels` en cada recurso;
  - las mismas fitness functions, con sus equivalentes de GCP. Cloud SQL cifra en reposo por defecto (como en Azure);
  - el proveedor `hashicorp/google` se agrega al espejo offline de la imagen, que pasa a `nexti-sandbox-iac:2`.
- **Serverless como forma de desplegar**, elegida con el eje de arquitectura `serverless`:
  - AWS: Lambda (con el adaptador de Spring para funciones), API Gateway HTTP y RDS en subredes privadas;
  - Azure: Container Apps con escala a cero (Functions no ejecuta Spring Boot sin reescritura);
  - GCP: Cloud Run con escala a cero, que ya es serverless;
  - el código generado es el mismo. Las reglas de compatibilidad (8.5) siguen avisando que un batch largo no va en
    funciones.

## Consecuencias

- **Nada de esto toca a los modelos.** Las variantes se prueban con los objetivos de referencia y las grabaciones
  existentes. Una aceptación con modelos nuevos (por ejemplo, el adaptador JDBC escrito para MySQL) necesita una
  grabación aparte.
- **Sube la etiqueta de la imagen de IaC.** El CI, el release y el chart de Helm se actualizan juntos.
- **Quarkus y Next.js quedan en M13** con su propio ADR.
