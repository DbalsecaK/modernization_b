# Plan del hito M10 — Flujo 4: validación independiente (IV&V)

- **Estado:** cerrado (2026-10-02).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`:
  - secciones 3.1 y 3.3, 6, 11.3 y 20 (Posterior);
  - ADR-0025 y D-44.
- **Rama:** `m10-flujo-4`. Un commit por paso y PR al terminar.
- **Decisiones:** las del ADR-0025. El aprobador pidió avanzar de corrido hasta terminar.
- **Presupuesto de grabación:** hasta 2 USD.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Flujo `independentValidation` en catálogo, composición, proyectos, insumos y web | Harness dinámico para destinos que no sean Spring Boot (quedan en inventario y reglas) |
| Insumo `target_archive` (código del tercero y su artefacto ejecutable) | Compilar el código del tercero sin red |
| Adaptador del destino: endpoints, campos, tablas, *slices* (Spring Boot; ASP.NET Core) | |
| Mapeo propuesto por código y aprobado en C2 | |
| Prueba de caja negra del golden master contra el artefacto del tercero en el sandbox | |
| Extracción de reglas del destino y comparación con las del legado | |
| Veredicto IV&V (`IVV_CHECKS`), informe y paquete de prueba | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0025 y D-44 |
| 2 | El flujo en el catálogo, la composición, la base (migración), la API y la web; insumo `target_archive` |
| 3 | Inventario del destino (`nexti_ivv.target`): endpoints, campos, tablas y *slices* |
| 4 | Mapeo: propuesta por código, `ivv-mapping.yaml`, gate C2 y su API |
| 5 | Harness de caja negra en el sandbox y comparación con el golden master |
| 6 | Fases del flujo, reglas del destino, veredicto IV&V, informe y paquete de prueba |
| 7 | Web: mapeo en C2 e informe IV&V (en/es) |
| 8 | Aceptación grabada, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| El inventario del destino tiene sus endpoints, campos y tablas | Pruebas del adaptador |
| El mapeo propuesto empareja programa, endpoint, campos y tablas | Pruebas del mapeo |
| Un destino correcto reproduce el golden master; uno con un error no | Pruebas del harness |
| La migración de terceros de la aplicación ficticia recibe su veredicto IV&V con informe | `test_acceptance_m10.py` |
| C2 y la API del mapeo, con OpenFGA, auditoría y aislamiento | `test_endpoints_authz.py` |

## 4. Cierre

**Lo que se entrega**

- **Flujo `independentValidation`** en el catálogo (C1, C2 y C4), la composición, la base (migración 0016), la API,
  el worker y la web. Las opciones de fuente guardan ahora una lista de flujos: las tecnologías legadas sirven al
  Flujo 1 y al Flujo 4. legacy-analyst (1.5.0) y rules-extractor (2.2.0) se recomiendan también para el Flujo 4.
- **Insumo `target_archive`:** el código del tercero, con su artefacto ejecutable si lo trae. Se valida como el
  archivo fuente y se descarga con `code.download`.
- **Paquete `nexti-ivv`:**
  - inventario del destino por código: Spring Boot completo; ASP.NET Core para inventario y *slices*;
  - mapeo legado ↔ destino (`ivv-mapping.yaml` del proveedor o propuesta por nombres, con las brechas que una persona
    debe cerrar) y sus problemas, calculados contra el golden master y el inventario;
  - arnés de caja negra en `nexti-sandbox-java:2`: PostgreSQL efímero, el destino compilado o su jar, stubs HTTP
    para las llamadas externas y comparación HTTP + tablas + llamadas normalizada al formato del legado.
- **Fases IV&V:** intake del destino, mapeo (C2), reglas del destino comparadas con las aprobadas, validación con
  `IVV_CHECKS` (`target_runs`, `contract_mapped`, `same_behaviour`, `fresh_inputs`, `rules_covered`,
  `source_intact`), informe `ivv/REPORT.md` y paquete de prueba con el mapeo y la comparación.
- **API:** `GET /projects/{id}/ivv` (`code.view`) y `PUT /projects/{id}/ivv/mapping` (`gate.c2.approve`). La
  corrección se guarda como versión en `ivv_mapping_version` (RLS, solo inserción), se audita
  (`ivv.mapping.change`) y el worker la usa si es posterior al intake.
- **Web:** pestaña IV&V (inventario, editor del mapeo con problemas y brechas, comparación de reglas e informe), el
  estado del mapeo junto a la puerta C2 y los títulos de los checks IV&V (en/es).

**Evidencia**

- **`test_acceptance_m10.py`:** BillPay, la migración ficticia de un tercero, recibe **PROVEN**: 28 de 28 casos del
  golden master, 12 entradas nuevas iguales en ambos lados, 11 de 11 reglas reproducidas y C1, C2 y C4 aprobadas por
  la API. La comparación de reglas encuentra 8 de 11 reglas del legado en el destino.
- **Grabación:** el lado legado reutiliza los cassettes y el golden master de M4. Solo se grabaron las 3 llamadas de
  las reglas del destino: unos 0,08 USD reales. El `cost_usd` del reporte (1,13 USD) es el costo contable de todas
  las llamadas reproducidas.
- **Pruebas de `nexti-ivv`:** un destino correcto reproduce los 12 casos del fixture y uno con la regla de sobregiro
  cambiada falla esos casos.
- **API:** matriz de permisos, aislamiento entre tenants, RLS de la tabla nueva y auditoría.

**Cambios respecto del plan**

- El inventario del destino vive en `nexti_ivv.target`, no en un adaptador `nexti_adapter_target` aparte: solo lo
  usa el Flujo 4.
- La corrección del mapeo es una tabla versionada y no una nueva versión del artefacto generado: `generated_artifact`
  es de solo inserción por ejecución.
- La aceptación encontró un error real del arnés: los códigos con ceros a la izquierda (número de cuenta) se
  normalizaban como enteros. Ahora se comparan como texto.
- No hay pruebas de render en la web: su configuración de pruebas no tiene jsdom. Las pruebas cubren el cliente de la
  API y el modelo de la pestaña.

**Queda para después**

- Arnés dinámico para destinos ASP.NET Core (hoy solo inventario y reglas).
- Compilar el código del tercero sin red cuando sus dependencias no están en la imagen.
