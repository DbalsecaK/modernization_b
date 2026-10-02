import type { ComponentType } from 'react'
import type { ScreenProps } from './types'
{{IMPORTS}}

export { START } from './routes'

/** Every screen by its id: the harness mounts them one by one. */
export const SCREENS: Record<string, ComponentType<ScreenProps>> = {
{{REGISTRY}}
}
