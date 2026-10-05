# ADR-0036 — La suite de caracterización en piezas acotadas

- **Estado:** Aceptada · 2026-10-05
- **Secciones:** 6.1 (fase 9, caracterización), 11.1 (hacer, verificar, corregir), 12 (modelos y topes de salida)
- **Relacionadas:** ADR-0033 (extracción guiada), ADR-0034 (respuestas cortadas)

## Contexto

La caracterización pedía al agente de pruebas **una sola respuesta** con toda la suite: el esquema de todas las
tablas y todos los casos con sus filas. Con un procedimiento de 2.000 líneas y 14 reglas, la respuesta superó el tope
de salida del perfil tres veces seguidas; la plataforma ya detecta el corte (ADR-0034), pero el tamaño de la respuesta
crecía con el programa y un tope mayor solo aplaza el problema.

Las demás fases ya trabajan por partes: la extracción por slices, las descripciones por lotes, la generación por caso
de uso. La caracterización era la excepción, junto con el diseño.

## Decisión

Con la opción `guided_extraction`, la suite se pide en piezas que el código une:

1. **El esquema primero:** un pedido que devuelve `program` y `schema`, sin casos.
2. **Los casos por grupos de seis reglas**, en orden de identificador: cada pedido lleva el esquema acordado y solo
   las reglas del grupo, y devuelve sus casos.
3. **El código une las piezas** en la suite completa: nombres de caso únicos (sufijo a los repetidos), validación del
   modelo, cobertura de reglas y ejecución en el motor del legado, como hasta ahora.
4. **Un diagnóstico vuelve a pedir solo las piezas que señala** (por identificador de regla o nombre de caso); si no
   señala ninguna, se repiten todas. El esquema solo se repite si el diagnóstico lo menciona.

Cada pedido queda acotado sin importar el tamaño del programa. Los cortes se tratan por pieza con la regla de
ADR-0034. Sin la opción, el pedido único de siempre: las grabaciones no cambian.

## Consecuencias

- Un programa con 60 reglas hace 1 + 10 pedidos pequeños en lugar de uno gigante; el costo total es parecido y el
  riesgo de corte desaparece.
- La reparación tras un diagnóstico es más barata: solo el grupo afectado.
- El diseño sigue siendo una respuesta por programa; su partición queda para cuando un caso real lo exija.
