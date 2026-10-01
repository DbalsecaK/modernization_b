# Plan del hito M0b — Identidad empresarial (SSO, MFA, Organizations)

- **Estado:** en curso (desde 2026-10-01).
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
| Un usuario en dos Organizations solo ve el tenant activo | `test_acceptance_m0b.py` y `test_tenant_isolation` |
| Los grupos del IdP se traducen a los roles esperados | `test_acceptance_m0b.py` |
| La configuración solo la cambia quien tiene el permiso, en su tenant, y queda auditada | `test_auth_admin_api.py` |
