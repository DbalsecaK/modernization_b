      *================================================================
      * PAGOSQL - DEBITO DE UNA CUENTA EN DB2 (BANCO FICTICIO)
      * SE LLAMA CON UNA COMMAREA Y RESPONDE EN
      * CA-RESP: 00 DEBITADA, 20 SALDO INSUFICIENTE, 30 NO EXISTE.
      *================================================================
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAGOSQL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           EXEC SQL INCLUDE SQLCA END-EXEC.
           EXEC SQL DECLARE SEG.CUENTAS TABLE
                    (NUMERO   CHAR(10) NOT NULL,
                     SALDO    DECIMAL(11,2) NOT NULL,
                     ESTADO   CHAR(1) NOT NULL)
           END-EXEC.
       01  W-SALDO                PIC S9(11)V99 COMP-3 VALUE ZERO.
       01  W-ESTADO               PIC X VALUE SPACE.
       01  W-CUENTA               PIC X(10) VALUE SPACES.
       01  W-MONTO                PIC S9(11)V99 COMP-3 VALUE ZERO.
       LINKAGE SECTION.
       01  DFHCOMMAREA.
           05  CA-CUENTA          PIC X(10).
           05  CA-MONTO           PIC 9(9)V99.
           05  CA-RESP            PIC XX.
       PROCEDURE DIVISION.
       0000-PRINCIPAL.
           MOVE CA-CUENTA TO W-CUENTA.
           MOVE CA-MONTO TO W-MONTO.
           EXEC SQL SELECT SALDO, ESTADO INTO :W-SALDO, :W-ESTADO
                    FROM SEG.CUENTAS WHERE NUMERO = :W-CUENTA
                    WITH UR
           END-EXEC.
           EVALUATE TRUE
              WHEN SQLCODE = 100
                 MOVE '30' TO CA-RESP
              WHEN SQLCODE NOT = 0
                 EXEC CICS ABEND ABCODE('NXSQ') END-EXEC
              WHEN W-SALDO < W-MONTO
                 MOVE '20' TO CA-RESP
              WHEN OTHER
                 PERFORM 1000-DEBITAR
           END-EVALUATE.
           EXEC CICS RETURN END-EXEC.

       1000-DEBITAR.
           EXEC SQL UPDATE SEG.CUENTAS
                    SET SALDO = SALDO - :W-MONTO
                    WHERE NUMERO = :W-CUENTA
           END-EXEC.
           IF SQLCODE = 0
              MOVE '00' TO CA-RESP
              EXEC CICS SYNCPOINT END-EXEC
           ELSE
              MOVE '40' TO CA-RESP
              EXEC CICS SYNCPOINT ROLLBACK END-EXEC
           END-IF.
