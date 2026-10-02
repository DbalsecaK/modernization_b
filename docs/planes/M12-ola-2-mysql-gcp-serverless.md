# Plan del hito M12 — Ola 2, primera parte: MySQL, GCP y serverless

- **Estado:** en curso (desde 2026-10-02).
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
