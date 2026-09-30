# Plan del hito M6b — Packs de frontend: React y Angular

- **Estado:** cerrado (2026-09-30), ver la sección 4. Sigue M6c (PR apilada sobre esta rama).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md` secciones 8.4 (packs de destino), 7.4 (prototipos), 11.3
  (verificación), 20 (M6b); ADR-0013 (prototipos) y ADR-0014 (hitos de packs).
- **Rama:** `m6b-packs-frontend`, apilada sobre `m6-cobol-cics`. Un commit por paso y PR al terminar.
- **Decisiones del aprobador (2026-09-30):** grabaciones con modelos reales dentro de los 10 USD de M6, M6b y M6c
  (quedan 7,05), con aviso antes de cada una.

## 1. Alcance

| Incluye | No incluye (hitos posteriores) |
|---|---|
| Contrato del backend como OpenAPI 3.1, derivado por código del diseño aprobado en C3 | Next.js (Ola 2) |
| Cliente tipado TypeScript generado del OpenAPI (determinista), el mismo para React y Angular | Pruebas en navegadores reales (Chromium): se prueban en jsdom |
| Pack React: esqueleto (shell, router, cliente, `@nexti/ds`) y una página por pantalla | Temas de marca del cliente distintos de la base NexTI |
| Pack Angular: esqueleto (standalone, router, cliente, clases del design system) y un componente por pantalla | |
| Imagen `nexti-sandbox-frontend` sin red: TypeScript, esbuild, React, Angular (compilador AOT), jsdom y axe-core | |
| Arnés de pantallas escrito por la plataforma: campos, etiquetas, validaciones, acciones, navegación y axe | |
| El agente *frontend-dev* escribe cada pantalla desde su spec, su prototipo y el cliente (hacer-verificar-corregir) | |
| Paso de frontend en la generación; sin pack el paso espera (D-06); veredicto propio del frontend | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan y ADR-0016 |
| 2 | `nexti_frontend`: OpenAPI desde el diseño, cliente tipado y contrato de pantalla (campos, validaciones, acciones) |
| 3 | Imagen `nexti-sandbox-frontend` y arnés de pantallas en jsdom con axe |
| 4 | Pack React: esqueleto, compilación con `tsc` y esbuild, arnés |
| 5 | Pack Angular: esqueleto, compilación AOT con `ngc`, arnés |
| 6 | Orquestación: paso de frontend en la generación, lecturas del worker, veredicto del frontend |
| 7 | Aceptación con la aplicación ficticia (SP de M4 + mapas de M5), grabada con aviso previo |
| 8 | CI, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El frontend React y el Angular compilan | Build en el sandbox (`tsc --noEmit`, `ngc`) en los tests de cada pack y en la aceptación |
| Pasan sus tests | Arnés de pantallas en jsdom (por pantalla) |
| Cubren todos los campos, validaciones y acciones de las specs de pantalla | Arnés: cada campo con `data-field` y etiqueta accesible, obligatorios y longitudes, cada acción |
| axe sin violaciones graves | axe-core en jsdom dentro del arnés |
| Sin pack, la generación del frontend espera | Test de orquestación (frontend sin pack) |

## 4. Cierre de M6b (2026-09-30)

Los criterios de la sección 3 se cumplen con tests automatizados. Corren en CI con el sandbox de frontend real
(`nexti-sandbox-frontend:1`) y la grabación de la corrida real.

| Criterio | Evidencia (tests) | Estado |
|---|---|---|
| El frontend React y el Angular compilan | `test_react.py` y `test_angular.py` con pantallas de referencia (`tsc` estricto, `ngc` con plantillas estrictas); aceptación grabada | ✅ |
| Pasan sus tests | Arnés de pantallas en jsdom: todas las pantallas cargan y un envío válido llama al backend o navega | ✅ |
| Cubren todos los campos, validaciones y acciones de las specs | Arnés: campos con etiqueta accesible, longitud, numérico, secreto y salida no editable; obligatorios que avisan sin llamar; cada acción | ✅ |
| axe sin violaciones graves | axe-core en jsdom dentro del arnés. El contraste no se mide en jsdom y así lo dice el veredicto | ✅ (sin contraste) |
| Sin pack, la generación del frontend espera | `test_frontend.py` (Next.js espera, `none` no genera) | ✅ |

**Aceptación grabada.** `test_acceptance_m6b.py` parte del diseño de M4 y de los prototipos que el diseñador UX/UI
dibujó en M5, tomados de esa grabación. Resultado:

- El agente *frontend-dev* escribió 3 pantallas en React y 3 en Angular.
- Las dos apps compilan y pasan el arnés.
- Las dos tienen veredicto **PROVEN** con los 6 chequeos del frontend.
- En React el agente se corrigió 2 veces con la retroalimentación del arnés; en Angular no hizo falta.

La corrida final hizo 8 llamadas por 0,30 USD. El gasto real de M6b fue de 0,32 USD. De los 10 USD asignados a M6,
M6b y M6c quedan 6,73.

La primera grabación destapó un falso positivo del validador: un comentario `//` después de un string se leía como
URL externa. Ya está corregido, con su test.

**Suites al cierre.** Backend completo: 712 pasadas y 2 omitidas. E2E de Playwright: 23 pasadas.

**Cambios respecto del plan**

- Los pasos 3 a 5 se hicieron juntos: imagen, arnés y los dos packs.
- Los esqueletos son plantillas `.ts`/`.tsx` del paquete; en Python solo se completan el registro de pantallas, la
  pantalla inicial y el título.
- `Screen` de `@nexti/ds` le da nombre accesible a su `main`.
- Las aceptaciones de M4 y M6 declaran `frontend: none`, porque sus grabaciones son anteriores a los packs. Sus
  replays siguen pasando.
- La pestaña Validación de la web muestra los chequeos del frontend según el módulo del veredicto.

**Limitaciones conocidas**

- Las pantallas se prueban en jsdom, no en un navegador real: no se mide el contraste de color ni el render visual.
- El backend se simula en el arnés: se registran las llamadas de las páginas, pero no se ejecutan contra el
  backend generado.
- El bundle de Angular para el arnés y el shell es JIT. La compilación AOT (`ngc`) se usa como chequeo de tipos; un
  despliegue real usaría el build de Angular CLI.
- Angular usa las clases CSS y los tokens del design system, no componentes Angular propios.
- El agente elige qué operación del cliente llama cada pantalla. El arnés verifica que llame o navegue, no que la
  operación sea la correcta.
