// Domain types shared by the prototype. They mirror the entities in docs/ESPECIFICACION_PLATAFORMA.md
// (section 19.4) so the mocks can later be replaced by API responses with the same shape.

export type Flow = 'modernization' | 'newFeature' | 'independentValidation'

export type Verdict = 'PROVEN' | 'PARTLY_PROVEN' | 'NOT_PROVEN' | 'NOT_VERIFIED'

export type PhaseStatus = 'done' | 'running' | 'waiting' | 'pending' | 'failed'

export type SupportLevel = 'certified' | 'assisted' | 'experimental'

export type Priority = 'P0' | 'P1' | 'P2'

export interface Tenant {
  id: string
  name: string
  deployment: 'sharedSaas' | 'dedicatedSaas' | 'customerCloud' | 'onPrem'
  projects: number
  users: number
  monthCostUsd: number
  defaultLanguage: 'en' | 'es'
}

export interface PhaseState {
  key: string
  status: PhaseStatus
  gate?: 'C1' | 'C2' | 'C3' | 'C4'
}

export interface TargetStack {
  architecture: string
  backend: string
  frontend: string
  database: string
  cloud: string
}

export interface Project {
  id: string
  tenantId: string
  name: string
  flow: Flow
  sources: string[]
  target: TargetStack
  phases: PhaseState[]
  verdict: Verdict
  progress: number
  costUsd: number
  budgetUsd: number
  tokens: number
  rules: { total: number; approved: number; verified: number }
  openQuestions: number
  artifactLanguage: 'en' | 'es'
  owner: string
  updatedAt: string
}

export type AgentGroup = 'analysis' | 'design' | 'build' | 'quality' | 'control'

export interface AgentDefinition {
  id: string
  name: string
  nameEs?: string
  group: AgentGroup
  description: string
  descriptionEs?: string
  phases: string[]
  capabilities: string[]
  tools: string[]
  mandatory: boolean
  level: SupportLevel
  version: string
  defaultProfile: string
  relativeCost: 1 | 2 | 3
}

export type SkillType = 'source' | 'target' | 'conversion' | 'crossCutting' | 'customer'

export interface SkillDefinition {
  id: string
  name: string
  type: SkillType
  description: string
  appliesTo: string[]
  tags: string[]
  conflictsWith: string[]
  version: string
  evalScore: number | null
  status: 'published' | 'evaluating' | 'draft'
}

export interface ProviderConnection {
  id: string
  provider: 'azureFoundry' | 'awsBedrock' | 'openai' | 'anthropic' | 'vertex'
  name: string
  region: string
  auth: string
  status: 'connected' | 'error' | 'notConfigured'
  models: number
  lastCheck: string
}

export interface ModelOffering {
  id: string
  family: string
  model: string
  version: string
  connectionId: string
  providerModelId: string
  region: string
  contextK: number
  capabilities: string[]
  inputPerMTokUsd: number
  outputPerMTokUsd: number
  status: 'available' | 'deprecated' | 'disabled'
}

export type Effort = 'low' | 'medium' | 'high' | 'max'

export interface ModelProfile {
  id: string
  name: string
  offeringId: string
  effort: Effort
  providerParameter: string
  maxOutputTokens: number
  fallbackOfferingId?: string
}

export interface Rule {
  id: string
  name: string
  domain: string
  category: 'calculation' | 'validation' | 'lifecycle' | 'policy'
  priority: Priority
  confidence: 'high' | 'medium' | 'low'
  status: 'approved' | 'inReview' | 'question' | 'draft'
  statement: string
  given: string
  when: string
  then: string
  source: string
  smeQuestion?: string
  testStatus: 'tested' | 'namedNotRun' | 'none'
}

export interface RunEvent {
  id: string
  time: string
  agent: string
  phase: string
  kind: 'started' | 'completed' | 'verificationFailed' | 'selfCorrected' | 'escalated' | 'gateWaiting' | 'fanOut'
  detail: string
  tokens?: number
}

export interface Task {
  id: string
  projectId: string
  kind:
    | 'approveSpec'
    | 'reviewStories'
    | 'reviewPrototype'
    | 'answerQuestion'
    | 'escalation'
    | 'signOff'
    | 'approveArchitecture'
  title: string
  due: string
  priority: 'high' | 'normal'
}

export interface User {
  id: string
  name: string
  email: string
  tenant: string
  roles: string[]
  mfa: boolean
  lastSeen: string
  status: 'active' | 'invited' | 'disabled'
}

export interface AuditEntry {
  id: string
  time: string
  actor: string
  action: string
  target: string
  tenant: string
}
