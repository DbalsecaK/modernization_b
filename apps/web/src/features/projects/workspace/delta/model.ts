import type { DeltaOut } from '@/api/delta'
import type { TargetField } from '../ivv/model'

// View models of the Delta tab (Flow 3, ADR-0026). Pure functions (unit tested): they only read defensively what the
// worker and the server wrote (the baseline and the design are free-form JSON in the API); the AS-IS inventory has
// the shape of the IV&V one and is read with `inventoryOf` of the IV&V model. Nothing is decided here.

export interface BaselineView {
  passed: string[]
  /** The tests that already failed before the delta: they do not count as a regression. */
  failed: string[]
}

export interface DeltaChange {
  name: string
  description: string
  stories: string[]
  /** `METHOD /path` of the new or extended endpoint, or null when the change has none. */
  endpoint: string | null
  request: TargetField[]
  response: TargetField[]
  reuses: string[]
  tables: string[]
  newTables: string[]
  files: string[]
}

export interface DeltaDecision {
  title: string
  decision: string
}

export interface DeltaDesignView {
  changes: DeltaChange[]
  decisions: DeltaDecision[]
}

type Json = Record<string, unknown>

const record = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {})
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const str = (v: unknown): string => (typeof v === 'string' ? v : typeof v === 'number' ? String(v) : '')
const strings = (v: unknown): string[] => list(v).map(str).filter(Boolean)

const fieldsOf = (v: unknown): TargetField[] =>
  list(v).map((f) => {
    const r = record(f)
    return { name: str(r.name), type: str(r.type) }
  })

/** The application's tests before the delta, passing and failing; null before the baseline ran. */
export function baselineOf(raw: DeltaOut['baseline']): BaselineView | null {
  if (!raw) return null
  return { passed: strings(raw.passed), failed: strings(raw.failed) }
}

/** `METHOD /path` of a change; just the path when the method is missing; null without a path. */
export function endpointOf(method: unknown, path: unknown): string | null {
  const p = str(path)
  if (!p) return null
  const m = str(method).toUpperCase()
  return m ? `${m} ${p}` : p
}

/** The changes of the delta design (with their stories, endpoint, reuses, tables and files) and its decisions. */
export function designOf(raw: DeltaOut['design']): DeltaDesignView | null {
  if (!raw) return null
  return {
    changes: list(raw.changes).map((c) => {
      const r = record(c)
      return {
        name: str(r.name),
        description: str(r.description),
        stories: strings(r.stories),
        endpoint: endpointOf(r.http_method, r.path),
        request: fieldsOf(r.request),
        response: fieldsOf(r.response),
        reuses: strings(r.reuses),
        tables: strings(r.tables),
        newTables: strings(r.new_tables),
        files: strings(r.files),
      }
    }),
    decisions: list(raw.decisions).map((d) => {
      const r = record(d)
      return { title: str(r.title), decision: str(r.decision) }
    }),
  }
}

/** Nothing produced yet: no inventory, baseline, design, files or report. */
export const isDeltaEmpty = (delta: DeltaOut) =>
  delta.inventory === null &&
  delta.baseline === null &&
  delta.design === null &&
  delta.added.length === 0 &&
  delta.changed.length === 0 &&
  delta.report === null
