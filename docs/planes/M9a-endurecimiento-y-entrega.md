# Plan del hito M9a — Endurecimiento y entrega del proyecto

- **Estado:** cerrado (2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`, secciones:
  - 6.1: fases 12 y 13;
  - 6.3: strangler fig;
  - 7.2: entrega de Flujo 2;
  - 15.7;
  - 16.2;
  - 20: M9, dividido por el ADR-0023 y D-42.
- **Rama:** `m9-entrega`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0023. El aprobador pidió avanzar sin preguntas.
  - El endurecimiento lo calcula código: secretos, dependencias con OSV, reglas estáticas por lenguaje y tiempos de
    los tests. No bloquea la entrega.
  - La entrega arma el release con el código, el plan de corte strangler fig y el informe.
  - El push va a una rama nueva del repositorio del cliente, con dulwich y el token de OpenBao, si hay repositorio y
    quien corre tiene `code.push`. Si no, el release queda en ZIP.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Fase 12: informe de endurecimiento calculado por código | Revisión del informe por el agente auditor (después de medir el informe) |
| Fase 13 en los dos flujos: release, plan de corte, push a una rama del cliente | Merge o pull request automático en el repositorio del cliente |
| Tabla `release` y endpoint de push desde la pestaña Código | Despliegue del código del cliente (decisión del cliente) |
| Web: informe en Validación, releases y push en Código (en/es) | Despliegue de la plataforma (M9b) |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0023 y D-42 |
| 2 | Paquete `nexti_hardening`: reglas estáticas, secretos (gitleaks en el sandbox), dependencias (OSV), tiempos de tests e informe |
| 3 | Paquete de entrega: plan de corte strangler fig desde el diseño y push con dulwich (servidor Git de prueba) |
| 4 | Orquestación: fases `hardening` y `delivery` en los dos flujos; tabla `release` |
| 5 | API: informe de endurecimiento, releases y `code:push` (OpenFGA, auditoría, aislamiento) |
| 6 | Web: informe en Validación, releases y botón *Push* en Código (en/es) |
| 7 | Aceptaciones que llegan a `completed`, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El informe encuentra el secreto, la dependencia vulnerable y el patrón inseguro; un proyecto limpio no tiene hallazgos | Pruebas de `nexti_hardening` |
| El release llega a una rama nueva del repositorio y su commit tiene el código, el plan y el informe | Pruebas de entrega con el servidor Git de prueba |
| Una corrida de modernización llega a `completed` con informe y release | Aceptaciones M4, M6c y M8b |
| `code:push` solo para quien tiene el permiso, en su tenant, y auditado | `test_endpoints_authz.py` |

## 4. Cierre

**Lo que se entrega**

- **Endurecimiento (fase 12)** con el paquete `nexti_hardening`. El informe se calcula por código sobre todo lo
  generado (backend, frontend e IaC) y tiene cuatro partes:
  - **Reglas estáticas por lenguaje:** SQL armado por concatenación, TLS sin verificar, credenciales en el código o
    en la configuración, CORS abierto y modo debug. Los tests no se analizan.
  - **Secretos:** gitleaks corre en `nexti-sandbox-hardening:1` sin red. El informe guarda la regla, el archivo y
    la línea, nunca el secreto.
  - **Dependencias:** las de Maven, NuGet y npm se consultan en OSV. El chequeo se apaga con `OSV_URL` vacío y
    entonces el informe dice "no comprobado".
  - **Tiempos de los tests** del build limpio, leídos del JUnit del paquete de prueba.

  El informe se guarda en `hardening/report.json` y `hardening/REPORT.md`. Informa y no bloquea la entrega.
- **Entrega (fase 13, en los dos flujos)** con el paquete `nexti_delivery`:
  - **Plan de corte strangler fig**, calculado desde el diseño (`docs/cutover/PLAN.md` y `routing.yaml`):
    - cada programa legado con su endpoint nuevo;
    - los pasos *shadow*, *primary* y retiro;
    - la capa anticorrupción.
  - **Push con dulwich** a una rama `nexti/` nueva. El commit va encima de la rama base del cliente, bajo
    `modernized/<contexto>/`, sin tocar el resto del repositorio y nunca sobre la rama base. El token sale de
    OpenBao y no aparece en ningún mensaje.
  - **Release en ZIP** cuando no hay repositorio, cuando quien lanzó la corrida no tiene `code.push` o cuando el push
    falla (con la razón).
  - **Tabla `release`** (migración 0014) con cada entrega.
- **API:**
  - el informe de endurecimiento y los releases, con `code.view`;
  - el push desde la pestaña Código, con `code.push`, auditado y con su caso de OpenFGA y su prueba de aislamiento.
- **Web:** el informe en Validación, y el botón *Push* habilitado y la lista de releases en Código (en/es).

**Evidencia**

- **Pruebas de los paquetes:**
  - el proyecto inseguro tiene sus hallazgos y el de referencia ninguno;
  - gitleaks encuentra un secreto armado durante la prueba sin guardarlo;
  - el push va a un servidor Git HTTP levantado en el proceso: rama nueva, legado intacto, release anterior
    reemplazado, repositorio vacío;
  - el token no aparece en los errores.
- **Fases en el pipeline:**
  - informe guardado;
  - ZIP sin repositorio y ZIP sin `code.push`;
  - push a una rama nueva;
  - push fallido con la razón.
- **Aceptaciones M4 y M8b** (reproducción sin gasto): la corrida llega a `succeeded`. La de M8b comprueba el informe,
  el plan de corte y el release en ZIP.
- **API:** casos de OpenFGA de los tres endpoints, más un push real a un servidor Git de la prueba y el rechazo a otro
  tenant.

**Cambios respecto del plan**

- **El administrador del tenant puede hacer push.** OpenFGA le da `code.push` a través del tenant, como al
  desarrollador del proyecto. El caso de autorización lo refleja.
- **URLs de repositorio y servidores Git de prueba.** Las URLs son siempre `https` (una restricción de la base). En un
  entorno local con hosts privados permitidos, una URL `https` a loopback se trata como `http`. Eso deja probar con
  un servidor Git local; en producción no cambia nada.

**Limitaciones conocidas**

- La revisión del informe por el agente auditor de seguridad queda para después de medir el informe por código.
- No se abre un pull request ni se hace merge automático: la rama queda para el proceso del cliente.
- Las reglas estáticas cubren los patrones que el generador puede introducir. No reemplazan un SAST completo.
