# Plan del hito M8b — Packs Oracle y nube (AWS, Azure)

- **Estado:** en curso (desde 2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 8.4 (packs de destino: persistencia y despliegue) y 20
  (M8b); ADR-0021.
- **Rama:** `m8b-oracle-nube`. Un commit por paso y PR al terminar.
- **Decisiones (opción recomendada; el aprobador pidió avanzar sin preguntas):**
  - **Oracle en el sandbox.** Oracle Database Free 23ai, una imagen fijada por digest con una base
    preinicializada. El JDK de Temurin y las bibliotecas del pack se copian encima, como SQL Server en M6c. Corre sin
    red, con los datos en un tmpfs.
  - **Oracle en Spring Boot primero.** Comparte el diseño y el golden master de M4. Oracle en .NET (ODP.NET Managed)
    va como segundo paso si la imagen combinada cabe en el sandbox; si no, queda para después y se dice.
  - **IaC con OpenTofu** (licencia abierta y compatible con Terraform), generado de forma determinista desde el
    diseño y el destino:
    - AWS: ECS Fargate, ALB, RDS (PostgreSQL u Oracle) y Secrets Manager.
    - Azure: Container Apps, Azure Database for PostgreSQL o Azure SQL, y Key Vault.
  - **Validación estática sin credenciales**, en el sandbox `nexti-sandbox-iac`: `tofu validate` con los proveedores
    instalados en la imagen. Las fitness functions del pack las calcula el código:
    - cifrado en reposo;
    - base de datos sin acceso público;
    - secretos fuera del código;
    - etiquetas obligatorias;
    - logs habilitados.
  - **Presupuesto de grabación:** hasta 2 USD.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Tipos neutrales a Oracle (NUMBER, VARCHAR2, DATE, TIMESTAMP) y esquema DDL en el pack Spring Boot | Desplegar en una nube real |
| Sandbox Java + Oracle Free con harness de equivalencia y canario | PL/SQL como lógica de destino |
| IaC OpenTofu para AWS y Azure desde el diseño, con mapeo de conceptos legacy a servicios gestionados | GCP y Kubernetes genérico |
| Validación estática del IaC y fitness functions en el sandbox | |
| Pestaña Código: el IaC entre los archivos generados | |
| Aceptación: la aplicación ficticia con Oracle y su IaC para AWS y Azure | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0021 y D-40 |
| 2 | Imagen `nexti-sandbox-java-oracle` y persistencia Oracle en el pack Spring Boot (tipos, DDL, adaptadores JDBC, harness) |
| 3 | Pack de despliegue: generadores OpenTofu para AWS y Azure, imagen `nexti-sandbox-iac`, validación y fitness functions |
| 4 | Orquestación: el destino Oracle y la fase de despliegue (IaC) en la generación y la verificación |
| 5 | Aceptación grabada y CI |
| 6 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| La aplicación ficticia genera y verifica su destino con Oracle | `test_acceptance_m8b.py` (golden master de M4 en Oracle) |
| Su IaC para AWS y Azure pasa la validación y las fitness functions del pack | Pruebas del pack de despliegue y la aceptación |
