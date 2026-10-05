# ADR-0039 — Estudio de adaptadores: adaptadores de origen declarados por el cliente

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 8.1 (principio N+M), 8.2 (contrato del adaptador), 8.6 (niveles de soporte), 12 (modelos por el gateway)
- **Relacionadas:** ADR-0011 (código del cliente), ADR-0033 (extracción guiada), ADR-0037 (versiones por eje)

## Contexto

Los adaptadores de origen son código de la plataforma (Sybase, COBOL, CICS/BMS, ASPX). Un cliente con una
tecnología fuera de la lista no podía avanzar hasta que alguien la programara. El aprobador pidió autogestión:
crear adaptadores desde la plataforma con ayuda de un modelo.

Dos límites del diseño: un adaptador gana su nivel con evidencia (golden master o trazas), y nada que escriba un
modelo se ejecuta como código en la plataforma.

## Decisión

- **Un adaptador declarado es una especificación, no código:** extensiones, prefijos de comentario y patrones
  (expresiones regulares evaluadas línea a línea) para la unidad, los parámetros, las llamadas, las lecturas y
  escrituras de tablas, las palabras de infraestructura y de control, y el mapa de tipos neutros. La plataforma la
  valida (grupos nombrados, expresiones compilables, clave única y distinta de las del catálogo) y la ejecuta con un
  único intérprete propio: `DeclarativeAdapter`, que cumple el contrato de 8.2 (inventario, tipos, slices,
  clasificación, datos por rango, resumen).
- **El estudio** (`/api/v1/adapters`, permiso `models.configure`): probar la declaración sobre muestras sin guardar
  nada (`:try`), pedir a un modelo un borrador a partir de las muestras y la descripción (`:draft`, por el gateway,
  con el perfil del cliente para la fase `catalog`; el borrador se valida y se prueba por código antes de mostrarse),
  guardar, actualizar y borrar. Todo auditado.
- **Privado del cliente:** los adaptadores viven en `tenant_adapter` con RLS. El catálogo que ve cada cliente suma
  los suyos como adaptadores **experimentales** (evidencia `none`) con su opción de origen para los flujos 1 y 4; la
  corrida los registra al arrancar y `pick_adapter` los considera junto a los de la plataforma.
- **Lo que no promete:** sin motor ni trazas no hay golden master: la caracterización espera y el veredicto no pasa
  de PARTLY PROVEN. Los slices son la unidad completa (sin análisis de dependencias). Pasar a *assisted* o
  *certified* sigue exigiendo un adaptador programado, fixtures y una aceptación grabada.

## Consecuencias

- Un cliente inventaría, clasifica y extrae reglas de una tecnología nueva el mismo día, con la etiqueta de
  experimental a la vista.
- El modelo ayuda a escribir la declaración; la declaración se ejecuta igual con o sin él, y el código del cliente
  nunca sale del gateway ni entra al repositorio (ADR-0011).
- Las muestras que se pegan en el estudio van al modelo elegido por el cliente: la pantalla lo advierte.
