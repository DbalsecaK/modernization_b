# Plan R2b — Runner en vivo de IBM i

- **Estado:** cerrado sin validación en un IBM i real (2026-10-07).
- **Fuente:** ADR-0053, D-85; plan de soporte RPG aprobado (R2).
- **Rama:** `r2b-runner-ibm-i` (sobre R2a).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | Puente `infra/sandbox/ibmi-bridge` (JTOpen 21.0.7): sign-on, lista de bibliotecas, carga de filas, `ProgramCall`, lectura |
| 2 | `nexti_adapter_rpg.ibmi`: parámetros tipados desde el parser, petición por stdin, golden master con entorno |
| 3 | Worker: fábrica `ibmi` en `Runtime.live` con la imagen del puente |
| 4 | Imagen en `start-local.ps1`, CI, release y Helm |

## 2. Pendiente

- Validar de punta a punta en un IBM i de prueba (PUB400 con el espacio de trabajo ficticio, o el sistema de prueba de
  un cliente).
- Procedimientos de un *SRVPGM, cobertura medida en el IBM i y quirks de RPG (R4).

## Cómo se valida

Pruebas del runner con el puente reemplazado; la imagen se construye en CI; el puente real responde en JSON los
errores de conexión y de petición.
