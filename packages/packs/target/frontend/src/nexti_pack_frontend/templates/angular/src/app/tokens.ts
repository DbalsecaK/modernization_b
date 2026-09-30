import { InjectionToken } from '@angular/core'
import type { Api } from '../api/client'

/** The typed backend client. */
export const API = new InjectionToken<Api>('API')
/** Opens another screen by its id. */
export const NAVIGATE = new InjectionToken<(screen: string) => void>('NAVIGATE')
