**FREE
ctl-opt nomain;

dcl-pr ValidarCuenta int(10) end-pr;

dcl-ds Cuenta qualified;
  numero char(10);
  saldo packed(11:2);
end-ds;

// Valida que una cuenta exista y este activa (ficticio)
dcl-proc ValidarCuenta export;
  dcl-pi *n int(10);
    pCuenta char(10) const;
  end-pi;
  dcl-s wEstado char(1);

  exec sql
    select CTESTA into :wEstado
      from COOPLIB.CUENTAS
     where CTNUME = :pCuenta;
  if sqlcode = 100;
    return 10;
  endif;
  if wEstado <> 'A';
    return 30;
  endif;
  exec sql insert into COOPLIB.AUDITA (AUCTA, AUFEC) values (:pCuenta, current date);
  return 0;
end-proc;
