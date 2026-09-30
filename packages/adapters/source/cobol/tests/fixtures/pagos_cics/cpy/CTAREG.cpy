      * CTAREG - REGISTRO DEL ARCHIVO VSAM CUENTAS (KSDS)
       01  CTA-REGISTRO.
           05  CTA-NUMERO             PIC 9(10).
           05  CTA-TIPO               PIC X(3).
           05  CTA-SALDO              PIC S9(11)V99 COMP-3.
           05  CTA-ESTADO             PIC X.
               88  CTA-ACTIVA         VALUE 'A'.
               88  CTA-INACTIVA       VALUE 'I'.
