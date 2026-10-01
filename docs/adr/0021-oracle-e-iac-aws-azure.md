# ADR-0021 — Oracle en los packs de backend e IaC para AWS y Azure

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 8.4 (packs de destino: persistencia y despliegue), 11.3 (verificación), 15.5 (sandbox), 20 (M8b)
- **Relacionadas:** ADR-0010 (pack Spring Boot), ADR-0017 (contrato de packs y SQL Server en el sandbox)

## Contexto

M8b agrega Oracle como persistencia de destino y el eje de despliegue (IaC para AWS y Azure).

El veredicto de un destino se calcula ejecutando: el código generado se compila, corre sus tests, reproduce el golden
master contra una base real dentro del sandbox y pasa el canario. Así se hace con PostgreSQL en Spring Boot (M4) y
con SQL Server en .NET (M6c). Para Oracle hace falta su motor dentro del sandbox.

La prueba de factibilidad con Oracle Database Free 23ai (imagen `gvenzl/oracle-free`, 1,3 GB) mostró dos límites del
contrato actual del sandbox:

- **Red.** Sin ninguna interfaz que no sea loopback, Oracle no arranca (`ORA-00600 [ksipc: no private ips avail]`).
  Con una red interna de Docker creada para la corrida, arranca en unos 55 s.
- **Disco.** La base preinicializada tiene 3 GB de archivos de datos que Oracle escribe en su lugar. Copiarlos a un
  tmpfs en cada corrida no es viable con la raíz de solo lectura.

## Decisión

- **Oracle Database Free en el sandbox Java** (`nexti-sandbox-java-oracle`). La imagen de Oracle va fijada por
  digest, con el JDK de Temurin y las bibliotecas del pack copiadas encima (como SQL Server en M6c). El script de
  cada corrida arranca la base, crea el esquema, compila, corre los tests y el harness, y la apaga.
- **Dos excepciones del sandbox, solo para las imágenes de motores de base de datos que las piden** (`Limits`):
  - *Red interna por corrida.* Se crea una red `--internal` propia de la corrida y se borra al terminar. No tiene
    salida a internet ni otros contenedores, así que el aislamiento de red es equivalente a `none`.
  - *Raíz escribible y el usuario del motor.* El contenedor corre con la capa escribible de Docker y con el usuario sin
    privilegios del motor (`oracle`, uid 54321), no como root.

  Se mantiene todo lo demás:
  - sin capacidades y con `no-new-privileges`;
  - límites de CPU, memoria, procesos y tiempo;
  - contenedor efímero (`--rm`);
  - entradas montadas en solo lectura.
- **El pack Spring Boot conoce su base de datos.** Con `database: oracle` cambian:
  - los tipos SQL (NUMBER, VARCHAR2, DATE, TIMESTAMP) y el DDL;
  - el dialecto del harness (URL JDBC, reinicio con `TRUNCATE`, inserciones con `CAST`);
  - la imagen del sandbox;
  - el pedido de los adaptadores, que nombra Oracle.

  Con PostgreSQL los pedidos al modelo no cambian, así que las grabaciones de M4 a M8 siguen valiendo.
- **Pack de despliegue con OpenTofu**, generado de forma determinista desde el diseño y el destino:
  - **AWS:** VPC con subredes privadas, ECS Fargate detrás de un ALB, RDS (PostgreSQL u Oracle) cifrado y privado,
    Secrets Manager y CloudWatch Logs.
  - **Azure:** red virtual, Container Apps, base de datos administrada privada, Key Vault y Log Analytics.

  El mapeo de conceptos legacy a servicios gestionados queda en el README del IaC:

  | Legacy | Servicio gestionado |
  |---|---|
  | Tablas del legado | La base de datos administrada |
  | Programas y procedimientos | El servicio en contenedores |
  | Credenciales | El almacén de secretos |

- **Validación estática sin credenciales de nube**, en el sandbox `nexti-sandbox-iac`:
  - `tofu init` con los proveedores instalados en la imagen (sin red);
  - `tofu validate`;
  - las fitness functions del pack, calculadas por código sobre el HCL generado: cifrado en reposo, base de datos sin
    acceso público, sin secretos en el código, etiquetas obligatorias y logs habilitados.

## Alternativas consideradas

- **Oracle fuera del sandbox, como servicio compartido.** Rompe el aislamiento por corrida: el código generado
  tocaría una base compartida con otras corridas y otros tenants.
- **Solo generar y compilar el código de Oracle, sin base.** Deja el veredicto en PARTLY PROVEN como máximo y no
  prueba el SQL que escribe el agente.
- **Terraform en lugar de OpenTofu.** La licencia BSL de Terraform no permite redistribuirlo libremente en la
  plataforma. OpenTofu es compatible y abierto.
- **Validar el IaC con `plan`.** Necesita credenciales de nube; la validación estática y las fitness functions no.

## Consecuencias

- Una corrida de equivalencia con Oracle tarda más (unos 55 s de arranque) y pide más memoria (3 GB). El CI construye
  y descarga la imagen.
- Oracle en el pack .NET (ODP.NET) usa el mismo mecanismo y queda para un paso posterior si la imagen combinada cabe.
- El IaC no se despliega: se valida. Desplegar es parte de M9.

## Cómo se valida

- Pruebas del sandbox para la red interna y la raíz escribible.
- Pruebas del pack: tipos de Oracle y la referencia de M4 reproducida en Oracle.
- Pruebas del pack de despliegue: validación de OpenTofu y fitness functions.
- `test_acceptance_m8b.py`: la aplicación ficticia con Oracle y su IaC para AWS y Azure.
