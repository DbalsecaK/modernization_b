      *================================================================
      * PAGOORD - PAGO DE ORDENES (BANCO FICTICIO, APLICACION FICTICIA)
      * TRANSACCION PGOR, PSEUDO-CONVERSACIONAL CON EL MAPA PAGOORD.
      * VALIDA LA ORDEN, CALCULA LA COMISION, DEBITA LA CUENTA (PAGODEB)
      * Y REGISTRA EL PAGO CON EL NUMERO DE MOVIMIENTO DE PAGOMOV.
      *================================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAGOORD.
       ENVIRONMENT DIVISION.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-COMISION            PIC S9(3)V99 COMP-3 VALUE ZERO.
       01  WS-TOTAL               PIC S9(11)V99 COMP-3 VALUE ZERO.
       01  WS-VALOR               PIC S9(9)V99 COMP-3 VALUE ZERO.
       01  WS-RESP                PIC S9(8) COMP VALUE ZERO.
       01  WS-MENSAJE             PIC X(78) VALUE SPACES.
       01  WS-ERROR               PIC X VALUE 'N'.
           88  HAY-ERROR          VALUE 'S'.
           88  SIN-ERROR          VALUE 'N'.
       01  WS-CLAVE-ORDEN.
           05  WS-CL-NUMERO       PIC 9(7).
           05  WS-CL-EMPRESA      PIC 9(5).
       01  WS-DEBCOM.
           COPY PAGDCOM.
       01  WS-MOVCOM.
           05  MOV-ORDEN          PIC 9(7).
           05  MOV-NUMERO         PIC 9(10).
       01  WS-COMMAREA.
           COPY PAGOCOM.
           COPY ORDREG.
           COPY PAGOSET.
           COPY DFHAID.
       LINKAGE SECTION.
       01  DFHCOMMAREA            PIC X(13).
       PROCEDURE DIVISION.
       0000-PRINCIPAL.
           IF EIBCALEN = ZERO
              PERFORM 1000-PRIMERA-VEZ
           ELSE
              MOVE DFHCOMMAREA TO WS-COMMAREA
              EVALUATE EIBAID
                 WHEN DFHPF3
                    PERFORM 9000-VOLVER-MENU
                 WHEN DFHENTER
                    PERFORM 2000-PROCESAR
                 WHEN OTHER
                    MOVE 'TECLA NO VALIDA' TO WS-MENSAJE
                    PERFORM 8000-ENVIAR-ERROR
              END-EVALUATE
           END-IF.
           EXEC CICS RETURN TRANSID('PGOR')
                COMMAREA(WS-COMMAREA) LENGTH(13)
           END-EXEC.

       1000-PRIMERA-VEZ.
           MOVE LOW-VALUES TO PAGOORDO.
           MOVE 'WEB' TO CANALO.
           EXEC CICS SEND MAP('PAGOORD') MAPSET('PAGOSET')
                FROM(PAGOORDO) ERASE
           END-EXEC.

       2000-PROCESAR.
           EXEC CICS RECEIVE MAP('PAGOORD') MAPSET('PAGOSET')
                INTO(PAGOORDI) RESP(WS-RESP)
           END-EXEC.
           SET SIN-ERROR TO TRUE.
           PERFORM 2100-VALIDAR-ENTRADA.
           IF SIN-ERROR
              PERFORM 2200-LEER-ORDEN
           END-IF.
           IF SIN-ERROR
              PERFORM 2300-CALCULAR-COMISION
              PERFORM 2400-DEBITAR-CUENTA
           END-IF.
           IF SIN-ERROR
              PERFORM 2500-REGISTRAR-PAGO
              PERFORM 2600-ENVIAR-RESULTADO
           ELSE
              PERFORM 8000-ENVIAR-ERROR
           END-IF.

       2100-VALIDAR-ENTRADA.
           IF ORDENI NOT NUMERIC OR ORDENI = ZEROS
              MOVE 'NUMERO DE ORDEN INVALIDO' TO WS-MENSAJE
              SET HAY-ERROR TO TRUE
           ELSE
              IF TIPCTAI NOT = 'CTE' AND TIPCTAI NOT = 'AHO'
                 AND TIPCTAI NOT = 'VIR'
                 MOVE 'TIPO DE CUENTA NO PERMITIDO' TO WS-MENSAJE
                 SET HAY-ERROR TO TRUE
              ELSE
                 IF CANALI NOT = 'WEB' AND CANALI NOT = 'OFI'
                    MOVE 'CANAL NO PERMITIDO' TO WS-MENSAJE
                    SET HAY-ERROR TO TRUE
                 ELSE
                    IF CANALI = 'OFI' AND CLAVEI = SPACES
                       MOVE 'CLAVE DE APROBACION REQUERIDA'
                         TO WS-MENSAJE
                       SET HAY-ERROR TO TRUE
                    END-IF
                 END-IF
              END-IF
           END-IF.

       2200-LEER-ORDEN.
           MOVE ORDENI TO WS-CL-NUMERO.
           MOVE EMPRESAI TO WS-CL-EMPRESA.
           EXEC CICS READ FILE('ORDENES') INTO(ORD-REGISTRO)
                RIDFLD(WS-CLAVE-ORDEN) UPDATE RESP(WS-RESP)
           END-EXEC.
           IF WS-RESP = DFHRESP(NOTFND)
              MOVE 'ORDEN NO EXISTE' TO WS-MENSAJE
              SET HAY-ERROR TO TRUE
           ELSE
              IF NOT ORD-PENDIENTE
                 MOVE 'ORDEN NO ESTA PENDIENTE' TO WS-MENSAJE
                 SET HAY-ERROR TO TRUE
              ELSE
                 COMPUTE WS-VALOR = FUNCTION NUMVAL(VALORI) / 100
                 IF WS-VALOR NOT = ORD-VALOR
                    MOVE 'VALOR NO COINCIDE CON LA ORDEN'
                      TO WS-MENSAJE
                    SET HAY-ERROR TO TRUE
                 END-IF
              END-IF
           END-IF.

       2300-CALCULAR-COMISION.
           IF ORD-VALOR >= 50000
              MOVE ZERO TO WS-COMISION
           ELSE
              IF CANALI = 'WEB'
                 MOVE 1.00 TO WS-COMISION
              ELSE
                 MOVE 2.50 TO WS-COMISION
              END-IF
           END-IF.
           COMPUTE WS-TOTAL = ORD-VALOR + WS-COMISION.

       2400-DEBITAR-CUENTA.
           MOVE CUENTAI TO DEB-CUENTA.
           MOVE TIPCTAI TO DEB-TIPO.
           MOVE WS-TOTAL TO DEB-MONTO.
           EXEC CICS LINK PROGRAM('PAGODEB') COMMAREA(WS-DEBCOM)
                LENGTH(LENGTH OF WS-DEBCOM)
           END-EXEC.
           EVALUATE DEB-RESP
              WHEN '00'
                 CONTINUE
              WHEN '10'
                 MOVE 'CUENTA INACTIVA' TO WS-MENSAJE
                 SET HAY-ERROR TO TRUE
              WHEN '20'
                 MOVE 'SALDO INSUFICIENTE' TO WS-MENSAJE
                 SET HAY-ERROR TO TRUE
              WHEN OTHER
                 MOVE 'CUENTA NO VALIDA' TO WS-MENSAJE
                 SET HAY-ERROR TO TRUE
           END-EVALUATE.

       2500-REGISTRAR-PAGO.
           MOVE ORD-NUMERO TO MOV-ORDEN.
           EXEC CICS LINK PROGRAM('PAGOMOV') COMMAREA(WS-MOVCOM)
                LENGTH(17)
           END-EXEC.
           SET ORD-PAGADA TO TRUE.
           MOVE MOV-NUMERO TO ORD-MOVIM.
           MOVE WS-COMISION TO ORD-COMIS.
           EXEC CICS REWRITE FILE('ORDENES') FROM(ORD-REGISTRO)
           END-EXEC.
           MOVE ORD-NUMERO TO CA-ULTIMA-ORDEN.
           EXEC CICS SYNCPOINT END-EXEC.

       2600-ENVIAR-RESULTADO.
           MOVE LOW-VALUES TO PAGORESO.
           MOVE ORD-NUMERO TO RORDENO.
           MOVE WS-COMISION TO RCOMISO.
           MOVE MOV-NUMERO TO RMOVIMO.
           MOVE 'PAGO REALIZADO' TO RMENSO.
           EXEC CICS SEND MAP('PAGORES') MAPSET('PAGOSET')
                FROM(PAGORESO) ERASE
           END-EXEC.

       8000-ENVIAR-ERROR.
           MOVE WS-MENSAJE TO MENSAJEO OF PAGOORDO.
           EXEC CICS SEND MAP('PAGOORD') MAPSET('PAGOSET')
                FROM(PAGOORDO) DATAONLY
           END-EXEC.

       9000-VOLVER-MENU.
           EXEC CICS XCTL PROGRAM('PAGOMNU')
           END-EXEC.
