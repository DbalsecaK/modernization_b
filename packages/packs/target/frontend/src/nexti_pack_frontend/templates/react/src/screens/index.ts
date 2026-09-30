import type { ComponentType } from 'react'
import type { ScreenProps } from './types'
{{IMPORTS}}

export const START = '{{START}}'

export const SCREENS: Record<string, ComponentType<ScreenProps>> = {
{{REGISTRY}}
}
