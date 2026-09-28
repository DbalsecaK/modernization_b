import { describe, expect, it } from 'vitest'
import { splitScenarios, validateCriteria, validateScenario } from './gherkin'

const codes = (text: string) => validateScenario(text).map((i) => i.code)

describe('acceptance criteria (Gherkin)', () => {
  it('accepts a complete scenario, with And/But, in English and in Spanish', () => {
    expect(codes('Scenario: Decline over the limit\n  Given a limit of 5,000.00\n  And a balance of 4,900.00\n  When a purchase of 150.00 is authorized\n  Then it is declined\n  But no hold is placed')).toEqual([])
    expect(codes('Escenario: Rechazo por límite\n  Dado un límite de 5.000,00\n  Cuando se autoriza una compra de 150,00\n  Entonces se rechaza con el código 51')).toEqual([])
  })

  it('reports missing parts', () => {
    expect(codes('Given a card\nThen it is rejected')).toEqual(['missingScenario'])
    expect(codes('Scenario:\n  Given a card\n  When activated\n  Then rejected')).toEqual(['emptyName'])
    expect(codes('Scenario: No when\n  Given a card\n  Then it is rejected')).toEqual(['missingWhen'])
    expect(codes('Scenario: Only then\n  Then it is rejected')).toEqual(['missingGiven', 'missingWhen'])
    expect(codes('Scenario: Empty\n  Given\n  When x\n  Then y')).toEqual(['emptyStep'])
  })

  it('reports steps out of order, a leading And and free text', () => {
    expect(validateScenario('Scenario: Two behaviors\n  Given a\n  When b\n  Then c\n  When d\n  Then e')).toEqual([expect.objectContaining({ code: 'outOfOrder', line: 5, detail: 'when', after: 'then' })])
    expect(codes('Scenario: And first\n  And a\n  Given b\n  When c\n  Then d')).toEqual(['continuationFirst'])
    expect(codes('Scenario: Prose\n  Given a\n  the user clicks\n  When b\n  Then c')).toEqual(['unknownLine'])
  })

  it('checks scenario outlines against their examples', () => {
    const ok = 'Scenario Outline: Limit\n  Given a balance of <balance>\n  When I buy <amount>\n  Then the result is <result>\n  Examples:\n    | balance | amount | result |\n    | 4900 | 150 | declined |'
    expect(codes(ok)).toEqual([])
    expect(codes(ok.replace('<result>', '<outcome>'))).toEqual(['unknownPlaceholder'])
    expect(codes('Scenario Outline: X\n  Given <a>\n  When b\n  Then c')).toEqual(['outlineWithoutExamples'])
    expect(codes('Scenario Outline: X\n  Given <a>\n  When b\n  Then c\n  Examples:\n    | a |')).toEqual(['emptyExamples'])
  })

  it('splits blocks and rejects duplicate scenario names', () => {
    const blocks = splitScenarios('Scenario: A\n Given a\n When b\n Then c\n\n\nScenario: a\n Given a\n When b\n Then c\n')
    expect(blocks).toHaveLength(2)
    expect(validateCriteria(blocks).map((i) => [i.scenario, i.code])).toEqual([[1, 'duplicateName']])
  })
})
