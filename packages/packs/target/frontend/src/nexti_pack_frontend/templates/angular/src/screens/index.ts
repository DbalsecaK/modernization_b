import type { Type } from '@angular/core'
{{IMPORTS}}

export const START = '{{START}}'

export const SCREENS: Record<string, Type<unknown>> = {
{{REGISTRY}}
}
