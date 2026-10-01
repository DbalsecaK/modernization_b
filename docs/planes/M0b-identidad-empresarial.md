# Plan del hito M0b — Identidad empresarial (SSO, MFA, Organizations)

- **Estado:** cerrado (2026-10-01).
- **Fuente:** `docs/ESPECIFICACION_PLATAFORMA.md`, secciones:
  - 15.1: autenticación e implantación por etapas;
  - 16: roles y permisos;
  - 18.7: pantallas de login del prototipo;
  - 20: M0b.

  Decisiones: D-20, D-27, ADR-0002, ADR-0004 y ADR-0022.
- **Rama:** `m0b-identidad`. Un commit por paso y PR al terminar.

## Decisiones

Se toma la opción recomendada en cada punto, porque el aprobador pidió avanzar sin preguntas.

**Organizations y tenants**

- Hay una Organization de Keycloak por tenant, en el realm `nexti`. Su alias es el slug del tenant.
- Los dominios de correo del tenant son los de la Organization.
- La plataforma la crea y la mantiene por la Admin REST API, con la cuenta de servicio `nexti-admin`. Esa cuenta suma
  `manage-realm` y `manage-identity-providers` y nada más.

**Tenant de la sesión**

- El BFF pide el scope `organization`.
- Si el token trae una Organization, la sesión arranca en ese tenant, siempre que el usuario sea miembro.
- Si no la trae, la sesión arranca en el primer tenant del usuario, como hasta ahora.

**SSO**

- Cada proveedor del tenant (Entra ID, Okta, Google o cualquier OIDC o SAML 2.0) es un Identity Provider de Keycloak.
  Queda vinculado a la Organization del tenant y a sus dominios.
- El secreto del cliente se envía solo a Keycloak. La plataforma no lo guarda ni lo audita.
- El IdP importa los grupos del usuario a un atributo `idp_groups`, que el cliente `nexti-bff` pone en el token.

**Home-realm discovery y "solo SSO"**

- La página de login de la web pide primero el correo.
- Si el dominio del correo es de un proveedor del tenant, el BFF redirige a Keycloak con `kc_idp_hint`. Si no, lo
  hace con `login_hint`.
- Un dominio "solo SSO" no puede entrar con contraseña. El BFF lo comprueba en el callback con la sesión de Keycloak:
  el claim `identity_provider` debe ser el proveedor del dominio.

**JIT y grupos**

- En el primer login por un proveedor con JIT, la plataforma crea el usuario y su membresía.
- En cada login traduce los grupos del IdP a roles del tenant, según el mapeo del proveedor. Los roles que vienen
  del mapeo se recalculan; los asignados a mano no se tocan.

**MFA**

- Un tenant con "MFA obligatoria" exige un segundo factor a las cuentas propias. Se usa el nivel de autenticación
  (LoA) de Keycloak:
  - el BFF pide `acr_values=mfa`;
  - el flujo `browser` del realm pide contraseña y luego OTP o passkey (WebAuthn);
  - el usuario que no tiene segundo factor lo configura en el momento;
  - los códigos de recuperación son una acción requerida de Keycloak.
- El callback rechaza un login con contraseña sin `acr=mfa` cuando el tenant lo exige.
- Los secretos de MFA viven solo en Keycloak.

**Políticas del realm**

- Las de contraseña, bloqueo y sesión son del realm compartido, porque Keycloak solo las admite por realm (D-20).
- La pestaña las muestra en solo lectura.
- Un tenant que necesite otras va a un realm dedicado; esa configuración es por despliegue.

**Tema de las pantallas de Keycloak**

- El tema `nexti` (login, OTP, WebAuthn, recuperación y activación) se construye con Keycloakify a partir de las
  pantallas del prototipo, en inglés y español.
- Va en una imagen de Keycloak propia, `nexti-keycloak`, con el tema dentro.

**Entra ID**

- Es un proveedor OIDC con el emisor `https://login.microsoftonline.com/<tenant>/v2.0`.
- La prueba con un tenant real de Entra queda pendiente hasta tener uno de prueba. La aceptación usa un segundo
  realm de Keycloak, `idp-test`, como IdP externo; la especificación admite esa opción.

**Auditoría**

- Los cambios de la configuración se auditan sin secretos.
- Los eventos de Keycloak, entre ellos el login por IdP y los cambios de TOTP, ya llegan a la auditoría desde M0.

## 1. Alcance

| Incluye | No incluye |
|---|---|
| Organization por tenant, sincronizada desde la plataforma | SCIM (se decide con un cliente que lo pida) |
| Proveedores OIDC y SAML por tenant, con dominios, "solo SSO", JIT y mapeo de grupos a roles | Prueba con un tenant real de Entra ID (pendiente de un tenant de prueba) |
| MFA obligatoria por tenant (TOTP, passkeys, códigos de recuperación) con LoA | Políticas de contraseña por tenant en el realm compartido (realm dedicado) |
| Login "email first" con home-realm discovery | |
| Administración → Autenticación conectada (proveedores, métodos y MFA) | |
| Tema Keycloakify de las pantallas de Keycloak (en/es) | |

## 2. Pasos y commits

| # | Paso |
|---|---|
| 1 | Plan, ADR-0022 y D-41 |
| 2 | Realm: Organizations, flujo `browser` con LoA (OTP/WebAuthn), códigos de recuperación, mappers del token, permisos de `nexti-admin` y realm `idp-test` |
| 3 | Datos y Keycloak: tablas de la configuración por tenant y de los proveedores; cliente Admin REST para Organizations e IdPs; reconciliación de la Organization de cada tenant |
| 4 | API de Administración → Autenticación: política del tenant y proveedores (OpenFGA, auditoría, aislamiento) |
| 5 | Login: email first y HRD, tenant desde la Organization, "solo SSO", MFA por LoA, JIT y grupos a roles |
| 6 | Web: pestaña Autenticación conectada y login "email first" (en/es) |
| 7 | Tema Keycloakify en la imagen `nexti-keycloak` |
| 8 | Aceptación, cierre y PR |

## 3. Criterios de aceptación → tests

| Criterio | Test |
|---|---|
| Login con SSO por un IdP externo (segundo realm) | `test_acceptance_m0b.py` |
| Cuenta propia con MFA (TOTP) en un tenant que la exige | `test_acceptance_m0b.py` |
| Un dominio "solo SSO" no entra con contraseña | `test_acceptance_m0b.py` |
| El token trae la Organization y de ella sale el `tenant_id` | `test_acceptance_m0b.py` |
| Un usuario en dos Organizations solo ve el tenant activo | `test_acceptance_m0b.py` y `test_rls.py` |
| Los grupos del IdP se traducen a los roles esperados | `test_acceptance_m0b.py` |
| La configuración solo la cambia quien tiene el permiso, en su tenant, y queda auditada | `test_endpoints_authz.py` (casos de `/api/v1/identity` y aislamiento) |

## 4. Cierre

**Lo que se entrega**

- **Organization de Keycloak por tenant.** La plataforma la reconcilia por la Admin REST API: alias, dominios y
  miembros. La cuenta `nexti-admin` suma solo los permisos de realm y de proveedores de identidad.
- **Proveedores OIDC y SAML 2.0 por tenant** (Entra ID, Okta, Google o cualquier otro), vinculados a su Organization.
  - Si se da el emisor, los endpoints se descubren solos.
  - Las URLs tienen que ser https y públicas; localhost solo se acepta en local.
  - Cada dominio pertenece a un solo proveedor en toda la plataforma.
  - El secreto va solo a Keycloak: no queda en la base, no vuelve en la API ni pasa por la auditoría. La prueba de
    aislamiento lo comprueba.
- **Login.**
  - **Email first y home-realm discovery en el BFF.** El dominio del correo decide adónde va el login: al
    proveedor del dominio (`kc_idp_hint`) o, si el tenant exige MFA, a Keycloak con `acr=mfa`.
  - **Reglas en el callback**, sobre el token validado:
    - un dominio "solo SSO" no entra con contraseña;
    - un tenant sin cuentas propias solo deja entrar a usuarios de sus proveedores;
    - con MFA obligatoria, un login con solo contraseña vuelve a Keycloak, que pide solo el segundo factor;
    - en el primer login por un proveedor con JIT se crean la cuenta y la membresía;
    - en cada login, los grupos del IdP se convierten en roles del tenant (las asignaciones con origen `idp` se
      recalculan y las manuales no se tocan);
    - la Organization del token elige el tenant de la sesión.
- **MFA por nivel de autenticación.** El flujo `browser` del realm tiene dos niveles. El segundo acepta TOTP,
  passkey o código de recuperación, y quien no tiene ningún factor configura el TOTP en ese momento.
- **Administración → Autenticación conectada**, en inglés y español:
  - métodos, dominios y MFA obligatoria;
  - proveedores con su estado en Keycloak y la URL de retorno para registrar en el IdP;
  - mapeo de grupos a roles y rol por defecto;
  - las políticas del realm, en solo lectura.

  Se retiraron el mock de proveedores y su formulario.
- **Tema Keycloakify** con el diseño del login del prototipo (panel de marca, colores y textos en/es) y las páginas
  propias de Keycloak dentro. Va en la imagen `nexti-keycloak:1`, que el Compose construye.
- **Realm `idp-test`** como IdP externo de prueba, con usuarios en grupos.

**Aceptación** (`test_acceptance_m0b.py`), contra el Keycloak real del Compose y recorriendo sus páginas:

- **SSO desde el correo con JIT:** dos usuarios de `idp-test` reciben los roles de sus grupos (`it-admins` y
  `auditors` dan administrador del tenant y auditor; `finance` da finanzas), y el login queda auditado con el
  proveedor.
- **"Solo SSO":** una cuenta propia de `corp.example` es rechazada con `sso_required`.
- **Organization:** una persona de dos tenants, miembro solo de la Organization de Pacific, entra en Pacific (no en
  Andes, que va primero por nombre) y solo ve los proyectos de Pacific.
- **MFA:** con la MFA obligatoria, una cuenta propia configura su TOTP y entra con `acr=mfa`. Sin el correo primero,
  la contraseña sola no alcanza y Keycloak pide solo el código.

**Cambios respecto del plan**

- **Dos cambios a la sección 15.1**, registrados en el ADR-0022:
  - el secreto del proveedor vive en Keycloak, no en Vault;
  - "cuentas propias siempre con MFA" pasa a ser la política "MFA obligatoria" del tenant, desactivada por
    defecto.
- **Organization con varios tenants.** Con el scope `organization`, Keycloak no manda el claim si el usuario está en
  varias Organizations, y el flujo no pide elegir una. La sesión arranca entonces en el primer tenant y la persona
  cambia de tenant en la plataforma.
- **El tema dibuja los formularios en el navegador.** Las pruebas que recorren Keycloak con httpx leen la acción y
  los campos ocultos del `kcContext`. El realm `idp-test` sigue con el tema de Keycloak.

**Limitaciones conocidas**

- La prueba con un tenant real de Entra ID queda pendiente de un tenant de prueba. Entra ID es un proveedor OIDC
  más.
- SCIM no está incluido.
- Las políticas de contraseña, bloqueo y sesión son del realm compartido. Un tenant que necesite otras pasa a un
  realm dedicado.
- Un entorno local creado antes de M0b recrea la base de Keycloak al arrancar con `start-local`.
