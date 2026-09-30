// The platform's test entry (ADR-0016): mounts one screen with a recording api and navigation.
import '@angular/compiler'
import 'zone.js'
import { createComponent } from '@angular/core'
import { createApplication } from '@angular/platform-browser'
import type { Api } from './api/client'
import { API, NAVIGATE } from './app/tokens'
import { SCREENS } from './screens'

declare global {
  interface Window {
    __nexti: { mount(id: string, api: Api, navigate: (screen: string) => void): Promise<void> }
  }
}

window.__nexti = {
  async mount(id, api, navigate) {
    const screen = SCREENS[id]
    if (!screen) throw new Error(`no screen ${id}`)
    const app = await createApplication({
      providers: [{ provide: API, useValue: api }, { provide: NAVIGATE, useValue: navigate }],
    })
    const host = document.getElementById('root') as HTMLElement
    const ref = createComponent(screen, { environmentInjector: app.injector, hostElement: host })
    app.attachView(ref.hostView)
    ref.changeDetectorRef.detectChanges()
  },
}
