import { describe, expect, it } from 'vitest'
import { diffHunks, errorLines, firstErrorLine, groupEvidence, lineDiff } from './model'

describe('groupEvidence', () => {
  it('separates the diagnostic, the files with their version before, and the analysis', () => {
    const analysis = {
      cause: 'The helper lacks the field.',
      change: 'Every attempt rewrote the service.',
      options: [
        { key: 'retryWithInstruction', label: 'Fix the tests', instruction: 'Declare it', confidence: 0.8 },
        { key: 'stop', label: 'Stop', confidence: 1.7 },
        { label: 'no key' },
      ],
    }
    const grouped = groupEvidence([
      { kind: 'log', reference: 'diagnostic', excerpt: 'Test.java:12: error' },
      { kind: 'code', reference: 'src/Test.java#attempt-3', excerpt: 'class T {}' },
      { kind: 'code', reference: 'src/Test.java#before', excerpt: 'class T { int x; }' },
      { kind: 'code', reference: 'src/Svc.java#attempt-3', excerpt: 'class S {}' },
      { kind: 'analysis', reference: 'model', excerpt: JSON.stringify(analysis) },
      { kind: 'rule', reference: 'RULE-003' },
    ])
    expect(grouped.diagnostic).toBe('Test.java:12: error')
    expect(grouped.files).toEqual([
      { path: 'src/Test.java', attempt: '3', after: 'class T {}', before: 'class T { int x; }' },
      { path: 'src/Svc.java', attempt: '3', after: 'class S {}' },
    ])
    expect(grouped.analysis?.cause).toBe('The helper lacks the field.')
    expect(grouped.analysis?.options).toEqual([
      {
        key: 'retryWithInstruction',
        label: 'Fix the tests',
        rationale: undefined,
        instruction: 'Declare it',
        confidence: 0.8,
      },
      { key: 'stop', label: 'Stop', rationale: undefined, instruction: undefined, confidence: 1 },
    ])
    expect(grouped.other).toEqual([{ reference: 'RULE-003' }])
  })

  it('ignores an analysis that is not JSON', () => {
    expect(groupEvidence([{ kind: 'analysis', reference: 'model', excerpt: 'not json' }]).analysis).toBeUndefined()
  })
})

describe('lineDiff', () => {
  it('marks what the last attempt changed against the version before', () => {
    const diff = lineDiff('a\nb\nc', 'a\nx\nc\nd')
    expect(diff.map((l) => `${l.kind}:${l.text}`)).toEqual(['same:a', 'del:b', 'add:x', 'same:c', 'add:d'])
    expect(diff[1]).toEqual({ kind: 'del', text: 'b', before: 2 })
    expect(diff[2]).toEqual({ kind: 'add', text: 'x', after: 2 })
  })

  it('keeps only the changed lines with context in hunks', () => {
    const before = Array.from({ length: 20 }, (_, i) => `line ${i + 1}`).join('\n')
    const after = before.replace('line 10', 'line ten')
    const hunks = diffHunks(lineDiff(before, after), 2)
    expect(hunks).toHaveLength(1)
    expect(hunks[0].map((l) => l.text)).toEqual(['line 8', 'line 9', 'line 10', 'line ten', 'line 11', 'line 12'])
  })
})

describe('errorLines', () => {
  it('finds the lines the compiler names for the file', () => {
    const diagnostic =
      'src/test/java/com/bank/ProcessTest.java:1223: error: cannot find symbol\n' +
      'src/test/java/com/bank/ProcessTest.java:1240: error: cannot find symbol\nOther.java:5: warning'
    expect([...errorLines(diagnostic, 'src/test/java/com/bank/ProcessTest.java')]).toEqual([1223, 1240])
    expect(firstErrorLine(diagnostic, 'src/test/java/com/bank/ProcessTest.java')).toBe(1223)
    expect(firstErrorLine(diagnostic, 'src/main/Svc.java')).toBeUndefined()
  })
})
