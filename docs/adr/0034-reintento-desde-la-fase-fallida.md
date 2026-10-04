# ADR-0034 — Reintento desde la fase fallida y verificación por código que no pierde trabajo

- **Estado:** Aceptada · 2026-10-04
- **Secciones:** 10.4 (ciclo de vida de una corrida), 11.1 (hacer, verificar, corregir), 6.1 (fases 5 y 8)
- **Relacionadas:** ADR-0009 (cola y checkpoints), ADR-0033 (extracción guiada)

## Contexto

Al probar la plataforma con un procedimiento real, tres corridas seguidas terminaron en "fallida" por motivos que no
eran del código del cliente:

1. El arquitecto escribió la clave de una entidad con el nombre de la columna del legado, no con el del campo.
2. Un método de puerto devolvía `void` como texto, y otro un decimal que los generadores no saben devolver.
3. El arquitecto citó nombres del legado "que no existen", y un slice de la extracción citó líneas fuera de su slice.

Cada vez hubo que lanzar una corrida nueva: repetir el inventario, la extracción (con su costo) y la aprobación de
C1 por otra persona. Los dos primeros motivos ya se corrigieron en el modelo del diseño. Este ADR cubre el tercero y
el problema de fondo: **un fallo en una fase tiraba toda la corrida**.

## Decisión

### Reintento desde la fase fallida

- Una corrida fallida ya no termina el grafo: queda esperando en un nodo `retry`, con el estado `failed` en la base
  de datos y la fase que falló en el estado del grafo.
- `POST /runs/{id}:retry` (permiso `pipeline.run`, solo sobre una corrida `failed`, una corrida activa por
  proyecto) la vuelve a encolar. El worker la reanuda con `{"retry": true}` y el grafo salta a la fase que falló:
  - las fases anteriores no se repiten y conservan sus resultados (reglas, historias, compuertas aprobadas);
  - la fase fallida vuelve a correr desde cero, con llamadas nuevas al modelo;
  - una compuerta rechazada reintenta la fase anterior a la compuerta.
- Queda auditado (`run.retry`) y la web lo ofrece con el botón **Reintentar desde la fase fallida**.
- Una corrida que falló antes de este cambio no tiene dónde reanudarse: el worker la deja fallida con la explicación
  y hay que lanzar una nueva.

### La verificación por código no pierde trabajo válido

- **Nombres del legado en el diseño.** Se comparan sin marcadores (`@o_trn` y `o_trn` son el mismo parámetro),
  sin caracteres invisibles y con normalización Unicode. Con la extracción guiada, el error le dice al modelo los
  nombres reales más parecidos a cada nombre inventado, o que no cite el que no se parece a ninguno.
- **Citas fuera del slice en la extracción.** Un slice de más de doce trozos está fragmentado: se aceptan citas de
  bloque completo. Y en el último intento, una regla cuyo único problema es citar fuera del slice se conserva con
  confianza baja y una pregunta, porque el verificador lee las líneas citadas del archivo entero y la juzga. El
  slice ya no se pierde.

## Consecuencias

- Un fallo en Arquitectura cuesta ahora solo esa fase, no toda la corrida.
- Las grabaciones existentes (M4, M6, M17, M18) no cambian: los mensajes al modelo son los mismos sin la opción, y
  en ellas ningún slice ni diseño llegaba a su último intento fallido.
- Las pruebas que esperaban que una corrida fallida dejara el grafo sin interrupciones ahora ven una espera de tipo
  `failed` con la fase.
