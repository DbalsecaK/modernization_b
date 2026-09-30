/*
 * Banco Ficticio S.A. - Reference application of the NexTI platform (fictitious, written for the repository).
 * Debits the account of a company for one payment order, charges the service commission and updates the order.
 * Nothing here comes from a real bank: names, tables and rules are invented to exercise the Sybase adapter.
 */
create procedure dbo.sp_pago_orden
(
    @i_orden            int,
    @i_empresa          int,
    @i_servicio         varchar(10),
    @i_tipo_cuenta      char(3),
    @i_cuenta           char(10),
    @i_valor            money,
    @i_canal            char(3)     = 'WEB',
    @i_fecha_proceso    datetime,
    @o_movimiento       int         = null output,
    @o_mensaje          varchar(120) = null output
)
as
declare @w_return       int,
        @w_error        int,
        @w_tarifa       money,
        @w_comision     money,
        @w_total        money,
        @w_saldo        money,
        @w_estado       char(1),
        @w_separada     char(1),
        @w_rowcount     int

select @w_return = 0,
       @o_mensaje = null

/* RF-01: only current, savings and virtual accounts can be debited */
if @i_tipo_cuenta not in ('CTE', 'AHO', 'VIR')
begin
    select @w_error = 50001,
           @o_mensaje = 'TIPO DE CUENTA NO PERMITIDO'
    goto ERROR
end

/* RF-02: the order must exist and be pending */
select @w_estado = ord_estado
  from db_pagos..pg_orden
 where ord_numero = @i_orden
   and ord_empresa = @i_empresa

if @@rowcount = 0
begin
    select @w_error = 50002,
           @o_mensaje = 'ORDEN NO EXISTE'
    goto ERROR
end

if @w_estado <> 'P'
begin
    select @w_error = 50003,
           @o_mensaje = 'ORDEN NO ESTA PENDIENTE'
    goto ERROR
end

/* RF-03: the tariff comes from the company table, else from the general service table */
select @w_tarifa = tar_valor,
       @w_separada = tar_separada
  from db_admin..ad_tarifa_empresa
 where tar_empresa = @i_empresa
   and tar_servicio = @i_servicio

if @@rowcount = 0
begin
    select @w_tarifa = srv_tarifa,
           @w_separada = 'N'
      from db_admin..ad_servicio
     where srv_codigo = @i_servicio
end

if @w_tarifa is null
    select @w_tarifa = 0

/* RF-04: web orders pay half the tariff; payroll never pays commission */
if @i_canal = 'WEB'
    select @w_comision = round(@w_tarifa / 2, 2)
else
    select @w_comision = @w_tarifa

if @i_servicio = 'NOMINA'
    select @w_comision = 0

/* RF-05: the total to debit includes the commission unless it is charged separately */
if @w_separada = 'S'
    select @w_total = @i_valor
else
    select @w_total = @i_valor + @w_comision

/* RF-06: virtual accounts cannot go below zero; other accounts may overdraw up to 100.00 */
select @w_saldo = cta_saldo
  from db_cuentas..ct_cuenta
 where cta_numero = @i_cuenta
   and cta_tipo = @i_tipo_cuenta

if (@i_tipo_cuenta = 'VIR' and @w_saldo < @w_total)
   or (@i_tipo_cuenta <> 'VIR' and @w_saldo + 100.00 < @w_total)
begin
    select @w_error = 50004,
           @o_mensaje = 'FONDOS INSUFICIENTES'
    goto ERROR
end

begin tran

exec @w_return = db_cuentas..sp_debito
     @i_cuenta     = @i_cuenta,
     @i_tipo       = @i_tipo_cuenta,
     @i_valor      = @w_total,
     @i_referencia = 'PAGO ORDEN',
     @o_secuencial = @o_movimiento output

if @w_return <> 0 or @@error <> 0
begin
    rollback tran
    select @w_error = 50005,
           @o_mensaje = 'ERROR EN DEBITO'
    goto ERROR
end

/* RF-07: a separate commission is a second movement */
if @w_separada = 'S' and @w_comision > 0
begin
    exec @w_return = db_cuentas..sp_debito
         @i_cuenta     = @i_cuenta,
         @i_tipo       = @i_tipo_cuenta,
         @i_valor      = @w_comision,
         @i_referencia = 'COMISION PAGO'

    if @w_return <> 0
    begin
        rollback tran
        select @w_error = 50006,
               @o_mensaje = 'ERROR EN COMISION'
        goto ERROR
    end
end

/* RF-08: the order is marked paid with the processing date and the commission charged */
update db_pagos..pg_orden
   set ord_estado = 'A',
       ord_fecha_pago = @i_fecha_proceso,
       ord_comision = @w_comision
 where ord_numero = @i_orden
   and ord_empresa = @i_empresa

select @w_error = @@error, @w_rowcount = @@rowcount

if @w_error <> 0 or @w_rowcount = 0
begin
    rollback tran
    select @w_error = 50007,
           @o_mensaje = 'ERROR ACTUALIZANDO ORDEN'
    goto ERROR
end

commit tran

select @o_mensaje = 'PAGO REALIZADO'
return 0

ERROR:
exec cobis..sp_cerror
     @t_from = 'sp_pago_orden',
     @i_num  = @w_error,
     @i_msg  = @o_mensaje
return @w_error
go
