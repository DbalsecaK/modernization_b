      *================================================================
      * PAGOMNU - MENU DE PAGOS (BANCO FICTICIO, APLICACION FICTICIA)
      * TRANSACCION PGMN CON EL MAPA PAGOMEN. OPCION 1 ABRE EL PAGO DE
      * ORDENES (XCTL A PAGOORD); OPCION 9 O PF3 TERMINA.
      *================================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAGOMNU.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                PIC S9(8) COMP VALUE ZERO.
       01  WS-FIN                 PIC X(20) VALUE 'SESION TERMINADA'.
       01  WS-COMMAREA.
           COPY PAGOCOM.
           COPY PAGOSET.
           COPY DFHAID.
       LINKAGE SECTION.
       01  DFHCOMMAREA            PIC X(13).
       PROCEDURE DIVISION.
       0000-PRINCIPAL.
           IF EIBCALEN = ZERO
              PERFORM 1000-MOSTRAR-MENU
           ELSE
              IF EIBAID = DFHPF3
                 PERFORM 9000-TERMINAR
              ELSE
                 PERFORM 2000-ELEGIR-OPCION
              END-IF
           END-IF.
           EXEC CICS RETURN TRANSID('PGMN')
                COMMAREA(WS-COMMAREA) LENGTH(13)
           END-EXEC.

       1000-MOSTRAR-MENU.
           MOVE LOW-VALUES TO PAGOMENO.
           EXEC CICS SEND MAP('PAGOMEN') MAPSET('PAGOSET')
                FROM(PAGOMENO) ERASE
           END-EXEC.

       2000-ELEGIR-OPCION.
           EXEC CICS RECEIVE MAP('PAGOMEN') MAPSET('PAGOSET')
                INTO(PAGOMENI) RESP(WS-RESP)
           END-EXEC.
           EVALUATE OPCIONI
              WHEN '1'
                 EXEC CICS XCTL PROGRAM('PAGOORD')
                      COMMAREA(WS-COMMAREA) LENGTH(13)
                 END-EXEC
              WHEN '9'
                 PERFORM 9000-TERMINAR
              WHEN OTHER
                 MOVE 'OPCION NO VALIDA' TO MENSAJEO OF PAGOMENO
                 EXEC CICS SEND MAP('PAGOMEN') MAPSET('PAGOSET')
                      FROM(PAGOMENO) DATAONLY
                 END-EXEC
           END-EVALUATE.

       9000-TERMINAR.
           EXEC CICS SEND TEXT FROM(WS-FIN) LENGTH(20) ERASE
           END-EXEC.
           EXEC CICS RETURN END-EXEC.
