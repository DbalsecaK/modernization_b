00100HDFTACTGRP(*NO)
00200FCONSCTAD  CF   E             WORKSTN
00300FCUENTASL1 IF   E           K DISK
00400DWSALIR           S               N
00500C                   DOW       NOT *IN03
00600C                   EXFMT     PANTALLA
00700C                   IF        *IN03
00800C                   LEAVE
00900C                   ENDIF
01000C     SCCTA         CHAIN     RCUENTA1
01100C                   IF        %FOUND(CUENTASL1)
01200C                   EVAL      SCSALD = CTSALD
01300C                   ELSE
01400C                   EVAL      SCMSG = 'CUENTA NO EXISTE'
01500C                   ENDIF
01600C                   ENDDO
01700C                   EVAL      *INLR = *ON
