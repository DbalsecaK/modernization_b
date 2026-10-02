import type { IvvOut } from '@/api/ivv'

// View models of the IV&V tab (Flow 4, ADR-0025). Pure functions (unit tested): they only read defensively what the
// worker and the server wrote (the inventory and the comparison are free-form JSON in the API); no problem, gap or
// comparison is decided here.

export interface TargetField {
  name: string
  type: string
}

export interface TargetEndpoint {
  method: string
  path: string
  handler: string
  file: string
  line: number | null
  request: TargetField[]
  response: TargetField[]
}

export interface TargetTable {
  name: string
  columns: string[]
  key: string[]
}

export interface TargetInventoryView {
  stack: string
  mainClass: string | null
  artifact: string | null
  schema: string | null
  endpoints: TargetEndpoint[]
  tables: TargetTable[]
}

export interface RulePair {
  legacy: string
  name: string
  target: string | null
  similarity: number | null
}

export interface RuleComparison {
  present: RulePair[]
  missing: RulePair[]
  extra: string[]
}

type Json = Record<string, unknown>

const record = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {})
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : [])
const str = (v: unknown): string => (typeof v === 'string' ? v : typeof v === 'number' ? String(v) : '')
const optStr = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

const fieldsOf = (v: unknown): TargetField[] =>
  list(v).map((f) => {
    const r = record(f)
    return { name: str(r.name), type: str(r.type) }
  })

/** The target's inventory (stack, endpoints with their fields, tables); null before the target intake. */
export function inventoryOf(raw: IvvOut['inventory']): TargetInventoryView | null {
  if (!raw) return null
  return {
    stack: str(raw.stack) || 'unknown',
    mainClass: optStr(raw.main_class),
    artifact: optStr(raw.artifact),
    schema: optStr(raw.schema),
    endpoints: list(raw.endpoints).map((e) => {
      const r = record(e)
      return {
        method: str(r.method).toUpperCase(),
        path: str(r.path),
        handler: str(r.handler),
        file: str(r.file),
        line: num(r.line),
        request: fieldsOf(r.request),
        response: fieldsOf(r.response),
      }
    }),
    tables: list(raw.tables).map((t) => {
      const r = record(t)
      return { name: str(r.name), columns: list(r.columns).map(str), key: list(r.key).map(str) }
    }),
  }
}

const pairsOf = (v: unknown): RulePair[] =>
  list(v).map((p) => {
    const r = record(p)
    return { legacy: str(r.legacy), name: str(r.name), target: optStr(r.target), similarity: num(r.similarity) }
  })

/** The legacy rules found in the target, the ones not found and the target's rules the legacy did not have. */
export function comparisonOf(raw: IvvOut['comparison']): RuleComparison | null {
  if (!raw) return null
  return {
    present: pairsOf(raw.present),
    missing: pairsOf(raw.missing),
    extra: list(raw.extra)
      .map((e) => (typeof e === 'string' ? e : str(record(e).name)))
      .filter(Boolean),
  }
}

/** `name: type` of a field, or just its name. */
export const fieldLabel = (f: TargetField) => (f.type ? `${f.name}: ${f.type}` : f.name)

/** `file:line` of an endpoint's handler, or just the file. */
export const sourceLabel = (e: Pick<TargetEndpoint, 'file' | 'line'>) =>
  e.line !== null && e.file ? `${e.file}:${e.line}` : e.file

/** The similarity as a percentage (0.62 -> "62%"). */
export const similarityLabel = (similarity: number | null) =>
  similarity === null ? '' : `${Math.round(similarity * 100)}%`

export type MappingState = 'notTakenIn' | 'problems' | 'ready'

/** Whether the mapping can go to gate C2: no mapping before the intake, else ready when the server finds no problem. */
export const mappingState = (ivv: Pick<IvvOut, 'mapping' | 'problems'>): MappingState =>
  ivv.mapping === null ? 'notTakenIn' : ivv.problems.length > 0 ? 'problems' : 'ready'

/** The text in the editor differs from the saved mapping. */
export const isDirty = (draft: string, saved: string | null) => draft !== (saved ?? '')
