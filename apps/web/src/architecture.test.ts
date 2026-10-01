import { describe, expect, it } from 'vitest'

// Plan P2: no screen whose backend exists reads sample data. Only the screens of later milestones may still import
// '@/mocks/data': Administration's identity providers (M0b).
const ALLOWED = new Set(['./features/admin/AdminPage.tsx'])

// Every source file of the app as text (Vite reads them at build time of the test).
const sources = import.meta.glob<string>(['./**/*.{ts,tsx}', '!./mocks/**', '!./**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

describe('sample data', () => {
  it('is only imported by the screens of later milestones', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(50)
    const importers = Object.entries(sources)
      .filter(([, text]) => /from ['"]@\/mocks\/data['"]/.test(text))
      .map(([path]) => path)
    expect(importers.filter((path) => !ALLOWED.has(path))).toEqual([])
  })
})
