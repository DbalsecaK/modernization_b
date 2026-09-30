import type { GherkinProblem, PlanProblem, RuleOut, StoryOut } from '@/api/spec'

// View models of the specification tab, mapped from the API's wire shapes. Pure functions (unit tested): no check
// here decides anything; validation, coverage and the plan's dependency check are the server's.

export type Priority = 'P0' | 'P1' | 'P2'
export type Confidence = 'high' | 'medium' | 'low'
export type Tone = 'good' | 'info' | 'warning' | 'neutral' | 'critical'

export interface SourceRef {
  file: string
  lineStart: number
  lineEnd: number
}

export interface DataItem {
  name: string
  type: string
  description: string
}

export interface RuleView {
  key: string
  version: number
  status: string
  origin: string
  createdAt: string
  name: string
  domain: string
  category: string
  priority: Priority | string
  statement: string
  condition: string
  action: string
  inputs: DataItem[]
  outputs: DataItem[]
  scenarios: string[]
  hardcoded: string[]
  suspectedDefect: string | null
  confidence: Confidence | string
  smeQuestion: string | null
  sources: SourceRef[]
}

const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback)
const strOrNull = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const record = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' ? (v as Record<string, unknown>) : {}

/** The rule card stored in `data` (snake_case, as the worker saved it), read defensively. */
export function toRuleView(rule: RuleOut): RuleView {
  const d = record(rule.data)
  const items = (v: unknown): DataItem[] =>
    list(v).map((x) => {
      const r = record(x)
      return { name: str(r.name), type: str(r.type), description: str(r.description) }
    })
  return {
    key: rule.key,
    version: rule.version,
    status: rule.status,
    origin: rule.origin,
    createdAt: rule.createdAt,
    name: str(d.name, rule.key),
    domain: str(d.domain),
    category: str(d.category),
    priority: str(d.priority, 'P1'),
    statement: str(d.statement),
    condition: str(d.condition),
    action: str(d.action),
    inputs: items(d.inputs),
    outputs: items(d.outputs),
    scenarios: list(d.scenarios).filter((s): s is string => typeof s === 'string'),
    hardcoded: list(d.hardcoded).filter((s): s is string => typeof s === 'string'),
    suspectedDefect: strOrNull(d.suspected_defect),
    confidence: str(d.confidence, 'medium'),
    smeQuestion: strOrNull(d.sme_question),
    sources: list(d.sources).map((x) => {
      const r = record(x)
      const lineStart = Number(r.line_start) || 0
      return { file: str(r.file), lineStart, lineEnd: Number(r.line_end) || lineStart }
    }),
  }
}

/** `file:12` or `file:12-18`. */
export function citation(ref: SourceRef): string {
  return ref.lineEnd > ref.lineStart ? `${ref.file}:${ref.lineStart}-${ref.lineEnd}` : `${ref.file}:${ref.lineStart}`
}

export const priorityTone = (p: string): Tone => (p === 'P0' ? 'critical' : p === 'P1' ? 'warning' : 'neutral')

export const ruleStatusTone = (status: string): Tone =>
  status === 'approved'
    ? 'good'
    : status === 'review'
      ? 'info'
      : status === 'reopened'
        ? 'warning'
        : status === 'obsolete'
          ? 'critical'
          : 'neutral'

// Stories
export const ACTIVE_STORY_STATUSES = ['draft', 'review', 'question', 'approved'] as const

export const isActive = (s: Pick<StoryOut, 'status'>) => (ACTIVE_STORY_STATUSES as readonly string[]).includes(s.status)

export const storyStatusTone = (status: string): Tone =>
  status === 'approved'
    ? 'good'
    : status === 'review'
      ? 'info'
      : status === 'question'
        ? 'warning'
        : status === 'discarded'
          ? 'critical'
          : 'neutral'

export interface Dependency {
  on: string
  strength: 'hard' | 'soft'
  reason: string
  origin: string
}

export function dependenciesOf(story: Pick<StoryOut, 'dependsOn'>): Dependency[] {
  return story.dependsOn.map((raw) => {
    const d = record(raw)
    return {
      on: str(d.on),
      strength: d.strength === 'hard' ? 'hard' : 'soft',
      reason: str(d.reason),
      origin: str(d.origin, 'graph'),
    }
  })
}

/** Stories grouped by feature, in the order the features first appear (stories without one go last). */
export function groupByFeature<T extends Pick<StoryOut, 'feature'>>(stories: T[]): { feature: string; items: T[] }[] {
  const groups = new Map<string, T[]>()
  for (const s of stories) groups.set(s.feature, [...(groups.get(s.feature) ?? []), s])
  return [...groups.entries()]
    .sort(([a], [b]) => (a === '' ? 1 : 0) - (b === '' ? 1 : 0))
    .map(([feature, items]) => ({ feature, items }))
}

/** Links of the story that no other active story covers (discarding it would leave them as a coverage gap). */
export function orphanLinks(story: StoryOut, stories: StoryOut[]): string[] {
  const others = stories.filter((s) => s.key !== story.key && isActive(s))
  return story.links.filter((l) => !others.some((s) => s.links.includes(l)))
}

/** Active stories that depend on `key`. */
export function dependentsOf(key: string, stories: StoryOut[]): string[] {
  return stories.filter((s) => isActive(s) && dependenciesOf(s).some((d) => d.on === key)).map((s) => s.key)
}

// The API's snake_case problem codes (Gherkin, plan) as i18n keys (camelCase avoids i18next's plural suffixes).
export const camelKey = (code: string) => code.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())

export function problemsByCriterion(problems: GherkinProblem[]): Map<number, GherkinProblem[]> {
  const byIndex = new Map<number, GherkinProblem[]>()
  for (const p of problems) byIndex.set(p.criterion, [...(byIndex.get(p.criterion) ?? []), p])
  return byIndex
}

/** Problems of a rejected save (422 `invalid_gherkin` / `invalid_plan`), kept only when they have the right shape. */
export function gherkinProblemsOf(raw: unknown[]): GherkinProblem[] {
  return raw.filter(
    (p): p is GherkinProblem =>
      !!p && typeof p === 'object' && typeof (p as GherkinProblem).criterion === 'number' && 'code' in p,
  )
}

export function planProblemsOf(raw: unknown[]): PlanProblem[] {
  return raw.filter(
    (p): p is PlanProblem =>
      !!p && typeof p === 'object' && typeof (p as PlanProblem).story === 'string' && 'code' in p,
  )
}

// Plan
export type Waves = string[][]

/** Wave index (0-based) of a story, or -1 when it is not planned. */
export const waveIndex = (waves: Waves, key: string) => waves.findIndex((w) => w.includes(key))

/**
 * The waves after moving `key` to wave `toWave` (at `index` inside it, or at the end). `toWave` may be one past the
 * last wave, creating it; waves left empty are dropped. The server validates the result.
 */
export function moveInWaves(waves: Waves, key: string, toWave: number, index?: number): Waves {
  const next = waves.map((w) => w.filter((k) => k !== key))
  while (next.length <= toWave) next.push([])
  const target = next[toWave]
  const at = index === undefined ? target.length : Math.max(0, Math.min(index, target.length))
  target.splice(at, 0, key)
  return next.filter((w) => w.length > 0)
}

/** Whether two plans are the same (same waves, same order). */
export const sameWaves = (a: Waves, b: Waves) => JSON.stringify(a) === JSON.stringify(b)

/** Warnings present after a save that were not there before (to tell the person their move added one). */
export function newProblems(before: PlanProblem[], after: PlanProblem[]): PlanProblem[] {
  const id = (p: PlanProblem) => `${p.code}:${p.story}:${p.on ?? ''}`
  const seen = new Set(before.map(id))
  return after.filter((p) => !seen.has(id(p)))
}
