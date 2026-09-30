import { describe, expect, it } from 'vitest'
import type { ScreenData } from '@/api/screens'
import { cellsOf, dataFields, frameEvent, swatches, terminalRows } from './model'

const screen: ScreenData = {
  id: 'SCR-PAGOORD',
  name: 'PAGOORD',
  rows: 3,
  columns: 20,
  fields: [
    { name: 'L1', kind: 'literal', position: { row: 1, column: 1 }, length: 5, initial: 'ORDEN' },
    { name: 'ORDEN', kind: 'input', position: { row: 1, column: 7 }, length: 7 },
    { name: 'VALOR', kind: 'output', position: { row: 2, column: 15 }, length: 9, initial: '12.50' },
  ],
}

describe('terminal screen', () => {
  it('draws each field after its attribute byte', () => {
    const rows = terminalRows(screen)
    expect(rows).toHaveLength(3)
    expect(rows[0].map((s) => s.text).join('')).toBe(' ORDEN _______      ')
    expect(rows[0].find((s) => s.field === 'ORDEN')).toEqual({ text: '_______', field: 'ORDEN', kind: 'input' })
  })

  it('cuts a field at the right edge and leaves empty rows blank', () => {
    const rows = terminalRows(screen)
    expect(rows[1].find((s) => s.field === 'VALOR')?.text).toBe('12.50')
    expect(rows[2]).toEqual([{ text: ' '.repeat(20) }])
    expect(rows.every((r) => r.map((s) => s.text).join('').length === 20)).toBe(true)
  })

  it('fills inputs and outputs to their length', () => {
    expect(cellsOf({ name: 'A', kind: 'input', length: 3, initial: 'X' })).toBe('X__')
    expect(cellsOf({ name: 'B', kind: 'output', length: 2 })).toBe('··')
    expect(cellsOf({ name: 'C', kind: 'literal', length: 2, initial: 'HOLA' })).toBe('HO')
    expect(dataFields(screen).map((f) => f.name)).toEqual(['ORDEN', 'VALOR'])
  })
})

describe('frame events', () => {
  it('accepts only the closed set the platform entry sends', () => {
    expect(frameEvent({ source: 'nexti-prototype', type: 'field', name: 'VALOR' })).toEqual({
      type: 'field',
      name: 'VALOR',
    })
    expect(frameEvent({ source: 'nexti-prototype', type: 'navigate', to: 'SCR-PAGOMEN' })?.type).toBe('navigate')
    expect(frameEvent({ source: 'other', type: 'ready' })).toBeNull()
    expect(frameEvent({ source: 'nexti-prototype', type: 'eval', code: 'x' })).toBeNull()
    expect(frameEvent({ source: 'nexti-prototype', type: 'field', name: 42 })).toBeNull()
    expect(frameEvent('ready')).toBeNull()
  })
})

describe('design system', () => {
  it('lists the color tokens', () => {
    expect(swatches({ color: { primary: '#052158', nested: {} }, space: {} })).toEqual([['primary', '#052158']])
    expect(swatches({})).toEqual([])
  })
})
