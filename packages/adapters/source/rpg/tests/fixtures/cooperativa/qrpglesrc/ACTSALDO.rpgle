00100HDFTACTGRP(*NO) ACTGRP(*CALLER)
00200FCUENTAS   UF   E           K DISK
00300FMOVIMI    O    E           K DISK
00400DACTSALDO         PI
00500DPCUENTA                        10A
00600DPMONTO                         11P 2
00700DPTIPO                           1A
00800DPRESULT                         3S 0
00900DWNUEVO           S             11P 2
01000DWCOMIS           C                   CONST(1.50)
01100C* Aplica un debito o credito al saldo de la cuenta (ficticio)
01200C     PCUENTA       CHAIN     CUENTAS
01300C                   IF        NOT %FOUND(CUENTAS)
01400C                   EVAL      PRESULT = 10
01500C                   RETURN
01600C                   ENDIF
01700C/FREE
01800  if PTIPO = 'D';
01900    if CTSALD < PMONTO + WCOMIS;
02000      PRESULT = 20;
02100      return;
02200    endif;
02300    WNUEVO = CTSALD - PMONTO - WCOMIS;
02400  else;
02500    WNUEVO = CTSALD + PMONTO;
02600  endif;
02700  exsr GRABAR;
02800  PRESULT = 0;
02900C/END-FREE
03000C     GRABAR        BEGSR
03100C                   EVAL      CTSALD = WNUEVO
03200C                   UPDATE    RCUENTA
03300C                   EVAL      MVCTA = PCUENTA
03400C                   EVAL(H)   MVMONT = PMONTO
03500C                   WRITE     RMOVIM
03600C                   ENDSR
