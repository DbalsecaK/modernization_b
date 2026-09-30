// Reference screen of SCR-PAGORES written by hand (ADR-0016).
import { Component, inject } from '@angular/core'
import { NAVIGATE } from '../app/tokens'

@Component({
  selector: 'nx-pagores',
  standalone: true,
  template: `
    <div class="nx-root nx-screen">
      <header class="nx-screen__header"><h1 class="nx-screen__title">Resultado del pago</h1></header>
      <main class="nx-screen__body" aria-label="Resultado del pago">
        <section class="nx-card" aria-label="Resultado">
          <dl>
            <dt>Orden</dt>
            <dd data-field="RORDEN">-</dd>
            <dt>Comision</dt>
            <dd data-field="RCOMIS">-</dd>
            <dt>Movimiento</dt>
            <dd data-field="RMOVIM">-</dd>
          </dl>
          <p data-field="RMENS" role="status">PAGO REALIZADO</p>
        </section>
        <button type="button" class="nx-button nx-button--primary" data-action="ENTER" (click)="navigate('SCR-PAGOORD')">Nuevo pago</button>
        <button type="button" class="nx-button nx-button--secondary" data-action="PF3" (click)="navigate('SCR-PAGOMEN')">Menu</button>
      </main>
    </div>
  `,
})
export class PagoresScreen {
  protected readonly navigate = inject(NAVIGATE)
}
