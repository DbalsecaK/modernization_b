      * ORDREG - REGISTRO DEL ARCHIVO VSAM ORDENES (KSDS)
       01  ORD-REGISTRO.
           05  ORD-CLAVE.
               10  ORD-NUMERO         PIC 9(7).
               10  ORD-EMPRESA        PIC 9(5).
           05  ORD-ESTADO             PIC X.
               88  ORD-PENDIENTE      VALUE 'P'.
               88  ORD-PAGADA         VALUE 'G'.
           05  ORD-VALOR              PIC S9(9)V99 COMP-3.
           05  ORD-MOVIM              PIC 9(10).
           05  ORD-COMIS              PIC S9(3)V99 COMP-3.
           05  FILLER                 PIC X(10).
