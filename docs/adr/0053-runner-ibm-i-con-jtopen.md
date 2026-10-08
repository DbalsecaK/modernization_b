# ADR-0053 — Runner en vivo de IBM i con JTOpen en un contenedor puente

- **Estado:** Aceptada · 2026-10-07
- **Secciones:** 6.1 fase 9 (caracterización), 11.3 (golden master), 15 (sandbox)
- **Relacionadas:** ADR-0052 (ejecución del legado por proyecto), ADR-0051 (adaptador RPG), ADR-0047 (cobertura),
  ADR-0046 (fase no disponible), ADR-0007 (secretos); plan de soporte RPG aprobado (R2b)

## Contexto

Con ADR-0052 un proyecto puede declarar que su legado corre en un IBM i del cliente. Falta quien lo ejecute: cargar
las filas de cada caso, llamar al programa RPG con sus parámetros y leer lo que dejó. El worker es Python y corre
en contenedores; el IBM i está en la red del cliente.

## Decisión

1. **JTOpen (jt400) en un contenedor puente** (`infra/sandbox/ibmi-bridge`, imagen `nexti-ibmi-bridge:1`): la
   biblioteca Java de código abierto de IBM. Solo necesita los host servers que todo IBM i trae (sign-on, comandos
   remotos, base de datos); nada se instala en el sistema del cliente.
2. **Un contenedor por suite**, sin privilegios (`--cap-drop ALL`, `no-new-privileges`, solo lectura, límites de
   memoria y procesos). Es el único sandbox con red, porque debe llegar al IBM i. La petición llega por stdin con las
   credenciales: nunca en argumentos, variables de entorno ni registros.
3. **Por caso**, en la biblioteca de prueba configurada (primera en la lista de bibliotecas del trabajo):
   - vacía las tablas de la suite y del caso, y carga las filas del caso;
   - llama al programa (`ProgramCall`) con los parámetros tipados que da el parser: empaquetado, zonado, texto fijo en
     el CCSID del proyecto y enteros binarios;
   - lee los parámetros y las tablas después de la llamada, en forma canónica (decimales con su escala, fechas ISO,
     texto fijo sin blancos finales). Un mensaje de escape del programa es el `error` del caso.
4. **Los fallos dicen qué hacer.** El sistema no responde: transitorio, la plataforma reintenta (ADR-0046). Sign-on
   rechazado o biblioteca inutilizable: la fase espera a que se corrija la configuración. Una suite que no encaja (un
   programa que no está en los insumos): vuelve al test engineer. Un caso no puede reemplazar con stubs los programas
   que llama: en un IBM i vivo corren los reales.
5. **El golden master** lleva el motor `ibmi` (no está en `TRACE_ENGINES`, así que el veredicto puede llegar a
   PROVEN) y el entorno medido: la versión del sistema y el CCSID.
6. **Alcance de R2b:** programas (*PGM). La cobertura no se mide en el IBM i todavía: como en todo motor sin
   medición, el chequeo «Legado cubierto» de ADR-0050 no se aplica y el veredicto puede llegar a PROVEN sin probar que
   cada subrutina fue ejercitada. Medirla (por ejemplo con el depurador o los datos de rendimiento del sistema), los
   procedimientos exportados de un *SRVPGM y los quirks de RPG (R4) quedan para después.

## Alternativas consideradas

- **Controlador ODBC de IBM i Access para Linux.** Su descarga requiere una cuenta de IBM y no se puede construir en
  CI sin credenciales.
- **Mapepire.** Exige instalar y arrancar un servidor en el IBM i del cliente.
- **Llamadas SQL (`CALL` a un procedimiento externo).** Exige registrar cada programa como procedimiento en el
  sistema del cliente.

## Consecuencias

- No hay IBM i en CI: el puente se compila en CI y el runner se prueba con el puente reemplazado. La primera
  validación de punta a punta necesita un IBM i de prueba (por ejemplo PUB400 con el espacio de trabajo ficticio).
- En Kubernetes, la política de red del worker debe permitir la salida al IBM i del cliente.
- El sistema del cliente ejecuta código del cliente en su propia biblioteca de prueba; la plataforma nunca escribe
  fuera de ella.

## Cómo se valida

`packages/adapters/source/rpg/tests/test_ibmi.py`: la petición lleva los parámetros tipados del programa, las filas
y las bibliotecas; la respuesta se vuelve golden master; cada clase de fallo se mapea a esperar, reintentar o
corregir la suite. La imagen se construye en CI. Con el puente real, un host inexistente responde un error de
conexión en JSON.
