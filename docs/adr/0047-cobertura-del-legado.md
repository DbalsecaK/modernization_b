# ADR-0047 — Cobertura del legado: qué ramas del programa ejercitó el golden master

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 11.3 (golden master), 6.1 fase 9 (caracterización), 11.2 (veredicto)
- **Relacionadas:** ADR-0044 (comparación honesta), ADR-0046 (caracterización rápida), plan aprobado (M27a)

## Contexto

PROVEN prueba que el destino hace lo mismo que el legado **en los casos del golden master**. Si ningún caso entra
por una rama del programa, el destino podría omitirla y el veredicto no lo diría. "No perder código" era una
suposición; hacía falta medirla, con scripts y no con la opinión de un modelo.

## Decisión

1. **Contrato neutral.** El golden master lleva una `coverage` opcional: las ramas del programa (la THEN y la ELSE
   de un IF, la ELSE implícita, el cuerpo de un bucle) con su id estable `línea_inicio-línea_fin:tipo`, si son
   medibles, qué ramas recorrió cada caso y qué casos no tienen cobertura confiable. Un adaptador que no mide deja
   la cobertura vacía y nada cambia (se omite al serializar: las grabaciones no cambian).
2. **Sybase primero, sin tocar el oráculo.** El golden master se graba siempre con el programa original. Después,
   en el mismo motor, se instala una **copia instrumentada** con un `print 'NXB|<id>'` como primera sentencia de cada
   rama y se ejecutan los mismos casos. Si en un caso la copia observa algo distinto del original, ese caso queda
   como "cobertura no confiable"; el golden master nunca sale de esta pasada.
3. **Honestidad sobre lo no medible.** Una rama que no se puede marcar sin riesgo (un cuerpo de una sentencia que
   comparte línea con la condición o con otra sentencia) se reporta como no medible, nunca como cubierta.
4. **En el veredicto y en C4.** La caracterización resume la cobertura ("24 de 26 ramas medibles ejercitadas") y la
   verificación añade a "lo que no prueba" la cobertura y cada rama sin caso, con sus líneas. La condición de
   aprobación con estos datos la fija el ADR del veredicto (paso 8 del plan).
5. **Mutación del detector.** Una prueba borra una rama del servicio de referencia del pack Java y exige que el
   golden master difiera en el caso que la ejercita.

## Consecuencias

- Una segunda pasada de los casos en el mismo motor (con lotes y caché de 3b, alrededor de un minuto).
- Las ramas sin caso quedan visibles; M27b las devolverá al test engineer para que escriba los casos que faltan.
- COBOL y ASPX lo implementarán como capacidad de su adaptador (paso 5 del plan).

## Cómo se valida

Pruebas unitarias de instrumentación (el ficticio queda marcado y sigue siendo un procedimiento válido; una rama de
una línea es no medible), de la segunda pasada (caso no confiable cuando la copia difiere) y de mutación; y la prueba
en vivo con Sybase: la grabación se reproduce y la cobertura es confiable en los 12 casos (24 de 26 ramas).

## Precisión M27b (2026-10-07): casos por rama y código citado

- **Una ronda por las ramas sin caso.** En el diseño guiado, después de grabar el golden master, si la cobertura
  tiene ramas medibles que ningún caso recorrió, la caracterización devuelve al test engineer una sola vez la lista
  de esas ramas (hasta 25): tipo, líneas, el código numerado alrededor y las reglas cuyas citas las tocan. La
  instrucción es conservar todos los casos y agregar los que entren a cada rama, o decir que la rama es inalcanzable.
  Lo que siga sin cubrir tras esa ronda va al reporte y al "no probado" del veredicto; no hay bucle.
- **La rama conoce su archivo** (`CoveredBranch.file`), para citar el código correcto cuando hay varios fuentes.
- **Código citado por regla.** La extracción guiada guarda `rules/citations.json`: por regla, cada cita con sus
  líneas de código (hasta 80 por cita, marcada como truncada si hay más). La tarjeta de regla en C1 muestra cada cita
  desplegable con el código numerado, para que el aprobador revise la regla contra el programa sin salir de la
  pantalla. Es un artefacto de documentación del proyecto, como el resto del código del legado en el espacio de
  trabajo; no entra en fixtures ni en el repositorio.

## Precisión paso 11 (2026-10-07): cobertura de COBOL y ASPX desde las trazas

COBOL/CICS y WebForms no corren en la plataforma: su golden master son trazas (ADR-0015, ADR-0020). Su cobertura
también sale de ellas:

- **La unidad** la da el adaptador (`coverage_branches`): los párrafos de un programa COBOL y los métodos del
  code-behind y de App_Code de una página. Es lo que las herramientas de trazas de esos entornos reportan.
- **La traza** puede traer, por resultado, `executed`: los párrafos o métodos que la herramienta vio ejecutar. El
  runner de trazas arma la cobertura solo si todos los casos lo traen; un caso sin `executed` no es un caso que no
  ejecutó nada.
- Desde ahí todo es igual que en Sybase: huecos, tarjeta de decisión de ADR-0050 y "no probado". El veredicto de
  trazas sigue limitado a PARTLY PROVEN.
