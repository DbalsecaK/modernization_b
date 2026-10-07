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
