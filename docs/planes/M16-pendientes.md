# Plan del hito M16 — Pendientes: SCIM, Oracle en .NET y revisión de seguridad

- **Estado:** en curso (desde 2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 8.4, 13, 15 y 20;
  - ADR-0031 y D-50.
- **Rama:** `m16-pendientes`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0031. El aprobador pidió terminar todo de corrido.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Endpoint SCIM 2.0 por tenant (Users, Groups) con token propio | Prueba contra un tenant real de Entra ID |
| Oracle en el pack .NET con su sandbox y golden master | Oracle en Go o Quarkus |
| Revisión adversarial de seguridad y corrección de los hallazgos confirmados | Pentest externo |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0031 y D-50 |
| 2 | SCIM: endpoint, token por tenant, mapeo de grupos a roles, auditoría, pantalla de Identidad |
| 3 | Oracle en .NET: pack, imagen y golden master |
| 4 | Revisión de seguridad y correcciones |
| 5 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Un IdP crea, busca, actualiza y desactiva usuarios y grupos de su tenant y de ningún otro | Pruebas de SCIM |
| Un token revocado o de otro tenant no entra | Pruebas de SCIM |
| El objetivo de referencia en .NET reproduce el golden master contra Oracle | Pruebas del pack .NET |
| Los hallazgos confirmados de la revisión tienen su prueba | Pruebas de cada corrección |
