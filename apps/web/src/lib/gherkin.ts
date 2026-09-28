// Deterministic check of the acceptance criteria of a user story (spec 7.7). Each criterion is one Gherkin
// scenario that must describe one behavior: Given → When → Then, with And/But continuing the previous step.
// English and Spanish keywords are accepted (artifact language, spec 18.6).

export type GherkinIssueCode =
  | 'missingScenario'
  | 'emptyName'
  | 'duplicateName'
  | 'missingGiven'
  | 'missingWhen'
  | 'missingThen'
  | 'outOfOrder'
  | 'continuationFirst'
  | 'emptyStep'
  | 'unknownLine'
  | 'outlineWithoutExamples'
  | 'examplesWithoutOutline'
  | 'unknownPlaceholder'
  | 'emptyExamples'

export interface GherkinIssue {
  scenario: number
  line: number
  code: GherkinIssueCode
  detail?: string
  // outOfOrder only: the step that came before.
  after?: string
}

type Step = 'given' | 'when' | 'then'

const SCENARIO = /^(Scenario Outline|Scenario Template|Esquema del escenario|Scenario|Escenario|Example|Ejemplo)\s*:\s*(.*)$/i
const OUTLINE = /^(Scenario Outline|Scenario Template|Esquema del escenario)$/i
const EXAMPLES = /^(Examples|Scenarios|Ejemplos)\s*:/i
const STEP: [RegExp, Step | 'and'][] = [
  [/^(Given|Dado|Dada|Dados|Dadas)(\s+|$)(.*)$/i, 'given'],
  [/^(When|Cuando)(\s+|$)(.*)$/i, 'when'],
  [/^(Then|Entonces)(\s+|$)(.*)$/i, 'then'],
  [/^(And|But|Y|E|Pero)(\s+|$)(.*)$/i, 'and'],
]
const order: Record<Step, number> = { given: 0, when: 1, then: 2 }

export function validateScenario(text: string, index = 0): GherkinIssue[] {
  const issues: GherkinIssue[] = []
  const add = (line: number, code: GherkinIssueCode, detail?: string, after?: string) => issues.push({ scenario: index, line, code, detail, after })
  const lines = text.split('\n').map((l) => l.trim())
  const first = lines.findIndex((l) => l && !l.startsWith('#') && !l.startsWith('@'))
  const header = first === -1 ? null : SCENARIO.exec(lines[first])
  if (!header) {
    add(first + 1, 'missingScenario')
    return issues
  }
  if (!header[2].trim()) add(first + 1, 'emptyName')
  const outline = OUTLINE.test(header[1])

  const seen = new Set<Step>()
  let last: Step | null = null
  let examplesAt = -1
  const placeholders: { name: string; line: number }[] = []
  const columns: string[] = []
  let rows = 0

  for (let i = first + 1; i < lines.length; i++) {
    const l = lines[i]
    if (!l || l.startsWith('#') || l.startsWith('@')) continue
    if (examplesAt !== -1) {
      if (l.startsWith('|')) {
        const cells = l.split('|').slice(1, -1).map((c) => c.trim())
        if (columns.length === 0) columns.push(...cells)
        else rows++
      } else add(i + 1, 'unknownLine', l)
      continue
    }
    if (EXAMPLES.test(l)) {
      if (!outline) add(i + 1, 'examplesWithoutOutline')
      examplesAt = i
      continue
    }
    if (l.startsWith('|') || l.startsWith('"""')) continue // data tables and doc strings belong to the previous step
    const match = STEP.map(([re, kind]) => [re.exec(l), kind] as const).find(([m]) => m)
    if (!match) {
      add(i + 1, 'unknownLine', l)
      continue
    }
    const [m, kind] = match
    if (!m![3].trim()) add(i + 1, 'emptyStep')
    for (const p of m![3].matchAll(/<([^>]+)>/g)) placeholders.push({ name: p[1], line: i + 1 })
    if (kind === 'and') {
      if (!last) add(i + 1, 'continuationFirst')
      continue
    }
    // Going back (a When or Given after a Then) means the scenario tests more than one behavior.
    if (last && order[kind] < order[last]) add(i + 1, 'outOfOrder', kind, last)
    seen.add(kind)
    last = kind
  }

  const end = lines.length
  if (!seen.has('given')) add(end, 'missingGiven')
  if (!seen.has('when')) add(end, 'missingWhen')
  if (!seen.has('then')) add(end, 'missingThen')
  if (outline) {
    if (examplesAt === -1) add(end, 'outlineWithoutExamples')
    else if (rows === 0) add(examplesAt + 1, 'emptyExamples')
    if (examplesAt !== -1) placeholders.filter((p) => !columns.includes(p.name)).forEach((p) => add(p.line, 'unknownPlaceholder', p.name))
  }
  return issues
}

export function scenarioName(text: string): string {
  const l = text.split('\n').map((x) => x.trim()).find((x) => SCENARIO.test(x))
  return l ? SCENARIO.exec(l)![2].trim() : ''
}

// All criteria of a story: each scenario on its own, plus no two scenarios with the same name.
export function validateCriteria(criteria: string[]): GherkinIssue[] {
  const issues = criteria.flatMap((c, i) => validateScenario(c, i))
  const names = criteria.map((c) => scenarioName(c).toLowerCase())
  names.forEach((n, i) => {
    if (n && names.slice(0, i).includes(n)) issues.push({ scenario: i, line: 1, code: 'duplicateName', detail: scenarioName(criteria[i]) })
  })
  return issues
}

// Splits the text of the story form into scenarios: one block per scenario, separated by a blank line.
export function splitScenarios(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((c) => c.replace(/\s+$/g, '').replace(/^\n+/, ''))
    .filter((c) => c.trim())
}
