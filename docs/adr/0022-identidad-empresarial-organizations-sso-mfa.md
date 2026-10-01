# ADR-0022 — Identidad empresarial: Organizations por tenant, SSO, MFA por nivel de autenticación

- **Estado:** Aceptada · 2026-10-01
- **Secciones:** 15.1 (autenticación), 16 (roles y permisos), 18.7 (pantallas de login), 20 (M0b)
- **Relacionadas:** ADR-0002 (multi-tenant), ADR-0004 (autenticación por etapas)

## Contexto

En M0 se dejó Keycloak con lo mínimo: un realm `nexti`, cuentas locales y el BFF. M0b agrega lo empresarial:

- SSO con el IdP del cliente;
- MFA;
- Organizations por tenant;
- home-realm discovery y "solo SSO";
- el tema de las pantallas de Keycloak;
- la configuración por tenant desde Administración.

La especificación pide que sea configuración de Keycloak más pantallas, sin cambiar la API de negocio. La plataforma
no guarda contraseñas ni secretos de MFA.

Hay tres preguntas abiertas:

- Cómo se exige MFA por tenant en un realm compartido.
- Cómo se impide la contraseña a un dominio "solo SSO".
- Cómo llegan los grupos del IdP a roles de la plataforma.

## Decisión

### Organizations

- **Una Organization de Keycloak por tenant**, con alias igual al slug del tenant y los dominios del tenant.
- La plataforma la reconcilia por la Admin REST API: la crea si falta y sincroniza sus dominios.
- La cuenta de servicio `nexti-admin` suma `manage-realm` y `manage-identity-providers`, y nada más.
- El BFF pide el scope `organization`. Si el token trae una Organization de la que el usuario es miembro en la
  plataforma, la sesión arranca en ese tenant.

### Proveedores

- **Proveedores de identidad por tenant.** Cada uno es un Identity Provider de Keycloak (OIDC o SAML 2.0),
  vinculado a la Organization del tenant.
- La plataforma guarda en `tenant_identity_provider` el alias, el protocolo, los dominios, "solo SSO", JIT y el
  mapeo de grupos a roles.
- El secreto del cliente va directo a Keycloak y no se guarda.
- Un mapper del IdP importa el claim de grupos al atributo `idp_groups`. Un mapper del cliente `nexti-bff` lo emite
  en el token, junto con el claim `identity_provider`, que es una nota de la sesión de Keycloak.

### Home-realm discovery y "solo SSO"

- **Home-realm discovery en el BFF.** `/auth/login?email=` busca el dominio entre los proveedores:
  - si el dominio tiene un proveedor, redirige con `kc_idp_hint`;
  - si no, redirige con `login_hint`.
- **"Solo SSO" en el callback.** Si el correo del usuario es de un dominio "solo SSO" y el claim
  `identity_provider` no es ese proveedor, el login se rechaza con `sso_required`.
- Keycloak solo se usa para autenticar. La regla vive en un lugar con tests y no depende de que el usuario no
  conozca la URL de Keycloak.

### MFA

- **MFA por nivel de autenticación (LoA).** El flujo `browser` del realm tiene dos niveles:
  - nivel 1: contraseña o IdP;
  - nivel 2: OTP o passkey (WebAuthn).
- El cliente mapea `mfa` al nivel 2. Cuando el tenant exige MFA, el BFF pide `acr_values=mfa`.
- Un usuario sin segundo factor lo configura en ese momento, como acción requerida, y lo mismo sus códigos de
  recuperación.
- El callback rechaza un login local con `acr` distinto de `mfa` en un tenant que lo exige.
- Los logins por IdP no pasan por el segundo nivel: el MFA es del IdP del cliente.

### JIT y grupos

- En el primer login por un proveedor con JIT, la plataforma crea el usuario y la membresía.
- En cada login traduce `idp_groups` a roles del tenant según el mapeo.
- Las asignaciones que vienen del mapeo se marcan con su origen y se recalculan. Las manuales no se tocan.

### Políticas del realm y tema

- **Políticas de contraseña, bloqueo y sesión del realm compartido**, de solo lectura en la pestaña. Un tenant que
  necesite otras pasa a un realm dedicado (D-20).
- **Tema con Keycloakify** a partir de las pantallas del prototipo (en/es), en una imagen de Keycloak propia,
  `nexti-keycloak`. Así Compose y CI usan el mismo tema.

### Pruebas

- **IdP de prueba.** Un segundo realm, `idp-test`, en el mismo Keycloak, actúa como IdP OIDC externo. Tiene usuarios
  con grupos.
- La prueba con un tenant real de Entra ID queda pendiente hasta tener uno de prueba. Entra ID es un proveedor OIDC
  más, con su emisor `login.microsoftonline.com/<tenant>/v2.0`.

**Cambios a la sección 15.1:**

- **El secreto del cliente de un proveedor vive en Keycloak, no en Vault.** Keycloak lo necesita para cada login y
  no se integra con OpenBao. Una copia en OpenBao no la usaría nadie.
- **"Cuentas propias siempre con MFA" pasa a ser una política del tenant** ("MFA obligatoria"), desactivada por
  defecto. Así los entornos locales y de prueba siguen entrando con contraseña. Al dar de alta un tenant
  productivo, la política se activa desde Administración → Autenticación.

## Alternativas consideradas

- **Un realm por tenant en el SaaS.** Da políticas por tenant, pero multiplica la operación y rompe la cuenta única
  con membresía en varios tenants. D-20 ya eligió Organizations.
- **Flujos de autenticación por Organization en Keycloak** para MFA y "solo SSO". Keycloak no condiciona un flujo por
  Organization sin extensiones propias. Hacerlo con LoA y la comprobación en el callback no necesita código Java
  dentro de Keycloak.
- **Mapear los grupos a roles de Keycloak.** Los roles y permisos viven en OpenFGA (D-15). Duplicarlos en Keycloak
  abre dos fuentes de verdad.
- **Guardar el secreto del IdP en OpenBao.** Keycloak ya lo guarda y lo necesita. Una segunda copia solo agrega
  superficie.

## Consecuencias

- `nexti-admin` puede cambiar la configuración del realm. Su secreto se trata como el de la base.
- El realm del Compose se importa solo si no existe. Un entorno local creado antes de M0b necesita recrear la base
  de Keycloak; `start-local` lo detecta y lo avisa.
- Las políticas de contraseña siguen siendo del realm compartido.

## Cómo se valida

- La aceptación de M0b corre contra el Keycloak real del Compose:
  - SSO por `idp-test` con JIT y grupos a roles;
  - cuenta propia con TOTP en un tenant con MFA obligatoria;
  - dominio "solo SSO" rechazado con contraseña;
  - Organization en el token y tenant activo;
  - usuario en dos Organizations.
- Pruebas de la API de configuración: OpenFGA por endpoint, aislamiento entre tenants y auditoría sin secretos.
