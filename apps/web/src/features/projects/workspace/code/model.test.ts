import { describe, expect, it } from 'vitest'
import type { CodeFileEntry } from '@/api/code'
import { buildTree, formatSize, generationInProgress, initialFile, splitDocs } from './model'

const file = (path: string): CodeFileEntry => ({ path, layer: 'domain', sizeBytes: 10, rules: [] })

describe('buildTree', () => {
  const rows = buildTree([
    file('src/main/java/demo/PayOrderService.java'),
    file('pom.xml'),
    file('src/main/java/demo/api/PayOrderController.java'),
    file('frontend/src/pages/PayOrder.tsx'),
    file('frontend/package.json'),
  ])

  it('puts folders before files and joins chains of single folders', () => {
    expect(rows.map((r) => [r.label, r.depth])).toEqual([
      ['frontend/', 0],
      ['src/pages/', 1],
      ['PayOrder.tsx', 2],
      ['package.json', 1],
      ['src/main/java/demo/', 0],
      ['api/', 1],
      ['PayOrderController.java', 2],
      ['PayOrderService.java', 1],
      ['pom.xml', 0],
    ])
  })

  it('keeps unique keys and the file on file rows only', () => {
    expect(new Set(rows.map((r) => r.key)).size).toBe(rows.length)
    expect(rows.filter((r) => r.file).map((r) => r.file!.path)).toContain('frontend/package.json')
    expect(rows.find((r) => r.label === 'frontend/')?.file).toBeUndefined()
  })

  it('opens the file asked for, else the first one', () => {
    expect(initialFile(rows, 'pom.xml')).toBe('pom.xml')
    expect(initialFile(rows, 'missing.txt')).toBe('frontend/src/pages/PayOrder.tsx')
    expect(initialFile([], undefined)).toBeNull()
  })
})

describe('formatSize', () => {
  it('uses bytes, kilobytes and megabytes', () => {
    expect([formatSize(512), formatSize(2048), formatSize(3 * 1024 * 1024)]).toEqual(['512 B', '2.0 KB', '3.0 MB'])
  })
})

describe('splitDocs and generationInProgress', () => {
  const entry = (path: string, layer: string) => ({ path, layer, sizeBytes: 1, rules: [] })

  it('keeps the documents of the generation apart from the code', () => {
    const { code, docs } = splitDocs([
      entry('src/main/java/App.java', 'domain'),
      entry('generation/findings.json', 'docs'),
      entry('docs/legacy-engine.md', 'docs'),
    ] as never)
    expect(code.map((f) => f.path)).toEqual(['src/main/java/App.java'])
    expect(docs.map((f) => f.path)).toEqual(['generation/findings.json', 'docs/legacy-engine.md'])
  })

  it('says a run is generating only while it is in the generation phase', () => {
    expect(generationInProgress([{ status: 'running', currentPhase: 'generation' }])).toBe(true)
    expect(generationInProgress([{ status: 'waiting', currentPhase: 'generation' }])).toBe(true)
    expect(generationInProgress([{ status: 'running', currentPhase: 'verification' }])).toBe(false)
    expect(generationInProgress([{ status: 'failed', currentPhase: 'generation' }])).toBe(false)
    expect(generationInProgress(undefined)).toBe(false)
  })
})
