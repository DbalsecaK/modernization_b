# ADR-0010 — Primer vertical Sybase hacia Java Spring Boot; el destino lo elige cada proyecto (D-06)

- **Estado:** Aceptada · 2026-09-29 (decisión del aprobador)
- **Secciones:** 8.1, 8.4, 8.7, 20 (M4), 22 (D-06 pasa de pendiente a registrada)
- **Relacionadas:** ADR-0011 (kit de referencia)

## Contexto

M4 construye el primer vertical completo: un stored procedure Sybase ASE migrado a un backend con PostgreSQL. La
especificación deja abierto el destino (D-06: ¿Java Spring Boot o .NET 10?). La aplicación de referencia es un SP
real de Banco Bolivariano, que tiene un proyecto de migración de Sybase a Java con Spring Boot.

## Decisión

- El **primer pack de destino** que se construye es **Java Spring Boot + PostgreSQL** (hexagonal por dentro, D-05).
- El destino **no es fijo**: el asistente del proyecto siempre pide los cinco ejes (arquitectura, backend, frontend,
  persistencia, cloud, 8.4) y la matriz de compatibilidad valida la combinación. Si un proyecto elige un backend
  cuyo pack todavía no existe, la fase de generación queda en espera ("pack disponible desde …") y nunca genera en
  otro lenguaje.
- El pack se construye detrás del contrato del principio N+M (8.1): sale de la spec y de los tipos neutrales, no del
  origen. .NET 10 y los demás backends se agregan después como packs con el mismo contrato.

## Alternativas consideradas

| Opción | Por qué no |
|---|---|
| .NET 10 primero | La referencia disponible migra a Spring Boot; construir primero .NET dejaría el vertical sin aplicación real para evaluar |
| Los dos packs en M4 | Duplica el trabajo del hito antes de validar el contrato del pack con un destino |

## Consecuencias

- El sandbox gana una imagen Java (Temurin 21 + Maven con las dependencias del pack ya descargadas), porque el
  contenedor no tiene red.
- La certificación de la ola 1 (8.7) sigue incluyendo .NET 10; queda como pack posterior.

## Cómo se valida

- La generación por capas del pack compila y pasa sus tests en el sandbox para la aplicación ficticia (CI) y para la
  referencia (a demanda).
- Un proyecto con backend sin pack espera en la generación en lugar de generar otro lenguaje (test del motor).
