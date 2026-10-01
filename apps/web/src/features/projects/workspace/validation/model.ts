import type { CheckOut, CodeExcerpt, TraceCase, TraceRule, VerdictOut } from '@/api/validation'
import type { Verdict } from '@/mocks/types'
import { camelKey, type Tone } from '../spec/model'

// View models of the validation and traceability tabs. Pure functions (unit tested): they only arrange what the
// server computed; no verdict, check or comparison is decided here.

/** The six checks of a verdict, in the order of spec 11.3. */
export const CHECK_KEYS = [
  'tests_ran',
  'rules_traced',
  'same_behaviour',
  'fresh_inputs',
  'canary',
  'source_intact',
] as const

/** The checks of a generated frontend's verdict (ADR-0016); its module is `frontend-<pack>`. */
export const FRONTEND_CHECK_KEYS = [
  'compiles',
  'screens_mount',
  'fields_covered',
  'validations',
  'actions',
  'accessibility',
] as const

/** The checks of a Flow 2 verdict (ADR-0018): the acceptance criteria are the oracle, there is no legacy. */
export const FEATURE_CHECK_KEYS = [
  'tests_ran',
  'criteria_covered',
  'contracts',
  'canary',
  'questions_closed',
  'traced_to_inputs',
] as const

export const isFrontendModule = (module: string) => module.startsWith('frontend-')

/** A Flow 2 verdict reports the checks only Flow 2 has. */
export const isFeatureVerdict = (checks: CheckOut[]) =>
  checks.some((c) => c.key === 'criteria_covered' || c.key === 'traced_to_inputs')

export type CheckStatus = CheckOut['status']

/** A check of the verdict; `missing` when the worker did not report it (it counts as not run). */
export interface CheckView extends CheckOut {
  missing: boolean
}

/** i18n key of a check title (camelCase avoids i18next's plural suffixes); the API's title is the fallback. */
export const checkTitleKey = (key: string) => `validation.checkTitles.${camelKey(key)}`

/** i18n key of a check status. */
export const checkStatusKey = (status: CheckStatus) => `validation.status.${camelKey(status)}`

export const checkTone = (status: CheckStatus): Tone =>
  status === 'passed' ? 'good' : status === 'failed' ? 'critical' : 'warning'

/**
 * The checks in the canonical order, the ones the worker did not report added as not checked (the verdict already
 * counts them as not run); unknown keys go last, as reported.
 */
export function allChecks(checks: CheckOut[], module = ''): CheckView[] {
  const keys: readonly string[] = isFrontendModule(module)
    ? FRONTEND_CHECK_KEYS
    : isFeatureVerdict(checks)
      ? FEATURE_CHECK_KEYS
      : CHECK_KEYS
  const byKey = new Map(checks.map((c) => [c.key, c]))
  const known = keys.map((key): CheckView =>
    byKey.has(key)
      ? { ...byKey.get(key)!, missing: false }
      : { key, title: key, status: 'not_checked', detail: '', missing: true },
  )
  const extra = checks.filter((c) => !keys.includes(c.key))
  return [...known, ...extra.map((c) => ({ ...c, missing: false }))]
}

/** The API's verdict ("PARTLY PROVEN") as the badge's value ("PARTLY_PROVEN"). */
export function toVerdict(value: string | null | undefined): Verdict {
  if (value === 'PROVEN') return 'PROVEN'
  if (value === 'PARTLY PROVEN') return 'PARTLY_PROVEN'
  if (value === 'NOT PROVEN') return 'NOT_PROVEN'
  return 'NOT_VERIFIED'
}

export interface ModuleVerdicts {
  module: string
  latest: VerdictOut
  history: VerdictOut[]
}

/** Verdicts by module, newest first inside each and modules by their newest verdict (the API sends newest first). */
export function byModule(verdicts: VerdictOut[]): ModuleVerdicts[] {
  const sorted = [...verdicts].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
  const groups = new Map<string, VerdictOut[]>()
  for (const v of sorted) groups.set(v.module, [...(groups.get(v.module) ?? []), v])
  return [...groups.entries()].map(([module, [latest, ...history]]) => ({ module, latest, history }))
}

export const passedCount = (v: Pick<VerdictOut, 'checks'>) => v.checks.filter((c) => c.status === 'passed').length

// Traceability
export type TraceState = 'verified' | 'notVerified' | 'pending'

/** `verified` null means no verification has looked at the rule yet. */
export const traceState = (verified: boolean | null | undefined): TraceState =>
  verified === true ? 'verified' : verified === false ? 'notVerified' : 'pending'

export const traceTone = (state: TraceState): Tone =>
  state === 'verified' ? 'good' : state === 'notVerified' ? 'critical' : 'neutral'

export function filterRules(rules: TraceRule[], state: 'all' | TraceState, query: string): TraceRule[] {
  const q = query.trim().toLowerCase()
  return rules.filter(
    (r) =>
      (state === 'all' || traceState(r.verified) === state) &&
      (!q || `${r.key} ${r.name} ${r.sources.join(' ')} ${r.targetFiles.join(' ')}`.toLowerCase().includes(q)),
  )
}

export function stateCounts(rules: TraceRule[]): Record<TraceState, number> {
  const counts: Record<TraceState, number> = { verified: 0, notVerified: 0, pending: 0 }
  for (const r of rules) counts[traceState(r.verified)] += 1
  return counts
}

export interface ExcerptLine {
  number: number
  text: string
  highlighted: boolean
}

/** The excerpt's lines with their real line numbers in the file. */
export function excerptLines(excerpt: CodeExcerpt): ExcerptLine[] {
  const marked = new Set(excerpt.highlighted)
  return excerpt.lines.map((text, i) => {
    const number = excerpt.firstLine + i
    return { number, text, highlighted: marked.has(number) }
  })
}

/** `path:12-40` (or `path:12` for one line) of the lines shown. */
export function excerptRange(excerpt: CodeExcerpt): string {
  const last = excerpt.firstLine + Math.max(0, excerpt.lines.length - 1)
  return last > excerpt.firstLine
    ? `${excerpt.path}:${excerpt.firstLine}-${last}`
    : `${excerpt.path}:${excerpt.firstLine}`
}

export interface Difference {
  path: string
  expected: string | null
  actual: string | null
}

const text = (v: unknown): string | null =>
  v === null || v === undefined ? null : typeof v === 'string' ? v : JSON.stringify(v)

/** A case's differences (`expected` is the legacy value, `actual` the target's), read defensively. */
export function differencesOf(c: Pick<TraceCase, 'differences'>): Difference[] {
  return c.differences.map((d) => ({ path: text(d.path) ?? '', expected: text(d.expected), actual: text(d.actual) }))
}
