      * PAGOSET - MAPA SIMBOLICO DEL MAPSET PAGOSET (GENERADO POR BMS)
       01  PAGOMENI.
           05  FILLER                 PIC X(12).
           05  OPCIONL                PIC S9(4) COMP.
           05  OPCIONF                PIC X.
           05  OPCIONI                PIC X.
           05  MENSAJEL               PIC S9(4) COMP.
           05  MENSAJEF               PIC X.
           05  MENSAJEI               PIC X(78).
       01  PAGOMENO REDEFINES PAGOMENI.
           05  FILLER                 PIC X(15).
           05  OPCIONO                PIC X.
           05  FILLER                 PIC X(3).
           05  MENSAJEO               PIC X(78).
       01  PAGOORDI.
           05  FILLER                 PIC X(12).
           05  ORDENL                 PIC S9(4) COMP.
           05  ORDENF                 PIC X.
           05  ORDENI                 PIC X(7).
           05  EMPRESAL               PIC S9(4) COMP.
           05  EMPRESAF               PIC X.
           05  EMPRESAI               PIC X(5).
           05  SERVICL                PIC S9(4) COMP.
           05  SERVICF                PIC X.
           05  SERVICI                PIC X(10).
           05  TIPCTAL                PIC S9(4) COMP.
           05  TIPCTAF                PIC X.
           05  TIPCTAI                PIC X(3).
           05  CUENTAL                PIC S9(4) COMP.
           05  CUENTAF                PIC X.
           05  CUENTAI                PIC X(10).
           05  VALORL                 PIC S9(4) COMP.
           05  VALORF                 PIC X.
           05  VALORI                 PIC X(11).
           05  CANALL                 PIC S9(4) COMP.
           05  CANALF                 PIC X.
           05  CANALI                 PIC X(3).
           05  CLAVEL                 PIC S9(4) COMP.
           05  CLAVEF                 PIC X.
           05  CLAVEI                 PIC X(6).
           05  MENSAJEL               PIC S9(4) COMP.
           05  MENSAJEF               PIC X.
           05  MENSAJEI               PIC X(78).
       01  PAGOORDO REDEFINES PAGOORDI.
           05  FILLER                 PIC X(15).
           05  ORDENO                 PIC X(7).
           05  FILLER                 PIC X(3).
           05  EMPRESAO               PIC X(5).
           05  FILLER                 PIC X(3).
           05  SERVICO                PIC X(10).
           05  FILLER                 PIC X(3).
           05  TIPCTAO                PIC X(3).
           05  FILLER                 PIC X(3).
           05  CUENTAO                PIC X(10).
           05  FILLER                 PIC X(3).
           05  VALORO                 PIC X(11).
           05  FILLER                 PIC X(3).
           05  CANALO                 PIC X(3).
           05  FILLER                 PIC X(3).
           05  CLAVEO                 PIC X(6).
           05  FILLER                 PIC X(3).
           05  MENSAJEO               PIC X(78).
       01  PAGORESI.
           05  FILLER                 PIC X(12).
           05  RORDENL                PIC S9(4) COMP.
           05  RORDENF                PIC X.
           05  RORDENI                PIC X(7).
           05  RCOMISL                PIC S9(4) COMP.
           05  RCOMISF                PIC X.
           05  RCOMISI                PIC X(10).
           05  RMOVIML                PIC S9(4) COMP.
           05  RMOVIMF                PIC X.
           05  RMOVIMI                PIC X(10).
           05  RMENSL                 PIC S9(4) COMP.
           05  RMENSF                 PIC X.
           05  RMENSI                 PIC X(40).
       01  PAGORESO REDEFINES PAGORESI.
           05  FILLER                 PIC X(15).
           05  RORDENO                PIC 9(7).
           05  FILLER                 PIC X(3).
           05  RCOMISO                PIC ZZZ,ZZ9.99.
           05  FILLER                 PIC X(3).
           05  RMOVIMO                PIC Z(9)9.
           05  FILLER                 PIC X(3).
           05  RMENSO                 PIC X(40).
