import type { ScreenData, ScreenField } from '@/api/screens'

// Pure helpers of the Diseño UI tab: the legacy terminal screen drawn from the screen spec (the same positions,
// lengths and attributes the parser read from the BMS map) and the fields of a spec a reviewer can comment on.

export type Segment = { text: string; field?: string; kind?: ScreenField['kind'] }

/** What a field shows on the terminal: a literal its text; an input its initial value or underscores; an output its
 * initial value or a placeholder of its length. Never longer than the field. */
export function cellsOf(field: ScreenField): string {
  const length = Math.max(field.length, 0)
  const initial = field.initial ?? ''
  if (field.kind === 'literal') return initial.slice(0, length || initial.length)
  const filler = field.kind === 'input' ? '_' : '·'
  return initial.slice(0, length).padEnd(length, filler)
}

/** The screen as rows of segments. A field's position is its attribute byte (BMS POS): its data starts one column
 * to the right. Fields without a position (screens not read from a terminal map) are not drawn. */
export function terminalRows(screen: ScreenData): Segment[][] {
  const rows = screen.rows ?? 24
  const columns = screen.columns ?? 80
  const grid: (Segment | null)[][] = Array.from({ length: rows }, () => Array<Segment | null>(columns).fill(null))
  for (const field of screen.fields) {
    const at = field.position
    if (!at || at.row < 1 || at.row > rows) continue
    const text = cellsOf(field)
    for (let i = 0; i < text.length; i++) {
      const column = at.column + i // 0-based index of the 1-based column after the attribute byte
      if (column >= columns) break
      grid[at.row - 1][column] = { text: text[i], field: field.name, kind: field.kind }
    }
  }
  return grid.map((cells) => {
    const segments: Segment[] = []
    for (const cell of cells) {
      const last = segments[segments.length - 1]
      const segment = cell ?? { text: ' ' }
      if (last && last.field === segment.field) last.text += segment.text
      else segments.push({ ...segment })
    }
    return segments
  })
}

/** The fields a prototype must show and a reviewer can comment on (literals are the legacy's labels). */
export function dataFields(screen: ScreenData): ScreenField[] {
  return screen.fields.filter((f) => f.kind !== 'literal')
}

/** A message from the prototype frame (ADR-0013): only the closed set the platform's entry sends. */
export type FrameEvent =
  | { type: 'ready' }
  | { type: 'field'; name: string }
  | { type: 'navigate'; to: string }
  | { type: 'error'; message: string }

export function frameEvent(data: unknown): FrameEvent | null {
  if (typeof data !== 'object' || data === null) return null
  const d = data as Record<string, unknown>
  if (d.source !== 'nexti-prototype') return null
  const text = (v: unknown) => (typeof v === 'string' ? v.slice(0, 500) : null)
  switch (d.type) {
    case 'ready':
      return { type: 'ready' }
    case 'field': {
      const name = text(d.name)
      return name ? { type: 'field', name } : null
    }
    case 'navigate': {
      const to = text(d.to)
      return to ? { type: 'navigate', to } : null
    }
    case 'error':
      return { type: 'error', message: text(d.message) ?? '' }
    default:
      return null
  }
}

/** The colors of a design system's tokens, for the swatches. */
export function swatches(tokens: Record<string, unknown>): [string, string][] {
  const color = tokens.color
  if (typeof color !== 'object' || color === null) return []
  return Object.entries(color as Record<string, unknown>).filter(
    (entry): entry is [string, string] => typeof entry[1] === 'string',
  )
}
