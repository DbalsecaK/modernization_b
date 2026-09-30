import '@angular/compiler'
import 'zone.js'
import { bootstrapApplication } from '@angular/platform-browser'
import { createApi } from './api/client'
import { AppComponent, current } from './app/app.component'
import { API, NAVIGATE } from './app/tokens'

bootstrapApplication(AppComponent, {
  providers: [
    { provide: API, useValue: createApi() },
    { provide: NAVIGATE, useValue: (screen: string) => current.set(screen) },
  ],
}).catch((error: unknown) => console.error(error))
