# Plan del hito M14 — Ola 3: Go y MongoDB

- **Estado:** en curso (desde 2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 8.4, 8.5, 8.7 y 20 (Posterior);
  - ADR-0029 y D-48.
- **Rama:** `m14-ola3-go-mongodb`, encima de `m13-ola2-quarkus-nextjs`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0029. El aprobador pidió avanzar de corrido hasta terminar.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Pack Go con su imagen, pruebas, golden master y canario | Go con bases distintas de PostgreSQL |
| MongoDB como base del pack Spring Boot, con modelado de agregados | MongoDB en .NET, Quarkus o Go |
| IaC de MongoDB en AWS y Azure | Un servicio MongoDB gestionado en GCP |
| Catálogo, CI, release y Helm | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0029 y D-48 |
| 2 | Pack Go: esqueleto, imagen, objetivo de referencia, golden master y canario |
| 3 | MongoDB: modelado de agregados, adaptadores, imagen, golden master e IaC |
| 4 | Catálogo, CI, release y Helm |
| 5 | Cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El esqueleto Go compila y sus pruebas corren en el sandbox | Pruebas del pack Go |
| El objetivo de referencia en Go reproduce el golden master | Pruebas del pack Go |
| El objetivo de referencia con MongoDB reproduce el golden master por colección | `test_mongodb.py` |
| La IaC de MongoDB valida y cumple las fitness functions en AWS y Azure | `test_iac.py` |
