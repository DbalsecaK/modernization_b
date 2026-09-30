      *================================================================
      * PAGODEB - DEBITO DE LA CUENTA DE UN PAGO (APLICACION FICTICIA)
      * SE LLAMA CON LINK DESDE PAGOORD. RESPONDE EN DEB-RESP:
      *   00 DEBITADA, 10 INACTIVA, 20 SALDO INSUFICIENTE,
      *   30 NO EXISTE, 40 EL TIPO NO COINCIDE.
      *================================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAGODEB.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-RESP                PIC S9(8) COMP VALUE ZERO.
           COPY CTAREG.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           COPY PAGDCOM.
       PROCEDURE DIVISION.
       0000-PRINCIPAL.
           EXEC CICS READ FILE('CUENTAS') INTO(CTA-REGISTRO)
                RIDFLD(DEB-CUENTA) UPDATE RESP(WS-RESP)
           END-EXEC.
           EVALUATE TRUE
              WHEN WS-RESP = DFHRESP(NOTFND)
                 MOVE '30' TO DEB-RESP
              WHEN CTA-TIPO NOT = DEB-TIPO
                 MOVE '40' TO DEB-RESP
              WHEN NOT CTA-ACTIVA
                 MOVE '10' TO DEB-RESP
              WHEN CTA-SALDO < DEB-MONTO
                 MOVE '20' TO DEB-RESP
              WHEN OTHER
                 PERFORM 1000-DEBITAR
           END-EVALUATE.
           EXEC CICS RETURN END-EXEC.

       1000-DEBITAR.
           SUBTRACT DEB-MONTO FROM CTA-SALDO.
           EXEC CICS REWRITE FILE('CUENTAS') FROM(CTA-REGISTRO)
           END-EXEC.
           MOVE '00' TO DEB-RESP.
