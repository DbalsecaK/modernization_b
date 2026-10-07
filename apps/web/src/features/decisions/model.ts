// What a decision card shows besides the question (ADR-0045): the diagnostic, the files of the last attempt with
// the version before them, and the analysis with its proposed answers. Pure functions, tested without the DOM.

export type EvidenceItem = { kind?: unknown; reference?: unknown; excerpt?: unknown }

export type AnalysisOption = {
  key: string
  label: string
  rationale?: string
  instruction?: string
  confidence?: number
}

export type Analysis = { cause?: string; change?: string; options: AnalysisOption[] }

export type FileEvidence = { path: string; attempt: string; after: string; before?: string }

export type GroupedEvidence = {
  diagnostic?: string
  files: FileEvidence[]
  analysis?: Analysis
  other: { reference: string }[]
}

const text = (value: unknown): string => (typeof value === 'string' ? value : '')

/** Groups the evidence list of a question by what the card renders. */
export function groupEvidence(evidence: EvidenceItem[]): GroupedEvidence {
  const grouped: GroupedEvidence = { files: [], other: [] }
  const after = new Map<string, FileEvidence>()
  const before = new Map<string, string>()
  for (const item of evidence) {
    const kind = text(item.kind)
    const reference = text(item.reference)
    const excerpt = text(item.excerpt)
    if (kind === 'log' && reference === 'diagnostic') {
      grouped.diagnostic = excerpt
    } else if (kind === 'code' && reference.includes('#')) {
      const at = reference.lastIndexOf('#')
      const path = reference.slice(0, at)
      const tag = reference.slice(at + 1)
      if (tag === 'before') before.set(path, excerpt)
      else after.set(path, { path, attempt: tag.replace(/^attempt-/, ''), after: excerpt })
    } else if (kind === 'analysis') {
      grouped.analysis = parseAnalysis(excerpt)
    } else if (reference) {
      grouped.other.push({ reference })
    }
  }
  for (const [path, file] of after) {
    grouped.files.push(before.has(path) ? { ...file, before: before.get(path) } : file)
  }
  return grouped
}

function parseAnalysis(json: string): Analysis | undefined {
  try {
    const data = JSON.parse(json) as { cause?: unknown; change?: unknown; options?: unknown }
    const options = Array.isArray(data.options)
      ? data.options
          .filter((o): o is Record<string, unknown> => !!o && typeof o === 'object')
          .map((o) => ({
            key: text(o.key),
            label: text(o.label) || text(o.key),
            rationale: text(o.rationale) || undefined,
            instruction: text(o.instruction) || undefined,
            confidence: typeof o.confidence === 'number' ? Math.min(1, Math.max(0, o.confidence)) : undefined,
          }))
          .filter((o) => o.key)
      : []
    return { cause: text(data.cause) || undefined, change: text(data.change) || undefined, options }
  } catch {
    return undefined
  }
}

export type DiffLine = { kind: 'same' | 'add' | 'del'; text: string; before?: number; after?: number }

/** A line diff (longest common subsequence): what the last attempt changed against the version before. */
export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split('\n')
  const b = after.split('\n')
  const n = a.length
  const m = b.length
  // lcs[i][j] = length of the LCS of a[i..] and b[j..]; one row at a time would lose the path, so keep it whole
  // (files of a few thousand lines are fine; the evidence is capped upstream).
  const lcs: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i], before: i + 1, after: j + 1 })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: 'del', text: a[i], before: i + 1 })
      i++
    } else {
      out.push({ kind: 'add', text: b[j], after: j + 1 })
      j++
    }
  }
  while (i < n) out.push({ kind: 'del', text: a[i], before: ++i })
  while (j < m) out.push({ kind: 'add', text: b[j], after: ++j })
  return out
}

/** The diff reduced to the changed lines with some context, as a reviewer reads it. */
export function diffHunks(lines: DiffLine[], context = 3): DiffLine[][] {
  const changed = lines.map((l) => l.kind !== 'same')
  const keep = lines.map((_, index) => {
    for (let k = Math.max(0, index - context); k <= Math.min(lines.length - 1, index + context); k++) {
      if (changed[k]) return true
    }
    return false
  })
  const hunks: DiffLine[][] = []
  let current: DiffLine[] = []
  keep.forEach((kept, index) => {
    if (kept) current.push(lines[index])
    else if (current.length) {
      hunks.push(current)
      current = []
    }
  })
  if (current.length) hunks.push(current)
  return hunks
}

/** The line numbers a diagnostic names for a file (`path/File.java:123:` or `File.java:123`). */
export function errorLines(diagnostic: string | undefined, path: string): Set<number> {
  const found = new Set<number>()
  if (!diagnostic) return found
  const name = path.split('/').pop() ?? path
  const pattern = new RegExp(`${name.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&')}:(\\d+)`, 'g')
  for (const match of diagnostic.matchAll(pattern)) found.add(Number(match[1]))
  return found
}

/** Where the diagnostic points inside a file: the first error line, to scroll to it. */
export function firstErrorLine(diagnostic: string | undefined, path: string): number | undefined {
  const lines = [...errorLines(diagnostic, path)]
  return lines.length ? Math.min(...lines) : undefined
}
