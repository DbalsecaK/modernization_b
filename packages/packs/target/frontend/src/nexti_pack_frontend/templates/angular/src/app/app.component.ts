import { Component, signal } from '@angular/core'
import { NgComponentOutlet } from '@angular/common'
import { SCREENS, START } from '../screens'

/** The current screen of the shell; NAVIGATE changes it. */
export const current = signal(START)

@Component({
  selector: 'nx-app',
  standalone: true,
  imports: [NgComponentOutlet],
  template: `<ng-container *ngComponentOutlet="screen()" />`,
})
export class AppComponent {
  readonly screen = () => SCREENS[current()] ?? null
}
