import { describe, expect, it } from 'vitest'
import en from './locales/en.json'
import es from './locales/es.json'

// Spec 18.6: CI fails if a key exists in one catalog and not in the other.
function keys(node: unknown, prefix = ''): string[] {
  if (node === null || typeof node !== 'object') return [prefix]
  return Object.entries(node as Record<string, unknown>).flatMap(([k, v]) => keys(v, prefix ? `${prefix}.${k}` : k))
}

function placeholders(node: unknown, prefix = '', out: Record<string, string[]> = {}) {
  if (typeof node === 'string') out[prefix] = [...node.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort()
  else if (node && typeof node === 'object')
    Object.entries(node as Record<string, unknown>).forEach(([k, v]) => placeholders(v, prefix ? `${prefix}.${k}` : k, out))
  return out
}

describe('translation catalogs', () => {
  it('English and Spanish have exactly the same keys', () => {
    const enKeys = keys(en).sort()
    const esKeys = keys(es).sort()
    expect(esKeys.filter((k) => !enKeys.includes(k))).toEqual([])
    expect(enKeys.filter((k) => !esKeys.includes(k))).toEqual([])
  })

  it('every translation keeps the same interpolation placeholders', () => {
    const enP = placeholders(en)
    const esP = placeholders(es)
    const mismatched = Object.keys(enP).filter((k) => JSON.stringify(enP[k]) !== JSON.stringify(esP[k]))
    expect(mismatched).toEqual([])
  })

  it('no Spanish value is left identical to English by mistake in long sentences', () => {
    const enFlat = placeholders(en)
    const same = Object.keys(enFlat).filter((k) => {
      const a = k.split('.').reduce<any>((n, p) => n?.[p], en)
      const b = k.split('.').reduce<any>((n, p) => n?.[p], es)
      return typeof a === 'string' && a.split(' ').length > 4 && a === b
    })
    expect(same).toEqual([])
  })
})
