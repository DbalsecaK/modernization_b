# Plan del hito M16 — Pendientes: SCIM, Oracle en .NET y revisión de seguridad

- **Estado:** cerrado (2026-10-03).
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

## 4. Cierre

**Lo que se entrega**

- **SCIM 2.0 por tenant** (`/scim/v2`): Users y Groups con filtros, paginación, `PATCH` y desactivación; token de
  portador creado, rotado y revocado desde Administración → Autenticación, guardado solo como hash y comparado en
  tiempo constante; sincronización con Keycloak (cuenta en la organización del tenant, deshabilitada al desactivar si
  la persona no está en otro tenant); grupos a roles con el mapeo del IdP (`source='scim'`); todo auditado
  (migración 0019).
- **Oracle en el pack .NET** (`nexti_pack_dotnet.oracle`): Oracle.ManagedDataAccess.Core, DDL y comillas de Oracle,
  harness con el proveedor ADO.NET que indica el plan, imagen `nexti-sandbox-dotnet-oracle:1`.
- **Revisión de seguridad** de lo construido desde M9a. Hallazgos corregidos:
  - *SCIM entre tenants:* los dominios propios de un tenant no eran únicos en la plataforma. Un tenant que declarara
    el dominio de otro podía vincular por SCIM las cuentas globales de esas personas y reactivar en Keycloak una
    cuenta deshabilitada. Ahora SCIM rechaza un dominio que otro tenant también declara y nunca reactiva la cuenta
    de alguien que pertenece a otro tenant;
  - *SSRF por DNS rebinding en modelos locales:* la URL base se validaba solo al configurarla. Ahora el gateway
    vuelve a resolver el host antes de cada llamada y rechaza una dirección interna, salvo que el despliegue
    permita hosts privados (perfil `air-gapped`).

  Revisado sin hallazgos: autenticación SCIM, extracción del paquete air-gapped (rutas, tipos de entrada,
  duplicados, firma y hashes), plugin de Figma (datos en JSON ASCII, sin red ni `eval`), control de licencia y push
  de la entrega (token enmascarado, host verificado, nunca la rama base).

**Evidencia**

- SCIM: 12 pruebas, entre ellas el aislamiento entre tenants, el token revocado, la sincronización con Keycloak y el
  dominio declarado por dos tenants.
- Oracle en .NET: el objetivo de referencia reproduce el golden master contra Oracle y el canario se detecta; el
  pack con SQL Server sigue reproduciendo su golden master.
- Gateway: un host interno al momento de la llamada se rechaza antes de enviar nada y queda en el registro de uso.
- Matriz de permisos, RLS y esquema en verde.

**Queda para después**

- La prueba de identidad con un tenant real de Entra ID (necesita credenciales de un tenant de prueba).
- La grabación de la aceptación del Flujo 3 con modelos reales (necesita el OK del aprobador).
