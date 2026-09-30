/**
 * The NexTI base design system tokens (spec 7.4): the starting point when the customer gives no brand. The same values
 * are written as CSS variables in `ds.css`. `tokens.json` (also read by the backend) is what a project stores as its
 * design system version and what a customer brand overrides.
 */
import base from './tokens.json'

export type Tokens = {
  color: Record<string, string>
  font: { family: string; mono: string; size: Record<string, string>; weight: Record<string, number> }
  space: Record<string, string>
  radius: Record<string, string>
  shadow: Record<string, string>
}

export const NEXTI_BASE: Tokens = base

/** The tokens as CSS custom properties (`--nx-color-primary`...), e.g. to apply a customer brand at runtime. */
export function cssVariables(tokens: Tokens): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(tokens.color)) out[`--nx-color-${kebab(key)}`] = value
  for (const [key, value] of Object.entries(tokens.space)) out[`--nx-space-${key}`] = value
  for (const [key, value] of Object.entries(tokens.radius)) out[`--nx-radius-${key}`] = value
  for (const [key, value] of Object.entries(tokens.font.size)) out[`--nx-font-${key}`] = value
  out['--nx-font-family'] = tokens.font.family
  out['--nx-font-mono'] = tokens.font.mono
  return out
}

function kebab(name: string): string {
  return name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)
}
