# Plan P9 — Administración completa en la web

- **Estado:** cerrado (2026-10-04).
- **Fuente:** sección 17 (administración). No cambia la especificación ni la API: solo agrega pantallas para
  operaciones que la API ya tenía.
- **Rama:** `p9-administracion-completa`.

## 1. Motivo

Al probar la compuerta C1, la segregación de funciones exigía que otra persona la aprobara. Esa persona solo tenía
rol de observador en el proyecto, y la web no tenía forma de asignarle otro rol: solo la invitación daba el primero.
Al comparar la API con la web aparecieron otras tres operaciones sin pantalla.

## 2. Qué se agregó

| Pestaña | Antes | Ahora |
|---|---|---|
| Usuarios | Invitar, suspender, reactivar, quitar del cliente | Además: **asignar rol** (del cliente o de un proyecto) a un miembro y **quitar** un rol desde su etiqueta |
| Roles y permisos | Crear, borrar, editar la matriz de permisos | Además: **renombrar** un rol propio del cliente |
| Clientes (superadministrador) | Crear | Además: **editar** nombre, modelo de despliegue, idioma y estado (activo o suspendido) |

Cada cambio pasa por la API: OpenFGA lo autoriza y la auditoría lo registra.

## 3. Lo que sigue sin pantalla, a propósito

- **SCIM (`/scim/v2`).** La consume el proveedor de identidad, no una persona. Su token se gestiona en la pestaña
  Autenticación.
- **Exportación de auditoría y descargas.** Son enlaces directos, no llamadas desde la web.

## 4. Pruebas

Se agregó una prueba de punta a punta en `e2e/admin.spec.ts`: asigna a un miembro un rol de proyecto y se lo quita,
con axe sobre el diálogo.
