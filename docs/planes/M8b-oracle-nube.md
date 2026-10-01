# Plan del hito M8b — Packs Oracle y nube (AWS, Azure)

- **Estado:** cerrado (2026-10-01).
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

## 4. Cierre

**Lo que se entrega**

- **Oracle en el pack Spring Boot.** El destino `spring-boot` + `oracle` elige el pack `SpringBootOraclePack`:
  - tipos Oracle (NUMBER, VARCHAR2, DATE, TIMESTAMP) y el DDL del esquema;
  - los identificadores reservados (por ejemplo `number`) van entre comillas en el DDL, los INSERT y los volcados;
  - el harness de equivalencia corre contra Oracle Database Free 23ai en la imagen `nexti-sandbox-java-oracle:1`.
- **Pack de despliegue `nexti-pack-iac`.** Genera OpenTofu por código desde el diseño y el destino:
  - AWS: VPC, ECS Fargate detrás de un ALB con HTTPS, RDS cifrado y privado, Secrets Manager y CloudWatch;
  - Azure: red virtual, Container Apps, PostgreSQL Flexible, Azure SQL u Oracle Database@Azure, Key Vault y Log
    Analytics;
  - un README con el mapeo de los conceptos del legado a los servicios gestionados.
- **Validación sin credenciales** en `nexti-sandbox-iac:1`. Corre `tofu init` y `tofu validate` con los proveedores
  de la imagen y sin red. El código calcula 5 fitness functions: cifrado en reposo, base no pública, sin secretos en
  el código, etiquetas y logs.
- **En el pipeline:**
  - la generación escribe la IaC en `infra/<nube>/`;
  - la verificación, también la de Flujo 2, le da su propio veredicto `iac-<nube>` con su paquete de prueba;
  - la pestaña Código muestra la IaC y la de Validación sus 6 chequeos (en/es).

**Aceptación grabada** (`test_acceptance_m8b.py`): la aplicación ficticia de M4 con destino Spring Boot + Oracle +
AWS.

- **Backend en Oracle: PROVEN.**
  - 39 tests en un build limpio;
  - 11 de 11 reglas verificadas por casos golden;
  - los 28 casos golden y las 12 entradas nuevas coinciden;
  - el canario cambió el margen de sobregiro y un caso golden se puso en rojo;
  - el legado intacto.
- **IaC de AWS: PROVEN** con los 6 chequeos.
- Azure (PostgreSQL, SQL Server y Oracle) y AWS con PostgreSQL se validan en las pruebas del pack de despliegue.

La corrida registra 51 llamadas por 1,53 USD en el ledger. Las respuestas de inventario, reglas, diseño y
caracterización se reproducen de las grabaciones de M4. Solo 5 llamadas fueron nuevas (los adaptadores para Oracle),
así que el gasto real queda muy por debajo de los 2 USD asignados.

**Cambios respecto del plan**

- **El sandbox de Oracle no corre con `--network none` ni con los datos en un tmpfs.**
  - Sin interfaz de red, Oracle falla con ORA-00600. Corre en una red `--internal` creada para la corrida, sin
    salida a internet ni a otros contenedores.
  - Los datafiles de unos 3 GB necesitan la raíz escribible.
  - El sandbox admite estas dos excepciones y un usuario propio solo cuando el pack las pide (ADR-0021).
- **OpenTofu se copia como binario** sobre Alpine. La imagen oficial termina con `ONBUILD exit 1`. Los proveedores
  quedan desempaquetados como único espejo, sin acceso a registros.
- **Oracle en .NET (ODP.NET) queda para después.** El destino .NET sigue con SQL Server.

**Limitaciones conocidas**

- La IaC se valida sin credenciales. Lo que solo muestran un `plan` o un despliegue no se comprueba (cuotas, nombres
  ya tomados, permisos de la cuenta), y el veredicto lo declara como no probado.
- GCP y Kubernetes genérico no tienen generador: un destino con esas nubes no recibe IaC.
- La imagen de Oracle tarda alrededor de un minuto en arrancar, así que la verificación en Oracle es más lenta que
  en PostgreSQL.
