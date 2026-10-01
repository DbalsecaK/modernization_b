# Plan del hito M9a — Endurecimiento y entrega del proyecto

- **Estado:** en curso (desde 2026-10-01).
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
