# ADR-0054 — Programas RPG interactivos: pantallas 5250 y su golden master

- **Estado:** Aceptada · 2026-10-08
- **Secciones:** 7.4 (pantallas), 6.1 fases 7 y 9 (UI y caracterización), 8.4 (destino de frontend)
- **Relacionadas:** ADR-0051 (adaptador RPG), ADR-0052 (ejecución del legado), ADR-0053 (runner de IBM i), M5 (BMS),
  ADR-0016 (packs de frontend); plan de soporte RPG aprobado (R3)

## Contexto

Un programa interactivo de IBM i muestra registros de un archivo de pantalla (DSPF) con `EXFMT`, espera que el
usuario escriba y pulse una tecla, y vuelve a mostrar. La plataforma ya lleva las pantallas de un terminal a la
especificación neutral (mapas BMS de CICS, M5) y de ahí a prototipos y a los packs de React y Angular. El cliente elige
por proyecto si quiere solo el backend (API), solo la web o los dos.

## Decisión

1. **Cada registro de un DSPF es una pantalla** (`ScreenSpec`), como un mapa BMS:
   - campos con posición, longitud y uso (entrada, salida o ambos) y tipo neutral desde su tipo DDS;
   - constantes como literales;
   - `CHECK(ME/MF)` como obligatorio, `ERRMSG` como mensaje, `EDTCDE`/`EDTWRD` como formato, `VALUES`, `RANGE`,
     `COMP` como validación y `DSPATR` como atributos;
   - las teclas de comando (`CFnn` devuelve los datos, `CAnn` no) más ENTER como acciones;
   - el tamaño desde `DSPSIZ`.
   La fase de UI lo toma con `screens_of`, sin cambios en prototipos ni packs.
2. **El golden master de un programa interactivo sale de trazas de sesiones 5250** grabadas en el sistema del cliente
   (motor `ibmi-trace`, techo PARTLY PROVEN): las entradas de cada caso son los campos que el usuario escribió y la
   tecla (`KEY`), las salidas lo que mostró la pantalla después, y las tablas como en batch.
3. **El runner en vivo de IBM i no ejecuta programas interactivos**: un `EXFMT` sin terminal se quedaría esperando.
   Lo rechaza con el motivo y la fase espera; el proyecto usa trazas para ese programa.
4. **El destino de la interfaz es la configuración de destino que ya existe**: frontend `none` es solo backend (API),
   `react` o `angular` es la web, y un backend más un frontend es la modernización completa. No hay una pantalla nueva.

## Alternativas consideradas

- **Emular la sesión 5250 en vivo (tn5250 desde el puente).** Daría PROVEN también a los interactivos, pero exige
  guiones de pantalla por caso y un emulador en el puente. Queda como una mejora posterior sobre las mismas trazas.
- **Un tipo de pantalla propio para 5250.** La especificación neutral ya tiene la grilla, las posiciones y los
  atributos de terminal; un tipo aparte duplicaría prototipos y packs.

## Consecuencias

- Un proyecto RPG interactivo produce pantallas, prototipos y frontend como uno CICS.
- Su veredicto no pasa de PARTLY PROVEN hasta que exista la emulación 5250 en vivo.
- Los subarchivos (`SFL`, `SFLCTL`) se muestran como pantallas, sin semántica de lista paginada todavía.

## Cómo se valida

`packages/adapters/source/rpg/tests/test_screens.py`: la pantalla ficticia `PANTALLA` con sus campos, literales y
F3; tamaño `*DS4`, obligatorio, mensaje, rango y atributos; la fase de UI la lee; el golden master de `CONSCTA` sale
de sus trazas de sesión y el runner en vivo lo rechaza.
