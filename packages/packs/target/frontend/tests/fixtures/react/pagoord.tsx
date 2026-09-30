// Reference page of SCR-PAGOORD written by hand (ADR-0016): the contract a generated page must meet.
import { useState, type FormEvent } from 'react'
import { Alert, Button, Card, Grid, Screen, TextField } from '@nexti/ds'
import { ApiError } from '../api/client'
import type { ScreenProps } from './types'

const REQUIRED = ['ORDEN', 'EMPRESA'] as const

export default function PagoordScreen({ api, navigate }: ScreenProps) {
  const [values, setValues] = useState<Record<string, string>>({ CANAL: 'WEB' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState('')
  const set = (name: string) => (event: { target: { value: string } }) =>
    setValues((v) => ({ ...v, [name]: event.target.value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    const missing = Object.fromEntries(
      REQUIRED.filter((name) => !values[name]).map((name) => [name, `${name} es obligatorio`]),
    )
    setErrors(missing)
    if (Object.keys(missing).length) return
    try {
      await api.payOrder({
        orderNumber: Number(values.ORDEN),
        company: Number(values.EMPRESA),
        service: values.SERVIC ?? '',
        accountType: values.TIPCTA ?? '',
        account: values.CUENTA ?? '',
        amount: Number(values.VALOR ?? 0) / 100,
        channel: values.CANAL ?? 'WEB',
        processingDate: new Date().toISOString(),
      })
      navigate('SCR-PAGORES')
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : 'No se pudo procesar el pago')
    }
  }

  return (
    <Screen title="Pago de ordenes" code="PAGOORD">
      <form onSubmit={submit} noValidate>
        <Card title="Datos de la orden">
          <Grid>
            <TextField data-field="ORDEN" label="Numero de orden" required numeric maxLength={7} value={values.ORDEN ?? ''} onChange={set('ORDEN')} error={errors.ORDEN} />
            <TextField data-field="EMPRESA" label="Empresa" required numeric maxLength={5} value={values.EMPRESA ?? ''} onChange={set('EMPRESA')} error={errors.EMPRESA} />
            <TextField data-field="SERVIC" label="Servicio" maxLength={10} value={values.SERVIC ?? ''} onChange={set('SERVIC')} />
            <TextField data-field="TIPCTA" label="Tipo de cuenta" maxLength={3} value={values.TIPCTA ?? ''} onChange={set('TIPCTA')} />
            <TextField data-field="CUENTA" label="Cuenta" numeric maxLength={10} value={values.CUENTA ?? ''} onChange={set('CUENTA')} />
            <TextField data-field="VALOR" label="Valor" numeric maxLength={11} value={values.VALOR ?? ''} onChange={set('VALOR')} />
            <TextField data-field="CANAL" label="Canal" maxLength={3} value={values.CANAL ?? ''} onChange={set('CANAL')} />
            <TextField data-field="CLAVE" label="Clave de aprobacion" type="password" maxLength={6} value={values.CLAVE ?? ''} onChange={set('CLAVE')} />
          </Grid>
        </Card>
        <div data-field="MENSAJE" aria-live="polite">
          {message && <Alert tone="error">{message}</Alert>}
        </div>
        <Button type="submit" variant="primary" data-action="ENTER">Pagar</Button>
        <Button data-action="PF3" onClick={() => navigate('SCR-PAGOMEN')}>Volver</Button>
        <Button data-action="PF12" onClick={() => setValues({ CANAL: 'WEB' })}>Cancelar</Button>
      </form>
    </Screen>
  )
}
