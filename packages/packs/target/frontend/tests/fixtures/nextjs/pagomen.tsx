'use client'
// Reference screen of SCR-PAGOMEN written by hand (ADR-0028): a Next.js client component, the same contract as React.
import { useState, type FormEvent } from 'react'
import { Button, Screen, TextField } from '@nexti/ds'
import type { ScreenProps } from '../types'

export default function PagomenScreen({ navigate }: ScreenProps) {
  const [option, setOption] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!option) return setError('Elija una opcion')
    setError('')
    if (option === '1') navigate('SCR-PAGOORD')
    else setMessage('OPCION NO VALIDA')
  }

  return (
    <Screen title="Banco Ficticio - Pagos" code="PAGOMEN">
      <form onSubmit={submit} noValidate>
        <p data-field="FECHA">{new Date(2026, 8, 30).toLocaleDateString('es')}</p>
        <TextField data-field="OPCION" label="Opcion" required numeric maxLength={1} value={option} onChange={(e) => setOption(e.target.value)} error={error} />
        <p data-field="MENSAJE" role="status">{message}</p>
        <Button type="submit" variant="primary" data-action="ENTER">Continuar</Button>
        <Button data-action="PF3" onClick={() => setMessage('SESION TERMINADA')}>Salir</Button>
      </form>
    </Screen>
  )
}
