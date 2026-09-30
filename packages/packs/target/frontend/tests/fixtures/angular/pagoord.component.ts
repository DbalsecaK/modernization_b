// Reference screen of SCR-PAGOORD written by hand (ADR-0016): the contract a generated component must meet.
import { Component, inject, signal } from '@angular/core'
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms'
import { ApiError } from '../api/client'
import { API, NAVIGATE } from '../app/tokens'

@Component({
  selector: 'nx-pagoord',
  standalone: true,
  imports: [ReactiveFormsModule],
  template: `
    <div class="nx-root nx-screen">
      <header class="nx-screen__header">
        <h1 class="nx-screen__title">Pago de ordenes</h1>
        <span class="nx-screen__code">PAGOORD</span>
      </header>
      <main class="nx-screen__body" aria-label="Pago de ordenes">
        <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
          <div class="nx-field" data-field="ORDEN">
            <label class="nx-field__label" for="orden">Numero de orden <span class="nx-field__required" aria-hidden="true">*</span></label>
            <input id="orden" class="nx-input nx-input--numeric" formControlName="ORDEN" maxlength="7" inputmode="numeric" required />
            @if (missing('ORDEN')) { <span class="nx-field__error" role="alert">El numero de orden es obligatorio</span> }
          </div>
          <div class="nx-field" data-field="EMPRESA">
            <label class="nx-field__label" for="empresa">Empresa <span class="nx-field__required" aria-hidden="true">*</span></label>
            <input id="empresa" class="nx-input nx-input--numeric" formControlName="EMPRESA" maxlength="5" inputmode="numeric" required />
            @if (missing('EMPRESA')) { <span class="nx-field__error" role="alert">La empresa es obligatoria</span> }
          </div>
          <div class="nx-field" data-field="SERVIC">
            <label class="nx-field__label" for="servic">Servicio</label>
            <input id="servic" class="nx-input" formControlName="SERVIC" maxlength="10" />
          </div>
          <div class="nx-field" data-field="TIPCTA">
            <label class="nx-field__label" for="tipcta">Tipo de cuenta</label>
            <input id="tipcta" class="nx-input" formControlName="TIPCTA" maxlength="3" />
          </div>
          <div class="nx-field" data-field="CUENTA">
            <label class="nx-field__label" for="cuenta">Cuenta</label>
            <input id="cuenta" class="nx-input nx-input--numeric" formControlName="CUENTA" maxlength="10" inputmode="numeric" />
          </div>
          <div class="nx-field" data-field="VALOR">
            <label class="nx-field__label" for="valor">Valor</label>
            <input id="valor" class="nx-input nx-input--numeric" formControlName="VALOR" maxlength="11" inputmode="numeric" />
          </div>
          <div class="nx-field" data-field="CANAL">
            <label class="nx-field__label" for="canal">Canal</label>
            <input id="canal" class="nx-input" formControlName="CANAL" maxlength="3" />
          </div>
          <div class="nx-field" data-field="CLAVE">
            <label class="nx-field__label" for="clave">Clave de aprobacion</label>
            <input id="clave" class="nx-input" type="password" formControlName="CLAVE" maxlength="6" />
          </div>
          <div data-field="MENSAJE" aria-live="polite">
            @if (message()) { <div class="nx-alert nx-alert--error" role="alert">{{ message() }}</div> }
          </div>
          <button type="submit" class="nx-button nx-button--primary" data-action="ENTER">Pagar</button>
          <button type="button" class="nx-button nx-button--secondary" data-action="PF3" (click)="navigate('SCR-PAGOMEN')">Volver</button>
          <button type="button" class="nx-button nx-button--secondary" data-action="PF12" (click)="form.reset()">Cancelar</button>
        </form>
      </main>
    </div>
  `,
})
export class PagoordScreen {
  private readonly api = inject(API)
  protected readonly navigate = inject(NAVIGATE)
  protected readonly message = signal('')
  protected submitted = false
  protected readonly form = new FormGroup({
    ORDEN: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    EMPRESA: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    SERVIC: new FormControl('', { nonNullable: true }),
    TIPCTA: new FormControl('', { nonNullable: true }),
    CUENTA: new FormControl('', { nonNullable: true }),
    VALOR: new FormControl('', { nonNullable: true }),
    CANAL: new FormControl('WEB', { nonNullable: true }),
    CLAVE: new FormControl('', { nonNullable: true }),
  })

  protected missing(name: 'ORDEN' | 'EMPRESA'): boolean {
    return this.submitted && this.form.controls[name].invalid
  }

  protected async submit(): Promise<void> {
    this.submitted = true
    if (this.form.invalid) return
    const v = this.form.getRawValue()
    try {
      await this.api.payOrder({
        orderNumber: Number(v.ORDEN),
        company: Number(v.EMPRESA),
        service: v.SERVIC,
        accountType: v.TIPCTA,
        account: v.CUENTA,
        amount: Number(v.VALOR || 0) / 100,
        channel: v.CANAL,
        processingDate: new Date().toISOString(),
      })
      this.navigate('SCR-PAGORES')
    } catch (error) {
      this.message.set(error instanceof ApiError ? error.message : 'No se pudo procesar el pago')
    }
  }
}
