import { describe, expect, it } from 'vitest'
import { NEXTI_BASE, cssVariables } from '@nexti/ds'

describe('NexTI base design system tokens', () => {
  it('become CSS custom properties with the same names as ds.css', () => {
    const variables = cssVariables(NEXTI_BASE)
    expect(variables['--nx-color-primary']).toBe('#052158')
    expect(variables['--nx-color-surface-muted']).toBe('#f1f3f6')
    expect(variables['--nx-space-md']).toBe('16px')
    expect(variables['--nx-font-family']).toContain('Inter')
  })

  it('a customer brand overrides only what it gives', () => {
    const brand = { ...NEXTI_BASE, color: { ...NEXTI_BASE.color, primary: '#7a0019' } }
    const variables = cssVariables(brand)
    expect(variables['--nx-color-primary']).toBe('#7a0019')
    expect(variables['--nx-color-accent']).toBe(NEXTI_BASE.color.accent)
  })
})
