# ADR-0014 — Hitos propios para los packs de destino de la Ola 1

- **Estado:** Aceptada · 2026-09-30
- **Secciones:** 8.1, 8.4, 8.7 (Ola 1), 20 (hoja de ruta)
- **Relacionadas:** ADR-0010 (primer pack: Java Spring Boot), ADR-0013 (prototipos React)

## Contexto

La plataforma es multilenguaje en origen y en destino (8.1): cada origen tiene un adaptador que llega a la spec
neutral y cada destino un pack que sale de ella. La Ola 1 (8.7) certifica como destinos Java Spring Boot, .NET 10,
Angular, React, PostgreSQL, SQL Server, Oracle, AWS y Azure. La hoja de ruta (20) asignaba los orígenes a hitos, pero
ningún hito construía los packs de destino más allá de Spring Boot + PostgreSQL (M4); solo M8 mencionaba .NET 10
para ASPX. El aprobador pidió priorizar terminar la aplicación y agregar esos hitos.

## Decisión

- **M6b — Packs de frontend React y Angular** (después de M6): usan el design system y los prototipos aprobados en
  C2 (M5) y un cliente tipado desde el OpenAPI del backend.
- **M6c — Pack .NET 10 + SQL Server** (antes de M8, que lo necesita para ASPX): mismo contrato de diseño, sandbox y
  verificación que Spring Boot.
- **M8b — Packs Oracle y nube AWS/Azure** (antes de M9): persistencia Oracle en los backends existentes e IaC con
  Terraform/OpenTofu validada en el sandbox.
- Ola 2 y Ola 3 (Quarkus, Next.js, MySQL, GCP, serverless, Go, MongoDB) siguen sin hito asignado.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| Un solo hito con todos los packs | Demasiado grande para revisarlo y cerrarlo con aceptación automatizada |
| Construir cada pack dentro del hito de un origen | Acopla orígenes y destinos, contra 8.1 |
| Dejar los packs para después de M9 | La aplicación no estaría completa para la Ola 1 |

## Consecuencias

- Hay tres hitos más en la sección 20; cada uno tiene su plan, sus criterios de aceptación y su PR.
- Un proyecto que elige un destino sin pack sigue esperando en la generación (D-06) hasta que llegue su hito.

## Cómo se valida

- Cada hito cierra con la aplicación ficticia migrada a su destino y verificada por código.
