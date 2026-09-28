import { agents, skills } from '@/mocks/data'
import type { Flow, TargetStack } from '@/mocks/types'

// Deterministic recommendation matrix (spec 9.4 and 9.7). No model is involved: the same inputs
// always give the same team, and every recommendation carries its reason.

export const SOURCE_OPTIONS = [
  'COBOL',
  'COBOL CICS',
  'BMS maps',
  'DB2',
  'Sybase ASE stored procedures',
  'ASP.NET WebForms',
  'C# .NET Framework 4.8',
] as const

export const INPUT_OPTIONS = [
  'User stories (Jira)',
  'Functional document (Word)',
  'User manual (PDF)',
  'Figma',
  'Screenshots',
] as const

export const TARGET_OPTIONS = {
  architecture: [
    'Microservices (hexagonal)',
    'Modular monolith (hexagonal)',
    'MVC',
    'Serverless',
    'Event-driven',
    'BFF + microservices',
  ],
  backend: ['Java Spring Boot', 'Java Quarkus', '.NET 10', 'Go', 'Next.js'],
  frontend: ['React', 'Angular', 'Next.js', '—'],
  database: ['PostgreSQL', 'MySQL', 'SQL Server', 'Oracle', 'MongoDB'],
  cloud: ['AWS', 'Azure', 'GCP', 'Kubernetes (on-prem)'],
} as const

export interface Recommendation {
  id: string
  reason: string // i18n key under wizard.reasons
}

export function recommendAgents(flow: Flow, sources: string[], target: TargetStack): Recommendation[] {
  const out: Recommendation[] = []
  const add = (id: string, reason: string) => {
    if (!out.some((r) => r.id === id)) out.push({ id, reason })
  }
  const hasUi = target.frontend !== '—'

  if (flow === 'modernization') {
    add('legacy-analyst', 'legacySource')
    add('rules-extractor', 'legacySource')
    add('data-analyst', 'legacySource')
    if (sources.some((s) => s === 'BMS maps' || s === 'ASP.NET WebForms')) add('ui-analyst', 'legacyScreens')
    add('data-migration', 'dataMigration')
  } else {
    add('functional-analyst', 'documents')
    if (sources.some((s) => s === 'Figma' || s === 'Screenshots')) add('ui-analyst', 'visualInputs')
  }
  add('solution-architect', 'always')
  add('data-architect', 'always')
  if (hasUi && !sources.includes('Figma')) add('ux-designer', 'noFigma')
  add('backend-dev', 'backend')
  if (hasUi) add('frontend-dev', 'frontend')
  add('devops', 'cloud')
  add('test-engineer', 'always')
  add('code-reviewer', 'always')
  add('security-auditor', 'always')
  add('rules-verifier', 'control')
  add(flow === 'modernization' ? 'equivalence-validator' : 'acceptance-judge', 'control')
  if (flow === 'modernization') add('acceptance-judge', 'control')
  return out
}

export function mandatoryAgentIds() {
  return agents.filter((a) => a.mandatory).map((a) => a.id)
}

function tagsFor(sources: string[], target: TargetStack) {
  return new Set<string>(['*', ...sources, target.backend, target.frontend, target.database, target.cloud])
}

export function recommendSkills(agentIds: string[], sources: string[], target: TargetStack) {
  const tags = tagsFor(sources, target)
  return skills
    .filter((s) => s.status === 'published')
    .filter((s) => s.appliesTo.some((a) => agentIds.includes(a)) && s.tags.some((tag) => tags.has(tag)))
    .map((s) => s.id)
}

export function skillConflicts(skillIds: string[]) {
  const pairs: [string, string][] = []
  for (const id of skillIds) {
    const skill = skills.find((s) => s.id === id)
    for (const other of skill?.conflictsWith ?? []) {
      if (skillIds.includes(other) && id < other) pairs.push([id, other])
    }
  }
  return pairs
}

export function missingSkills(sources: string[], skillIds: string[]) {
  const required: Record<string, string> = {
    'BMS maps': 'bms-parsing',
    'COBOL CICS': 'exec-cics',
    'Sybase ASE stored procedures': 'sybase-tsql',
    'ASP.NET WebForms': 'webforms',
  }
  return sources
    .filter((s) => required[s] && !skillIds.includes(required[s]))
    .map((s) => ({ source: s, skill: required[s] }))
}

// Phases that must have at least one responsible agent.
export function uncoveredPhases(flow: Flow, agentIds: string[]) {
  const needed =
    flow === 'modernization'
      ? ['inventory', 'ruleExtraction', 'design', 'generation', 'verification']
      : ['normalization', 'ui', 'design', 'generation', 'validation']
  const covered = new Set(agents.filter((a) => agentIds.includes(a.id)).flatMap((a) => a.phases))
  return needed.filter((p) => !covered.has(p))
}

// Compatibility matrix rules (spec 8.5). Each warning becomes an ADR when the project is created.
export function compatibilityWarnings(sources: string[], target: TargetStack): string[] {
  const out: string[] = []
  if (target.database === 'MongoDB') out.push('mongoModeling')
  if (target.architecture === 'Serverless' && sources.includes('COBOL')) out.push('serverlessBatch')
  if (target.architecture === 'Serverless' && sources.includes('COBOL CICS')) out.push('serverlessCics')
  if (target.backend === 'Next.js' && target.frontend !== 'Next.js') out.push('nextBff')
  if (target.backend === 'Go') out.push('goConventions')
  if (sources.includes('C# .NET Framework 4.8') && target.backend === '.NET 10') out.push('upliftOption')
  return out
}
