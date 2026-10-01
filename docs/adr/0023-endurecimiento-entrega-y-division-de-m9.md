# ADR-0023 — Endurecimiento y entrega del proyecto; división de M9

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 6.1 (fases 12 y 13), 6.3 (strangler fig), 7.2 (entrega de Flujo 2), 14.3-14.5 (despliegue), 15.7
  (seguridad de la cadena), 16.2 (`codigo.push`), 20 (M9)
- **Relacionadas:** ADR-0007 (secretos en OpenBao), ADR-0014 (hitos), ADR-0021 (IaC del destino)

## Contexto

Las corridas de modernización se detienen en la fase 12 (endurecimiento) porque no tiene ejecutor. La fase 13
(entrega) solo informa que el ZIP está listo. El botón *Push* de la pestaña Código está deshabilitado y el permiso
`code.push` no lo usa ningún endpoint.

La sección 20 junta en M9 dos cosas distintas:

- lo que el proyecto del cliente necesita para salir: endurecer y entregar el código generado;
- lo que la plataforma necesita para desplegarse: contenedores, Helm, OpenTofu por nube, perfiles, SBOM, imágenes
  firmadas, DAST y operación.

## Decisión

### División del hito

M9 se divide en dos hitos, cada uno con su rama, su PR y su plan:

- **M9a — Endurecimiento y entrega del proyecto:** las fases 12 y 13 de los dos flujos y su parte en la web.
- **M9b — Despliegue de la plataforma:** el empaquetado (14.4), los perfiles y el plano de datos en la nube del
  cliente (14.3), la cadena segura (15.7) y la operación de plataforma.

### Endurecimiento, calculado por código

La fase produce un informe con hallazgos de cuatro tipos. Cada hallazgo tiene severidad, archivo y regla.

- **Secretos:** gitleaks corre en el sandbox, sin red, sobre los archivos generados.
- **Dependencias:** las coordenadas del proyecto generado (Maven, NuGet, npm) se consultan en OSV
  (`api.osv.dev`). Solo salen nombres y versiones de bibliotecas públicas, nunca código del cliente. Un despliegue
  sin salida a internet lo marca como "no comprobado".
- **Reglas estáticas por lenguaje**, deterministas: SQL armado por concatenación, verificación TLS deshabilitada,
  credenciales en el código, CORS abierto y modo debug.
- **Rendimiento básico:** los tiempos de los tests del build limpio (JUnit XML). Un test que pasa del umbral es un
  hallazgo.

El informe se guarda como artefacto (`hardening/report.json` y `hardening/REPORT.md`) y se muestra en la pestaña
Validación. La fase no bloquea la entrega: el informe viaja con el release. Los hallazgos críticos se señalan en el
resumen de la corrida.

La revisión del informe por el agente auditor de seguridad queda para después de medir el informe por código.

### Entrega

La fase arma el release:

- el código generado (backend, frontend, IaC);
- el plan de corte strangler fig (6.3), calculado desde el diseño: cada programa legado con su ruta nueva, el orden
  por dominio y los stubs de la capa anticorrupción;
- el informe de endurecimiento.

**Push al repositorio del cliente.** Cuando el proyecto tiene un repositorio configurado y quien lanzó la corrida
tiene `code.push`, el release se sube a una rama nueva, `nexti/<corrida>`:

- nunca a la rama principal;
- con dulwich (Git en Python puro, sin CLI);
- con el token de OpenBao;
- con el mismo filtro SSRF del repositorio de origen.

El mismo push se puede pedir desde la pestaña Código (`POST /projects/{id}/code:push`, con `code.push`). Cada
entrega queda en la tabla `release`: rama, commit, archivos y estado. También se audita.

Sin repositorio, el release queda para descargar en ZIP, como hasta ahora.

## Alternativas consideradas

- **Push a la rama principal o merge automático.** Saltea la revisión del cliente. Una rama nueva deja la decisión a
  su proceso de pull requests.
- **CLI de git en el worker.** Agrega un binario al contenedor y una superficie de inyección de argumentos. dulwich
  hace lo necesario (commit y push por HTTPS) en el mismo proceso.
- **Semgrep como SAST del código generado.** Sus reglas del registro necesitan red o un paquete de reglas mantenido.
  Las reglas propias por lenguaje cubren los patrones que el generador puede introducir. Semgrep sigue en el CI de la
  plataforma.
- **Bloquear la entrega con hallazgos críticos.** El código ya pasó C4 con sign-off humano. El informe informa, y la
  decisión de desplegar es del cliente.

## Consecuencias

- Las corridas de modernización llegan al final del flujo: endurecimiento, entrega y `completed`.
- El permiso `code.push` pasa a usarse. El botón *Push* se habilita para quien lo tiene.
- La plataforma consulta un servicio externo (OSV) con nombres de bibliotecas. Una variable de entorno lo apaga.

## Cómo se valida

- Pruebas del endurecimiento con un proyecto que tiene un secreto, una dependencia vulnerable (OSV simulado) y un
  patrón inseguro, y otro limpio.
- Push a un servidor Git HTTP de prueba (dulwich en el proceso): la rama y el commit se verifican leyendo el
  repositorio.
- Las aceptaciones grabadas (M4, M6c, M8b) llegan a `completed` con su informe y su release en ZIP.
- OpenFGA y aislamiento para `code:push` y los endpoints nuevos.
