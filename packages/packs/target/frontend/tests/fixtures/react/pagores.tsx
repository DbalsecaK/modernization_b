// Reference page of SCR-PAGORES written by hand (ADR-0016).
import { Button, Card, Screen } from '@nexti/ds'
import type { ScreenProps } from './types'

export default function PagoresScreen({ navigate }: ScreenProps) {
  return (
    <Screen title="Resultado del pago" code="PAGORES">
      <Card title="Resultado">
        <dl>
          <dt>Orden</dt>
          <dd data-field="RORDEN">-</dd>
          <dt>Comision</dt>
          <dd data-field="RCOMIS">-</dd>
          <dt>Movimiento</dt>
          <dd data-field="RMOVIM">-</dd>
        </dl>
        <p data-field="RMENS" role="status">PAGO REALIZADO</p>
      </Card>
      <Button variant="primary" data-action="ENTER" onClick={() => navigate('SCR-PAGOORD')}>Nuevo pago</Button>
      <Button data-action="PF3" onClick={() => navigate('SCR-PAGOMEN')}>Menu</Button>
    </Screen>
  )
}
