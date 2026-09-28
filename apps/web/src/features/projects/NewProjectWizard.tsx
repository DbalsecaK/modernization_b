import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ArrowLeftRight, Check, Info, Lock, Sparkles, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUsd } from '@/lib/format'
import {
  compatibilityWarnings,
  INPUT_OPTIONS,
  mandatoryAgentIds,
  missingSkills,
  recommendAgents,
  recommendSkills,
  skillConflicts,
  SOURCE_OPTIONS,
  TARGET_OPTIONS,
  uncoveredPhases,
} from '@/lib/recommend'
import { agents, profiles, skills, users } from '@/mocks/data'
import type { AgentGroup, Flow, TargetStack } from '@/mocks/types'
import { Badge, Button, Card, CardBody, Field, Input, PageHeader, Select, Toggle } from '@/components/ui/primitives'
import { AgentCard, agentName } from '@/features/catalog/AgentCard'
import { DocumentsSection, UiReferencesSection, WorkTrackingSection, type UiReferences, type WorkTracking } from './ProjectSetupSections'

const STEPS = ['basics', 'source', 'target', 'agents', 'skills', 'models', 'pipeline', 'team', 'review'] as const
type Step = (typeof STEPS)[number]

const GROUPS: AgentGroup[] = ['analysis', 'design', 'build', 'quality', 'control']

export function NewProjectWizard() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('basics')
  const [name, setName] = useState('Card Management — CICS to Spring Boot')
  const [flow, setFlow] = useState<Flow>('modernization')
  const [language, setLanguage] = useState<'en' | 'es'>('en')
  const [sources, setSources] = useState<string[]>(['COBOL CICS', 'BMS maps', 'DB2'])
  const [delivery, setDelivery] = useState<'zip' | 'git'>('git')
  const [documents, setDocuments] = useState<string[]>([])
  const [uiRefs, setUiRefs] = useState<UiReferences>({ documents: [], screens: [], figma: [], prototypes: [] })
  const [tracking, setTracking] = useState<WorkTracking>({ integration: 'jira', project: '', autoCreate: true })
  const [target, setTarget] = useState<TargetStack>({
    architecture: 'Microservices (hexagonal)',
    backend: 'Java Spring Boot',
    frontend: 'Angular',
    database: 'PostgreSQL',
    cloud: 'AWS',
  })
  const [agentOverride, setAgentOverride] = useState<string[] | null>(null)
  const [skillOverride, setSkillOverride] = useState<string[] | null>(null)
  const [inheritModels, setInheritModels] = useState(true)
  const [modelChoice, setModelChoice] = useState<Record<string, string>>({})
  const [template, setTemplate] = useState('bankStandard')
  const [budget, setBudget] = useState(5000)
  const [maxIterations, setMaxIterations] = useState(3)
  const [autonomy, setAutonomy] = useState<'guided' | 'balanced' | 'autonomous'>('balanced')
  const [sampling, setSampling] = useState(10)
  const [team, setTeam] = useState<{ userId: string; role: string }[]>([
    { userId: 'u2', role: 'projectOwner' },
    { userId: 'u3', role: 'architect' },
  ])

  const recommendations = useMemo(() => recommendAgents(flow, sources, target), [flow, sources, target])
  // Control agents are always part of the team (spec 9.4).
  const agentIds = Array.from(new Set([...(agentOverride ?? recommendations.map((r) => r.id)), ...mandatoryAgentIds()]))
  const recommendedSkills = useMemo(() => recommendSkills(agentIds, sources, target), [agentIds, sources, target])
  const skillIds = skillOverride ?? recommendedSkills
  const warnings = compatibilityWarnings(sources, target)
  const conflicts = skillConflicts(skillIds)
  const missing = missingSkills(sources, skillIds)
  const uncovered = uncoveredPhases(flow, agentIds)
  const index = STEPS.indexOf(step)
  const sourceOptions: readonly string[] = flow === 'modernization' ? SOURCE_OPTIONS : INPUT_OPTIONS
  const estimate = agents.filter((a) => agentIds.includes(a.id)).reduce((s, a) => s + a.relativeCost * 260, 0)

  const blockers: string[] = []
  if (!name.trim()) blockers.push(t('wizard.blockers.name'))
  if (sources.length === 0) blockers.push(t('wizard.blockers.source'))
  if (uncovered.length) blockers.push(t('wizard.blockers.phases', { phases: uncovered.map((p) => t(`phases.${p}`)).join(', ') }))
  if (conflicts.length) blockers.push(t('wizard.blockers.conflicts'))

  function toggleAgent(id: string) {
    if (mandatoryAgentIds().includes(id)) return
    setAgentOverride(agentIds.includes(id) ? agentIds.filter((a) => a !== id) : [...agentIds, id])
    setSkillOverride(null)
  }

  const canUseFullStack = agentIds.includes('backend-dev') && agentIds.includes('frontend-dev')
  const usesFullStack = agentIds.includes('fullstack-dev')

  function swapFullStack() {
    if (canUseFullStack) setAgentOverride([...agentIds.filter((a) => a !== 'backend-dev' && a !== 'frontend-dev'), 'fullstack-dev'])
    else if (usesFullStack) setAgentOverride([...agentIds.filter((a) => a !== 'fullstack-dev'), 'backend-dev', 'frontend-dev'])
    setSkillOverride(null)
  }

  function toggleSkill(id: string) {
    setSkillOverride(skillIds.includes(id) ? skillIds.filter((s) => s !== id) : [...skillIds, id])
  }

  return (
    <>
      <PageHeader title={t('wizard.title')} description={t('wizard.description')} />
      <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
        <ol className="flex gap-2 overflow-x-auto lg:flex-col lg:gap-1" aria-label={t('wizard.steps')}>
          {STEPS.map((s, i) => (
            <li key={s}>
              <button
                onClick={() => setStep(s)}
                className={cn(
                  'flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm whitespace-nowrap',
                  s === step ? 'bg-surface font-medium text-text shadow-sm ring-1 ring-border' : 'text-text-2 hover:text-text',
                )}
                aria-current={s === step ? 'step' : undefined}
              >
                <span
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs',
                    i < index ? 'bg-good text-white' : s === step ? 'bg-brand text-brand-contrast' : 'bg-surface-2 text-muted',
                  )}
                >
                  {i < index ? <Check size={12} /> : i + 1}
                </span>
                {t(`wizard.stepNames.${s}`)}
              </button>
            </li>
          ))}
        </ol>

        <Card>
          <CardBody className="space-y-6 py-6">
            {step === 'basics' && (
              <>
                <StepTitle title={t('wizard.stepNames.basics')} hint={t('wizard.basicsHint')} />
                <Field label={t('wizard.projectName')}>
                  <Input value={name} onChange={(e) => setName(e.target.value)} />
                </Field>
                <div>
                  <div className="mb-2 text-sm font-medium text-text">{t('wizard.flow')}</div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {(['modernization', 'newFeature'] as const).map((f) => (
                      <ChoiceCard
                        key={f}
                        selected={flow === f}
                        onClick={() => {
                          setFlow(f)
                          setSources(f === 'modernization' ? ['COBOL CICS', 'BMS maps'] : ['User stories (Jira)', 'Figma'])
                          setAgentOverride(null)
                          setSkillOverride(null)
                        }}
                        title={t(`flows.${f}`)}
                        body={t(`wizard.flowHint.${f}`)}
                      />
                    ))}
                  </div>
                </div>
                <Field label={t('wizard.artifactLanguage')} hint={t('wizard.artifactLanguageHint')}>
                  <Select value={language} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')}>
                    <option value="en">English</option>
                    <option value="es">Español</option>
                  </Select>
                </Field>
              </>
            )}

            {step === 'source' && (
              <>
                <StepTitle
                  title={t(flow === 'modernization' ? 'wizard.sourceTitle' : 'wizard.inputsTitle')}
                  hint={t(flow === 'modernization' ? 'wizard.sourceHint' : 'wizard.inputsHint')}
                />
                <div className="flex flex-wrap gap-2">
                  {sourceOptions.map((s) => (
                    <Chip
                      key={s}
                      selected={sources.includes(s)}
                      onClick={() => {
                        setSources(sources.includes(s) ? sources.filter((x) => x !== s) : [...sources, s])
                        setAgentOverride(null)
                        setSkillOverride(null)
                      }}
                    >
                      {s}
                    </Chip>
                  ))}
                </div>
                {flow === 'modernization' ? (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <ChoiceCard selected={delivery === 'git'} onClick={() => setDelivery('git')} title={t('wizard.connectGit')} body={t('wizard.connectGitHint')} />
                    <ChoiceCard selected={delivery === 'zip'} onClick={() => setDelivery('zip')} title={t('wizard.uploadZip')} body={t('wizard.uploadZipHint')} />
                  </div>
                ) : (
                  <DocumentsSection value={documents} onChange={setDocuments} />
                )}
                <UiReferencesSection value={uiRefs} onChange={setUiRefs} />
                <WorkTrackingSection value={tracking} onChange={setTracking} />
                <Notice tone="info">{t('wizard.untrustedNotice')}</Notice>
              </>
            )}

            {step === 'target' && (
              <>
                <StepTitle title={t('wizard.targetTitle')} hint={t('wizard.targetHint')} />
                <div className="grid gap-4 sm:grid-cols-2">
                  {(Object.keys(TARGET_OPTIONS) as (keyof TargetStack)[]).map((axis) => (
                    <Field key={axis} label={t(`target.${axis}`)}>
                      <Select
                        value={target[axis]}
                        onChange={(e) => {
                          setTarget({ ...target, [axis]: e.target.value })
                          setAgentOverride(null)
                          setSkillOverride(null)
                        }}
                      >
                        {TARGET_OPTIONS[axis].map((o) => (
                          <option key={o}>{o}</option>
                        ))}
                      </Select>
                    </Field>
                  ))}
                </div>
                {warnings.length > 0 ? (
                  <div className="space-y-2">
                    {warnings.map((w) => (
                      <Notice key={w} tone="warning">
                        {t(`compat.${w}`)}
                      </Notice>
                    ))}
                  </div>
                ) : (
                  <Notice tone="good">{t('wizard.compatible')}</Notice>
                )}
              </>
            )}

            {step === 'agents' && (
              <>
                <StepTitle title={t('wizard.agentsTitle')} hint={t('wizard.agentsHint')} />
                <div className="flex flex-wrap items-center gap-3">
                  {(canUseFullStack || usesFullStack) && (
                    <Button size="sm" onClick={swapFullStack}>
                      <ArrowLeftRight size={14} /> {t(canUseFullStack ? 'wizard.useFullStack' : 'wizard.useSeparate')}
                    </Button>
                  )}
                  {agentOverride && (
                    <Button size="sm" variant="ghost" onClick={() => { setAgentOverride(null); setSkillOverride(null) }}>
                      <Sparkles size={14} /> {t('wizard.restoreRecommended')}
                    </Button>
                  )}
                  <span className="text-sm text-muted">{t('wizard.agentsSelected', { count: agentIds.length })}</span>
                </div>
                {usesFullStack && <Notice tone="info">{t('wizard.fullStackConsequence')}</Notice>}
                {uncovered.length > 0 && (
                  <Notice tone="warning">{t('wizard.blockers.phases', { phases: uncovered.map((p) => t(`phases.${p}`)).join(', ') })}</Notice>
                )}
                {GROUPS.map((group) => (
                  <section key={group}>
                    <h3 className="mb-3 text-sm font-semibold text-text">{t(`agentGroups.${group}`)}</h3>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {agents
                        .filter((a) => a.group === group)
                        .map((a) => (
                          <AgentCard
                            key={a.id}
                            agent={a}
                            selected={agentIds.includes(a.id)}
                            recommendedReason={recommendations.find((r) => r.id === a.id)?.reason}
                            onToggle={() => toggleAgent(a.id)}
                          />
                        ))}
                    </div>
                  </section>
                ))}
              </>
            )}

            {step === 'skills' && (
              <>
                <StepTitle title={t('wizard.skillsTitle')} hint={t('wizard.skillsHint')} />
                {conflicts.map(([a, b]) => (
                  <Notice key={a + b} tone="critical">
                    {t('wizard.skillConflict', { a: skills.find((s) => s.id === a)?.name, b: skills.find((s) => s.id === b)?.name })}
                  </Notice>
                ))}
                {missing.map((m) => (
                  <Notice key={m.skill} tone="warning">
                    {t('wizard.skillMissing', { source: m.source, skill: skills.find((s) => s.id === m.skill)?.name })}
                  </Notice>
                ))}
                {agents
                  .filter((a) => agentIds.includes(a.id))
                  .map((agent) => {
                    const available = skills.filter((s) => s.appliesTo.includes(agent.id))
                    if (available.length === 0) return null
                    return (
                      <section key={agent.id}>
                        <h3 className="mb-2 text-sm font-semibold text-text">{agentName(agent, i18n.language)}</h3>
                        <div className="grid gap-2 md:grid-cols-2">
                          {available.map((skill) => {
                            const on = skillIds.includes(skill.id)
                            const inConflict = conflicts.some((c) => c.includes(skill.id))
                            return (
                              <button
                                key={skill.id}
                                onClick={() => toggleSkill(skill.id)}
                                className={cn(
                                  'flex items-start gap-3 rounded-md border p-3 text-left',
                                  inConflict ? 'border-critical' : on ? 'border-series-1 bg-series-1/5' : 'border-border hover:bg-surface-2',
                                )}
                                aria-pressed={on}
                              >
                                <span className={cn('mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border', on ? 'border-series-1 bg-series-1 text-white' : 'border-border')}>
                                  {on && <Check size={11} />}
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-text">
                                    {skill.name}
                                    {recommendedSkills.includes(skill.id) && <Badge tone="accent">{t('agents.recommended')}</Badge>}
                                    {skill.status !== 'published' && <Badge>{t(`skillStatus.${skill.status}`)}</Badge>}
                                  </span>
                                  <span className="mt-0.5 block text-xs text-muted">{skill.description}</span>
                                  <span className="mt-1 block text-xs text-muted">
                                    {t(`skillTypes.${skill.type}`)} · v{skill.version}
                                    {skill.evalScore !== null && ` · ${t('skills.evalScore', { score: Math.round(skill.evalScore * 100) })}`}
                                  </span>
                                </span>
                              </button>
                            )
                          })}
                        </div>
                      </section>
                    )
                  })}
              </>
            )}

            {step === 'models' && (
              <>
                <StepTitle title={t('wizard.modelsTitle')} hint={t('wizard.modelsHint')} />
                <Toggle checked={inheritModels} onChange={setInheritModels} label={t('wizard.inheritModels')} />
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted uppercase">
                        <th className="py-2 pr-4 font-medium">{t('wizard.agent')}</th>
                        <th className="py-2 pr-4 font-medium">{t('wizard.profile')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {agents
                        .filter((a) => agentIds.includes(a.id))
                        .map((a) => (
                          <tr key={a.id} className="border-t border-border">
                            <td className="py-2 pr-4 text-text">{agentName(a, i18n.language)}</td>
                            <td className="py-2 pr-4">
                              <Select
                                disabled={inheritModels}
                                value={modelChoice[a.id] ?? a.defaultProfile}
                                onChange={(e) => setModelChoice({ ...modelChoice, [a.id]: e.target.value })}
                                className="h-9"
                              >
                                {profiles.map((p) => (
                                  <option key={p.id} value={p.id}>
                                    {p.name} — {p.providerParameter}
                                  </option>
                                ))}
                              </Select>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                <Notice tone="info">{t('wizard.verifierDifferentModel')}</Notice>
              </>
            )}

            {step === 'pipeline' && (
              <>
                <StepTitle title={t('wizard.pipelineTitle')} hint={t('wizard.pipelineHint')} />
                <div className="grid gap-3 sm:grid-cols-2">
                  {(['bankStandard', 'internalAgile'] as const).map((tpl) => (
                    <ChoiceCard key={tpl} selected={template === tpl} onClick={() => setTemplate(tpl)} title={t(`templates.${tpl}.name`)} body={t(`templates.${tpl}.body`)} />
                  ))}
                </div>
                <div>
                  <div className="mb-2 text-sm font-medium text-text">{t('hitl.autonomyTitle')}</div>
                  <div className="grid gap-3 md:grid-cols-3">
                    {(['guided', 'balanced', 'autonomous'] as const).map((a) => (
                      <ChoiceCard key={a} selected={autonomy === a} onClick={() => setAutonomy(a)} title={t(`hitl.levels.${a}.name`)} body={t(`hitl.levels.${a}.body`)} />
                    ))}
                  </div>
                </div>
                <div className="rounded-lg border border-border p-4">
                  <div className="text-sm font-medium text-text">{t('hitl.whenTitle')}</div>
                  <ul className="mt-2 space-y-1.5 text-sm text-text-2">
                    <li>• {t('hitl.when.gates', { gates: autonomy === 'autonomous' ? 'C1, C4' : 'C1, C2, C3, C4' })}</li>
                    <li>• {t('hitl.when.questions')}</li>
                    <li>• {t(autonomy === 'guided' ? 'hitl.when.reviewAllP0' : 'hitl.when.reviewException', { pct: sampling })}</li>
                    <li>• {t('hitl.when.escalations', { max: maxIterations })}</li>
                  </ul>
                  {autonomy !== 'guided' && (
                    <div className="mt-3 max-w-xs">
                      <Field label={t('hitl.sampling')} hint={t('hitl.samplingHint')}>
                        <Input type="number" min={0} max={100} value={sampling} onChange={(e) => setSampling(Number(e.target.value))} />
                      </Field>
                    </div>
                  )}
                  <p className="mt-3 text-xs text-muted">{t('hitl.keepsWorking')}</p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t('wizard.budget')} hint={t('wizard.budgetHint')}>
                    <Input type="number" min={0} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
                  </Field>
                  <Field label={t('wizard.maxIterations')} hint={t('wizard.maxIterationsHint')}>
                    <Input type="number" min={1} max={10} value={maxIterations} onChange={(e) => setMaxIterations(Number(e.target.value))} />
                  </Field>
                </div>
              </>
            )}

            {step === 'team' && (
              <>
                <StepTitle title={t('wizard.teamTitle')} hint={t('wizard.teamHint')} />
                <div className="space-y-2">
                  {team.map((member, i) => {
                    const user = users.find((u) => u.id === member.userId)!
                    return (
                      <div key={member.userId} className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3">
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-text">{user.name}</div>
                          <div className="text-xs text-muted">{user.email}</div>
                        </div>
                        <Select
                          className="h-9 w-48"
                          value={member.role}
                          onChange={(e) => setTeam(team.map((m, j) => (j === i ? { ...m, role: e.target.value } : m)))}
                          aria-label={t('wizard.role')}
                        >
                          {['projectOwner', 'architect', 'analyst', 'businessReviewer', 'developer', 'observer'].map((r) => (
                            <option key={r} value={r}>
                              {t(`roles.${r}`)}
                            </option>
                          ))}
                        </Select>
                        <button onClick={() => setTeam(team.filter((_, j) => j !== i))} className="rounded p-1 text-muted hover:text-critical" aria-label={t('common.remove')}>
                          <X size={16} />
                        </button>
                      </div>
                    )
                  })}
                </div>
                <Select
                  className="max-w-sm"
                  value=""
                  onChange={(e) => e.target.value && setTeam([...team, { userId: e.target.value, role: 'observer' }])}
                  aria-label={t('wizard.addMember')}
                >
                  <option value="">{t('wizard.addMember')}</option>
                  {users
                    .filter((u) => !team.some((m) => m.userId === u.id))
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name}
                      </option>
                    ))}
                </Select>
                <Notice tone="info">{t('wizard.segregation')}</Notice>
              </>
            )}

            {step === 'review' && (
              <>
                <StepTitle title={t('wizard.reviewTitle')} hint={t('wizard.reviewHint')} />
                <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                  <Summary label={t('wizard.projectName')}>{name}</Summary>
                  <Summary label={t('wizard.flow')}>{t(`flows.${flow}`)}</Summary>
                  <Summary label={t('wizard.stepNames.source')}>{sources.join(', ')}</Summary>
                  <Summary label={t('setup.uiTitle')}>
                    {t('setup.summaryUi', { screens: uiRefs.screens.length, figma: uiRefs.figma.length, prototypes: uiRefs.prototypes.length })}
                  </Summary>
                  <Summary label={t('setup.trackingTitle')}>
                    {tracking.integration === 'none' ? t('setup.noIntegration') : `${tracking.integration === 'jira' ? 'Jira' : 'Azure DevOps'} · ${tracking.project || '—'}`}
                  </Summary>
                  <Summary label={t('wizard.stepNames.target')}>
                    {target.architecture} · {target.backend} · {target.frontend} · {target.database} · {target.cloud}
                  </Summary>
                  <Summary label={t('wizard.stepNames.agents')}>{t('wizard.agentsSelected', { count: agentIds.length })}</Summary>
                  <Summary label={t('wizard.stepNames.skills')}>{t('wizard.skillsSelected', { count: skillIds.length })}</Summary>
                  <Summary label={t('wizard.artifactLanguage')}>{language === 'en' ? 'English' : 'Español'}</Summary>
                  <Summary label={t('wizard.budget')}>{formatUsd(budget)}</Summary>
                  <Summary label={t('wizard.estimate')}>{formatUsd(estimate)}</Summary>
                  <Summary label={t('wizard.stepNames.pipeline')}>{t(`templates.${template}.name`)}</Summary>
                  <Summary label={t('hitl.autonomyTitle')}>{t(`hitl.levels.${autonomy}.name`)}</Summary>
                </dl>
                {warnings.map((w) => (
                  <Notice key={w} tone="warning">
                    {t(`compat.${w}`)}
                  </Notice>
                ))}
                {blockers.map((b) => (
                  <Notice key={b} tone="critical">
                    {b}
                  </Notice>
                ))}
                <Notice tone="info">{t('wizard.adrNotice')}</Notice>
              </>
            )}

            <div className="flex justify-between border-t border-border pt-5">
              <Button variant="ghost" disabled={index === 0} onClick={() => setStep(STEPS[index - 1])}>
                {t('common.back')}
              </Button>
              {step === 'review' ? (
                <Button variant="primary" disabled={blockers.length > 0} onClick={() => void navigate({ to: '/projects/$projectId', params: { projectId: 'p1' } })}>
                  {t('wizard.create')}
                </Button>
              ) : (
                <Button variant="primary" onClick={() => setStep(STEPS[index + 1])}>
                  {t('common.next')}
                </Button>
              )}
            </div>
          </CardBody>
        </Card>
      </div>
    </>
  )
}

function StepTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div>
      <h2 className="text-lg font-semibold text-text">{title}</h2>
      <p className="mt-1 text-sm text-text-2">{hint}</p>
    </div>
  )
}

function ChoiceCard({ selected, onClick, title, body }: { selected: boolean; onClick: () => void; title: string; body: string }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      className={cn('rounded-lg border p-4 text-left', selected ? 'border-series-1 ring-1 ring-series-1' : 'border-border hover:bg-surface-2')}
    >
      <div className="text-sm font-semibold text-text">{title}</div>
      <div className="mt-1 text-sm text-text-2">{body}</div>
    </button>
  )
}

function Chip({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm',
        selected ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-text-2 hover:bg-surface-2',
      )}
    >
      {selected && <Check size={14} />}
      {children}
    </button>
  )
}

export function Notice({ tone, children }: { tone: 'info' | 'warning' | 'critical' | 'good'; children: ReactNode }) {
  const Icon = tone === 'info' ? Info : tone === 'good' ? Check : tone === 'critical' ? Lock : AlertTriangle
  return (
    <div
      className={cn(
        'flex items-start gap-2 rounded-md px-3 py-2.5 text-sm',
        tone === 'info' && 'bg-info/8 text-text-2',
        tone === 'warning' && 'bg-warning/12 text-text-2',
        tone === 'critical' && 'bg-critical/10 text-text-2',
        tone === 'good' && 'bg-good/10 text-text-2',
      )}
      role={tone === 'critical' ? 'alert' : undefined}
    >
      <Icon
        size={16}
        className={cn(
          'mt-0.5 shrink-0',
          tone === 'info' && 'text-info',
          tone === 'warning' && 'text-warning',
          tone === 'critical' && 'text-critical',
          tone === 'good' && 'text-good',
        )}
      />
      <span>{children}</span>
    </div>
  )
}

function Summary({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-text">{children}</dd>
    </div>
  )
}
