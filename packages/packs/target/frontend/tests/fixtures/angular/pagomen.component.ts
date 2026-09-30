// Reference screen of SCR-PAGOMEN written by hand (ADR-0016).
import { Component, inject, signal } from '@angular/core'
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms'
import { NAVIGATE } from '../app/tokens'

@Component({
  selector: 'nx-pagomen',
  standalone: true,
  imports: [ReactiveFormsModule],
  template: `
    <div class="nx-root nx-screen">
      <header class="nx-screen__header"><h1 class="nx-screen__title">Banco Ficticio - Pagos</h1></header>
      <main class="nx-screen__body" aria-label="Banco Ficticio - Pagos">
        <form (submit)="submit($event)" novalidate>
          <p data-field="FECHA">30/09/2026</p>
          <div class="nx-field" data-field="OPCION">
            <label class="nx-field__label" for="opcion">Opcion</label>
            <input id="opcion" class="nx-input nx-input--numeric" [formControl]="option" maxlength="1" inputmode="numeric" required />
            @if (submitted && option.invalid) { <span class="nx-field__error" role="alert">Elija una opcion</span> }
          </div>
          <p data-field="MENSAJE" role="status">{{ message() }}</p>
          <button type="submit" class="nx-button nx-button--primary" data-action="ENTER">Continuar</button>
          <button type="button" class="nx-button nx-button--secondary" data-action="PF3" (click)="message.set('SESION TERMINADA')">Salir</button>
        </form>
      </main>
    </div>
  `,
})
export class PagomenScreen {
  private readonly navigate = inject(NAVIGATE)
  protected readonly option = new FormControl('', { nonNullable: true, validators: [Validators.required] })
  protected readonly message = signal('')
  protected submitted = false

  protected submit(event: Event): void {
    event.preventDefault()
    this.submitted = true
    if (this.option.invalid) return
    if (this.option.value === '1') this.navigate('SCR-PAGOORD')
    else this.message.set('OPCION NO VALIDA')
  }
}
