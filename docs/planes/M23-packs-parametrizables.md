# Plan del hito M23 — Packs parametrizables y perfiles de pack

- **Estado:** cerrado (2026-10-05).
- **Fuente:** secciones 8.4, 8.6 y 8.7; ADR-0040 y D-59.
- **Rama:** `m23-packs-parametrizables` (sobre M22).

## 1. Pasos

| # | Paso |
|---|---|
| 1 | `BackendPack.configured(target)`; Spring Boot fija la versión del `pom` desde `backend_version`; la generación usa el pack configurado |
| 2 | `tenant_pack_profile` (migración 0024, RLS), API `/api/v1/pack-profiles`, catálogo del cliente con la preferencia `pack_profile` |
| 3 | Worker: la corrida recibe la raíz de paquete y las convenciones del perfil elegido; orientación y verificación de la raíz en el diseño (guiada) |
| 4 | Web: perfiles de pack en la pestaña de packs; selector de perfil en el asistente |
| 5 | Pruebas de pack, diseño, API y autorización; ADR-0040 y D-59 |

## 2. Cierre

Lo que un cliente puede moldear sin tocar packs: versión, raíz de paquete y convenciones. Lo que sigue siendo de la
plataforma: el pack, su imagen y su certificación. Con esto se cierra la serie M19–M23 pedida por el aprobador.
