import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  ArrowLeftRight,
  Check,
  CheckCircle2,
  Info,
  Loader2,
  Lock,
  Sparkles,
  X,
  XCircle,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatUsd } from '@/lib/format'
import { can, useMe } from '@/api/session'
import { ApiError } from '@/api/client'
import { useMembers } from '@/api/admin'
import { useProfiles } from '@/api/ai'
import {
  AXES,
  addLink,
  setRepository,
  uploadInput,
  useCatalog,
  useComposition,
  useCreateProject,
  type Catalog,
  type Composition,
  type Flow,
  type Target,
} from '@/api/projects'
import { Badge, Button, Card, CardBody, Field, Input, PageHeader, Select, Toggle } from '@/components/ui/primitives'
import { Textarea } from '@/components/ui/overlay'
import { AgentCard, agentName } from '@/features/catalog/AgentCard'
import {
  ArchiveSection,
  DocumentsSection,
  EMPTY_UI_REFERENCES,
  GitSection,
  UiReferencesSection,
  WorkTrackingSection,
  type GitInput,
  type UiReferences,
} from './ProjectSetupSections'

const STEPS = ['basics', 'source', 'target', 'agents', 'skills', 'models', 'pipeline', 'team', 'review'] as const
type Step = (typeof STEPS)[number]
const GROUPS = ['analysis', 'design', 'build', 'quality', 'control'] as const
const PROJECT_ROLES = ['projectOwner', 'architect', 'analyst', 'businessReviewer', 'developer', 'observer'] as const
const DEFAULT_SOURCES: Record<Flow, string[]> = {
  modernization: ['cobol-cics', 'bms'],
  newFeature: ['user-stories', 'figma'],
  independentValidation: ['sybase-sp'],
  extendExisting: ['spring-boot-app', 'user-stories'],
}
const FLOWS = ['modernization', 'newFeature', 'extendExisting', 'independentValidation'] as const
const DEFAULT_TARGET: Target = {
  architecture: 'microservices-hexagonal',
  backend: 'spring-boot',
  frontend: 'angular',
  database: 'postgresql',
  cloud: 'aws',
}

type TaskState = { label: string; status: 'pending' | 'ok' | 'failed'; detail?: string }

export function NewProjectWizard() {
  const { t } = useTranslation()
  const catalog = useCatalog()
  if (!catalog.data) return <PageHeader title={t('wizard.title')} description={t('wizard.description')} />
  return <Wizard catalog={catalog.data} />
}

function errorText(t: (k: string, o?: Record<string, unknown>) => string, error: unknown) {
  if (error instanceof ApiError) return t(`inputs.rejections.${error.code}`, { defaultValue: error.message })
  return String(error)
}

function Wizard({ catalog }: { catalog: Catalog }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const me = useMe()
  const canConfigureModels = can(me, 'models.configure')
  const canManageUsers = can(me, 'users.manage')
  const members = useMembers(canManageUsers)
  const profiles = useProfiles(canConfigureModels)
  const create = useCreateProject()

  const [step, setStep] = useState<Step>('basics')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [flow, setFlow] = useState<Flow>('modernization')
  const [language, setLanguage] = useState<'en' | 'es'>('en')
  const [sources, setSources] = useState<string[]>(DEFAULT_SOURCES.modernization)
  const [delivery, setDelivery] = useState<'git' | 'zip'>('git')
  const [git, setGit] = useState<GitInput>({ url: '', branch: 'main', token: '' })
  const [archive, setArchive] = useState<File[]>([])
  const [targetArchive, setTargetArchive] = useState<File[]>([])
  const [documents, setDocuments] = useState<File[]>([])
  const [uiRefs, setUiRefs] = useState<UiReferences>(EMPTY_UI_REFERENCES)
  const [target, setTarget] = useState<Target>(DEFAULT_TARGET)
  const [agentOverride, setAgentOverride] = useState<string[] | null>(null)
  const [skillOverride, setSkillOverride] = useState<string[] | null>(null)
  const [inheritModels, setInheritModels] = useState(true)
  const [modelChoice, setModelChoice] = useState<Record<string, string>>({})
  const [template, setTemplate] = useState(catalog.pipelineTemplates[0]?.key ?? 'bankStandard')
  const [budget, setBudget] = useState('5000')
  const [maxIterations, setMaxIterations] = useState(3)
  const [autonomy, setAutonomy] = useState<'guided' | 'balanced' | 'autonomous'>('balanced')
  const [sampling, setSampling] = useState(10)
  const [team, setTeam] = useState<{ userId: string; role: string }[]>([])
  const [tasks, setTasks] = useState<TaskState[] | null>(null)
  const [createdId, setCreatedId] = useState<string | null>(null)

  const composition = useComposition({ flow, sources, target, agents: agentOverride, skills: skillOverride })
  const result: Composition | undefined = composition.data
  const agentIds = result?.agents ?? []
  const skillIds = result?.skills ?? []
  const agentByKey = new Map(catalog.agents.map((a) => [a.key, a]))
  const skillTitle = (key: string) => catalog.skills.find((s) => s.key === key)?.title ?? key
  const sourceName = (key: string) => catalog.sources.find((s) => s.key === key)?.name ?? key
  const optionName = (axis: string, key: string) =>
    catalog.targets.find((o) => o.axis === axis && o.key === key)?.name ?? key
  const index = STEPS.indexOf(step)
  // Flow 1, Flow 3 and Flow 4 start from code: the legacy code, or the existing application Flow 3 extends
  // (ADR-0026); Flow 4 (ADR-0025) also brings the third party's target.
  const legacyCode = flow !== 'newFeature'
  const extending = flow === 'extendExisting'
  // Flow 2 and Flow 3 bring the documents of the request; Flow 3 has no UI delta, so no UI references (ADR-0026).
  const withDocuments = flow === 'newFeature' || extending
  const resetComposition = () => {
    setAgentOverride(null)
    setSkillOverride(null)
  }

  const blockers: string[] = []
  if (!name.trim()) blockers.push(t('wizard.blockers.name'))
  if (sources.length === 0) blockers.push(t('wizard.blockers.source'))
  for (const p of result?.problems ?? []) {
    blockers.push(
      t(`wizard.problems.${p.code}`, {
        defaultValue: `${p.code}${p.subject ? `: ${p.subject}` : ''}`,
        subject: p.code.startsWith('uncovered') ? t(`phases.${p.subject}`) : (p.subject ?? ''),
      }),
    )
  }

  function toggleAgent(key: string) {
    if (agentByKey.get(key)?.mandatory) return
    setAgentOverride(agentIds.includes(key) ? agentIds.filter((a) => a !== key) : [...agentIds, key])
    setSkillOverride(null)
  }

  const canUseFullStack = agentIds.includes('backend-dev') && agentIds.includes('frontend-dev')
  const usesFullStack = agentIds.includes('fullstack-dev')

  function swapFullStack() {
    if (canUseFullStack)
      setAgentOverride([...agentIds.filter((a) => a !== 'backend-dev' && a !== 'frontend-dev'), 'fullstack-dev'])
    else if (usesFullStack)
      setAgentOverride([...agentIds.filter((a) => a !== 'fullstack-dev'), 'backend-dev', 'frontend-dev'])
    setSkillOverride(null)
  }

  function toggleSkill(key: string) {
    setSkillOverride(skillIds.includes(key) ? skillIds.filter((s) => s !== key) : [...skillIds, key])
  }

  function modelWarning(agent: string) {
    const check = result?.models.find((m) => m.agent === agent)
    if (!check) return undefined
    if (!check.profileId) return t('wizard.noProfile')
    if (check.missing.length)
      return t('wizard.modelMissing', { caps: check.missing.map((c) => t(`capabilities.${c}`)).join(', ') })
    return undefined
  }

  async function submit() {
    if (!result) return
    const items: { label: string; run: (id: string) => Promise<unknown> }[] = []
    const named = (files: File[]) => (files.length === 1 ? files[0].name : `${files[0].name} (+${files.length - 1})`)
    if (legacyCode && delivery === 'zip' && archive.length > 0)
      items.push({ label: named(archive), run: (id) => uploadInput(id, archive, 'source_archive') })
    if (flow === 'independentValidation' && targetArchive.length > 0)
      items.push({ label: named(targetArchive), run: (id) => uploadInput(id, targetArchive, 'target_archive') })
    if (legacyCode && delivery === 'git' && git.url.trim())
      items.push({
        label: git.url.trim(),
        run: (id) =>
          setRepository(id, {
            url: git.url.trim(),
            branch: git.branch || 'main',
            token: git.token || null,
            clearToken: false,
          }),
      })
    for (const f of withDocuments ? documents : [])
      items.push({ label: f.name, run: (id) => uploadInput(id, f, 'document') })
    const refs = extending ? EMPTY_UI_REFERENCES : uiRefs
    for (const s of refs.screens) items.push({ label: s.file.name, run: (id) => uploadInput(id, s.file, 'screenshot') })
    for (const l of refs.figma) items.push({ label: l, run: (id) => addLink(id, 'figma_link', l) })
    for (const l of refs.prototypes) items.push({ label: l, run: (id) => addLink(id, 'prototype_link', l) })

    try {
      const project = await create.mutateAsync({
        name: name.trim(),
        description,
        flow,
        artifactLanguage: language,
        sources,
        target,
        agents: result.agents,
        skills: result.skills,
        pipelineTemplate: template,
        autonomy,
        maxIterations,
        samplingPct: sampling,
        budgetUsd: Number(budget) > 0 ? budget : null,
        team: team.map((m) => ({ userId: m.userId, roleKey: m.role })),
        modelChoices: inheritModels
          ? []
          : Object.entries(modelChoice)
              .filter(([agent, profile]) => profile && agentIds.includes(agent))
              .map(([agentRole, profileId]) => ({ agentRole, profileId })),
      })
      setCreatedId(project.id)
      const states: TaskState[] = items.map((i) => ({ label: i.label, status: 'pending' }))
      setTasks([...states])
      for (const [i, item] of items.entries()) {
        try {
          await item.run(project.id)
          states[i] = { ...states[i], status: 'ok' }
        } catch (error) {
          states[i] = { ...states[i], status: 'failed', detail: errorText(t, error) }
        }
        setTasks([...states])
      }
      if (states.every((s) => s.status === 'ok'))
        void navigate({ to: '/projects/$projectId', params: { projectId: project.id } })
    } catch (error) {
      setTasks([{ label: t('wizard.create'), status: 'failed', detail: errorText(t, error) }])
    }
  }

  if (tasks) return <Creating tasks={tasks} projectId={createdId} onBack={() => setTasks(null)} />

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
                  s === step
                    ? 'bg-surface font-medium text-text shadow-sm ring-1 ring-border'
                    : 'text-text-2 hover:text-text',
                )}
                aria-current={s === step ? 'step' : undefined}
              >
                <span
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs',
                    i < index
                      ? 'bg-good text-white'
                      : s === step
                        ? 'bg-brand text-brand-contrast'
                        : 'bg-surface-2 text-muted',
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
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Card Management — CICS to Spring Boot"
                  />
                </Field>
                <Field label={t('wizard.projectDescription')}>
                  <Textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
                </Field>
                <div>
                  <div className="mb-2 text-sm font-medium text-text">{t('wizard.flow')}</div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {FLOWS.map((f) => (
                      <ChoiceCard
                        key={f}
                        selected={flow === f}
                        onClick={() => {
                          setFlow(f)
                          setSources(DEFAULT_SOURCES[f])
                          // Flow 3 extends a Spring Boot backend; the UI delta is out of scope (ADR-0026).
                          if (f === 'extendExisting') setTarget({ ...target, backend: 'spring-boot', frontend: 'none' })
                          resetComposition()
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
                  title={t(
                    extending ? 'wizard.existingTitle' : legacyCode ? 'wizard.sourceTitle' : 'wizard.inputsTitle',
                  )}
                  hint={t(extending ? 'wizard.existingHint' : legacyCode ? 'wizard.sourceHint' : 'wizard.inputsHint')}
                />
                <div className="flex flex-wrap gap-2">
                  {catalog.sources
                    .filter((s) => s.flows.includes(flow))
                    .map((s) => (
                      <Chip
                        key={s.key}
                        selected={sources.includes(s.key)}
                        onClick={() => {
                          setSources(sources.includes(s.key) ? sources.filter((x) => x !== s.key) : [...sources, s.key])
                          resetComposition()
                        }}
                      >
                        {t(`sourceOptions.${s.key}`, { defaultValue: s.name })}
                      </Chip>
                    ))}
                </div>
                {catalog.sources
                  .filter((s) => sources.includes(s.key) && (s.versions ?? []).length > 0)
                  .map((s) => (
                    <p key={s.key} className="text-xs text-text-2">
                      {t('wizard.sourceVersions', {
                        source: t(`sourceOptions.${s.key}`, { defaultValue: s.name }),
                        versions: (s.versions ?? [])
                          .map((v) => `${v.name}${v.level === 'planned' ? ` (${t('wizard.versionPlanned')})` : ''}`)
                          .join(', '),
                      })}
                    </p>
                  ))}
                {legacyCode ? (
                  <>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ChoiceCard
                        selected={delivery === 'git'}
                        onClick={() => setDelivery('git')}
                        title={t('wizard.connectGit')}
                        body={t('wizard.connectGitHint')}
                      />
                      <ChoiceCard
                        selected={delivery === 'zip'}
                        onClick={() => setDelivery('zip')}
                        title={t('wizard.uploadZip')}
                        body={t('wizard.uploadZipHint')}
                      />
                    </div>
                    {delivery === 'git' ? (
                      <GitSection value={git} onChange={setGit} />
                    ) : (
                      <ArchiveSection
                        value={archive}
                        onChange={setArchive}
                        prompt={extending ? t('setup.dropExistingArchive') : undefined}
                      />
                    )}
                    {flow === 'independentValidation' && (
                      <div>
                        <div className="mb-2 text-sm font-medium text-text">{t('inputs.kinds.target_archive')}</div>
                        <ArchiveSection
                          value={targetArchive}
                          onChange={setTargetArchive}
                          hint={t('inputs.targetArchiveHint')}
                          label={t('inputs.kinds.target_archive')}
                        />
                      </div>
                    )}
                    {extending && <DocumentsSection value={documents} onChange={setDocuments} />}
                  </>
                ) : (
                  <DocumentsSection value={documents} onChange={setDocuments} />
                )}
                {!extending && <UiReferencesSection value={uiRefs} onChange={setUiRefs} />}
                <WorkTrackingSection />
                <Notice tone="info">{t('wizard.untrustedNotice')}</Notice>
              </>
            )}

            {step === 'target' && (
              <>
                <StepTitle title={t('wizard.targetTitle')} hint={t('wizard.targetHint')} />
                <div className="grid gap-4 sm:grid-cols-2">
                  {AXES.map((axis) => {
                    const option = catalog.targets.find((o) => o.axis === axis && o.key === target[axis])
                    const versions = option?.versions ?? []
                    const chosen = target.versions?.[axis] ?? versions.find((v) => v.default)?.key ?? ''
                    return (
                      <Field key={axis} label={t(`target.${axis}`)}>
                        <Select
                          value={target[axis]}
                          onChange={(e) => {
                            const next = catalog.targets.find((o) => o.axis === axis && o.key === e.target.value)
                            const fallback = next?.versions?.find((v) => v.default)?.key
                            const versionsNext = { ...(target.versions ?? {}) }
                            if (fallback) versionsNext[axis] = fallback
                            else delete versionsNext[axis]
                            setTarget({ ...target, [axis]: e.target.value, versions: versionsNext })
                            resetComposition()
                          }}
                        >
                          {catalog.targets
                            .filter((o) => o.axis === axis)
                            .map((o) => (
                              <option key={o.key} value={o.key}>
                                {o.key === 'none' ? t('wizard.noFrontend') : o.name}
                              </option>
                            ))}
                        </Select>
                        {versions.length > 0 && (
                          <Select
                            aria-label={`${t('target.' + axis)} · ${t('wizard.version')}`}
                            className="mt-2"
                            value={chosen}
                            onChange={(e) => {
                              setTarget({ ...target, versions: { ...(target.versions ?? {}), [axis]: e.target.value } })
                              resetComposition()
                            }}
                          >
                            {versions.map((v) => (
                              <option key={v.key} value={v.key} disabled={v.level === 'planned'}>
                                {v.name}
                                {v.level === 'planned' ? ` · ${t('wizard.versionPlanned')}` : ''}
                              </option>
                            ))}
                          </Select>
                        )}
                      </Field>
                    )
                  })}
                </div>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  {Array.from(new Set((catalog.preferences ?? []).map((p) => p.group)))
                    .filter((group) => group !== 'practices')
                    .map((group) => (
                      <Field key={group} label={t(`wizard.preferences.${group}`, { defaultValue: group })}>
                        <Select
                          value={
                            (target.preferences?.[group] as string | undefined) ??
                            (catalog.preferences ?? []).find((p) => p.group === group && p.default)?.key ??
                            ''
                          }
                          onChange={(e) => {
                            const { [group]: _dropped, ...rest } = target.preferences ?? {}
                            void _dropped
                            setTarget({
                              ...target,
                              preferences: e.target.value ? { ...rest, [group]: e.target.value } : rest,
                            })
                            resetComposition()
                          }}
                        >
                          {!(catalog.preferences ?? []).some((p) => p.group === group && p.default) && (
                            <option value="">{t('wizard.preferences.none')}</option>
                          )}
                          {(catalog.preferences ?? [])
                            .filter((p) => p.group === group)
                            .map((p) => (
                              <option key={p.key} value={p.key}>
                                {p.name}
                              </option>
                            ))}
                        </Select>
                      </Field>
                    ))}
                </div>
                <Field label={t('wizard.preferences.practices')} hint={t('wizard.preferences.practicesHint')}>
                  <div className="flex flex-wrap gap-2">
                    {(catalog.preferences ?? [])
                      .filter((p) => p.group === 'practices')
                      .map((p) => {
                        const chosen = (target.preferences?.practices as string[] | undefined) ?? []
                        const selected = chosen.includes(p.key)
                        return (
                          <Chip
                            key={p.key}
                            selected={selected}
                            onClick={() => {
                              const next = selected ? chosen.filter((k) => k !== p.key) : [...chosen, p.key]
                              setTarget({ ...target, preferences: { ...(target.preferences ?? {}), practices: next } })
                              resetComposition()
                            }}
                          >
                            {p.name}
                          </Chip>
                        )
                      })}
                  </div>
                </Field>
                {result && result.warnings.length > 0 ? (
                  <div className="space-y-2">
                    {result.warnings.map((w) => (
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
                    <Button size="sm" variant="ghost" onClick={resetComposition}>
                      <Sparkles size={14} /> {t('wizard.restoreRecommended')}
                    </Button>
                  )}
                  <span className="text-sm text-muted">{t('wizard.agentsSelected', { count: agentIds.length })}</span>
                </div>
                {usesFullStack && <Notice tone="info">{t('wizard.fullStackConsequence')}</Notice>}
                {(result?.uncoveredPhases.length ?? 0) > 0 && (
                  <Notice tone="warning">
                    {t('wizard.blockers.phases', {
                      phases: result!.uncoveredPhases.map((p) => t(`phases.${p}`)).join(', '),
                    })}
                  </Notice>
                )}
                {GROUPS.map((group) => (
                  <section key={group}>
                    <h3 className="mb-3 text-sm font-semibold text-text">{t(`agentGroups.${group}`)}</h3>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {catalog.agents
                        .filter((a) => a.group === group)
                        .map((a) => (
                          <AgentCard
                            key={a.key}
                            agent={a}
                            selected={agentIds.includes(a.key)}
                            recommendedReason={result?.recommendedAgents.find((r) => r.agent === a.key)?.reason}
                            modelWarning={agentIds.includes(a.key) ? modelWarning(a.key) : undefined}
                            onToggle={() => toggleAgent(a.key)}
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
                {result?.conflicts.map(([a, b]) => (
                  <Notice key={a + b} tone="critical">
                    {t('wizard.skillConflict', { a: skillTitle(a), b: skillTitle(b) })}
                  </Notice>
                ))}
                {result?.missingSkills.map((m) => (
                  <Notice key={m.skill} tone="warning">
                    {t('wizard.skillMissing', { source: sourceName(m.source), skill: skillTitle(m.skill) })}
                  </Notice>
                ))}
                {catalog.agents
                  .filter((a) => agentIds.includes(a.key))
                  .map((agent) => {
                    const available = catalog.skills.filter((s) => s.agents.includes(agent.key))
                    if (available.length === 0) return null
                    return (
                      <section key={agent.key}>
                        <h3 className="mb-2 text-sm font-semibold text-text">{agentName(agent, i18n.language)}</h3>
                        <div className="grid gap-2 md:grid-cols-2">
                          {available.map((skill) => {
                            const on = skillIds.includes(skill.key)
                            const inConflict = result?.conflicts.some((c) => c.includes(skill.key))
                            return (
                              <button
                                key={skill.key}
                                onClick={() => toggleSkill(skill.key)}
                                className={cn(
                                  'flex items-start gap-3 rounded-md border p-3 text-left',
                                  inConflict
                                    ? 'border-critical'
                                    : on
                                      ? 'border-series-1 bg-series-1/5'
                                      : 'border-border hover:bg-surface-2',
                                )}
                                aria-pressed={on}
                              >
                                <span
                                  className={cn(
                                    'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border',
                                    on ? 'border-series-1 bg-series-1 text-white' : 'border-border',
                                  )}
                                >
                                  {on && <Check size={11} />}
                                </span>
                                <span className="min-w-0 flex-1">
                                  <span className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-text">
                                    {skill.title}
                                    {result?.recommendedSkills.includes(skill.key) && (
                                      <Badge tone="accent">{t('agents.recommended')}</Badge>
                                    )}
                                    {skill.status !== 'published' && <Badge>{t(`skillStatus.${skill.status}`)}</Badge>}
                                  </span>
                                  <span className="mt-0.5 block text-xs text-muted">{skill.description}</span>
                                  <span className="mt-1 block text-xs text-muted">
                                    {t(`skillTypes.${skill.type}`)} · v{skill.version}
                                    {skill.evalScore != null &&
                                      ` · ${t('skills.evalScore', { score: Math.round(skill.evalScore * 100) })}`}
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
                <Toggle
                  checked={inheritModels}
                  onChange={setInheritModels}
                  disabled={!canConfigureModels}
                  label={t('wizard.inheritModels')}
                />
                {!canConfigureModels && <Notice tone="info">{t('wizard.modelsNeedPermission')}</Notice>}
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-muted uppercase">
                        <th className="py-2 pr-4 font-medium">{t('wizard.agent')}</th>
                        <th className="py-2 pr-4 font-medium">{t('wizard.profile')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {catalog.agents
                        .filter((a) => agentIds.includes(a.key))
                        .map((a) => {
                          const check = result?.models.find((m) => m.agent === a.key)
                          const warning = modelWarning(a.key)
                          return (
                            <tr key={a.key} className="border-t border-border">
                              <td className="py-2 pr-4 text-text">{agentName(a, i18n.language)}</td>
                              <td className="py-2 pr-4">
                                {inheritModels ? (
                                  <span className="text-text-2">{check?.profileName ?? t('wizard.inherited')}</span>
                                ) : (
                                  <Select
                                    value={modelChoice[a.key] ?? ''}
                                    onChange={(e) => setModelChoice({ ...modelChoice, [a.key]: e.target.value })}
                                    className="h-9"
                                    aria-label={`${t('wizard.profile')} · ${agentName(a, i18n.language)}`}
                                  >
                                    <option value="">{t('wizard.inherited')}</option>
                                    {(profiles.data ?? []).map((p) => (
                                      <option key={p.id} value={p.id}>
                                        {p.name} — {p.model}
                                      </option>
                                    ))}
                                  </Select>
                                )}
                                {warning && (
                                  <div className="mt-1 flex items-center gap-1 text-xs text-warning-ink">
                                    <AlertTriangle size={12} /> {warning}
                                  </div>
                                )}
                              </td>
                            </tr>
                          )
                        })}
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
                  {catalog.pipelineTemplates.map((tpl) => (
                    <ChoiceCard
                      key={tpl.key}
                      selected={template === tpl.key}
                      onClick={() => setTemplate(tpl.key)}
                      title={t(`templates.${tpl.key}.name`, { defaultValue: tpl.name })}
                      body={t(`templates.${tpl.key}.body`, { defaultValue: tpl.description })}
                    />
                  ))}
                </div>
                <div>
                  <div className="mb-2 text-sm font-medium text-text">{t('hitl.autonomyTitle')}</div>
                  <div className="grid gap-3 md:grid-cols-3">
                    {(['guided', 'balanced', 'autonomous'] as const).map((a) => (
                      <ChoiceCard
                        key={a}
                        selected={autonomy === a}
                        onClick={() => setAutonomy(a)}
                        title={t(`hitl.levels.${a}.name`)}
                        body={t(`hitl.levels.${a}.body`)}
                      />
                    ))}
                  </div>
                </div>
                <div className="rounded-lg border border-border p-4">
                  <div className="text-sm font-medium text-text">{t('hitl.whenTitle')}</div>
                  <ul className="mt-2 space-y-1.5 text-sm text-text-2">
                    <li>
                      •{' '}
                      {t('hitl.when.gates', {
                        gates: (catalog.pipelineTemplates.find((x) => x.key === template)?.requiredGates ?? []).join(
                          ', ',
                        ),
                      })}
                    </li>
                    <li>• {t('hitl.when.questions')}</li>
                    <li>
                      •{' '}
                      {t(autonomy === 'guided' ? 'hitl.when.reviewAllP0' : 'hitl.when.reviewException', {
                        pct: sampling,
                      })}
                    </li>
                    <li>• {t('hitl.when.escalations', { max: maxIterations })}</li>
                  </ul>
                  {autonomy !== 'guided' && (
                    <div className="mt-3 max-w-xs">
                      <Field label={t('hitl.sampling')} hint={t('hitl.samplingHint')}>
                        <Input
                          type="number"
                          min={0}
                          max={100}
                          value={sampling}
                          onChange={(e) => setSampling(Number(e.target.value))}
                        />
                      </Field>
                    </div>
                  )}
                  <p className="mt-3 text-xs text-muted">{t('hitl.keepsWorking')}</p>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label={t('wizard.budget')} hint={t('wizard.budgetHint')}>
                    <Input type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} />
                  </Field>
                  <Field label={t('wizard.maxIterations')} hint={t('wizard.maxIterationsHint')}>
                    <Input
                      type="number"
                      min={1}
                      max={10}
                      value={maxIterations}
                      onChange={(e) => setMaxIterations(Number(e.target.value))}
                    />
                  </Field>
                </div>
              </>
            )}

            {step === 'team' && (
              <>
                <StepTitle title={t('wizard.teamTitle')} hint={t('wizard.teamHint')} />
                <Notice tone="info">{t('wizard.youAreOwner')}</Notice>
                {canManageUsers ? (
                  <>
                    <div className="space-y-2">
                      {team.map((member, i) => {
                        const user = members.data?.find((u) => u.id === member.userId)
                        return (
                          <div
                            key={member.userId}
                            className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="text-sm font-medium text-text">{user?.displayName}</div>
                              <div className="text-xs text-muted">{user?.email}</div>
                            </div>
                            <Select
                              className="h-9 w-48"
                              value={member.role}
                              onChange={(e) =>
                                setTeam(team.map((m, j) => (j === i ? { ...m, role: e.target.value } : m)))
                              }
                              aria-label={t('wizard.role')}
                            >
                              {PROJECT_ROLES.map((r) => (
                                <option key={r} value={r}>
                                  {t(`roles.${r}`)}
                                </option>
                              ))}
                            </Select>
                            <button
                              onClick={() => setTeam(team.filter((_, j) => j !== i))}
                              className="rounded p-1 text-muted hover:text-critical"
                              aria-label={t('common.remove')}
                            >
                              <X size={16} />
                            </button>
                          </div>
                        )
                      })}
                    </div>
                    <Select
                      className="max-w-sm"
                      value=""
                      onChange={(e) =>
                        e.target.value && setTeam([...team, { userId: e.target.value, role: 'observer' }])
                      }
                      aria-label={t('wizard.addMember')}
                    >
                      <option value="">{t('wizard.addMember')}</option>
                      {(members.data ?? [])
                        .filter(
                          (u) => u.status === 'active' && u.id !== me?.user.id && !team.some((m) => m.userId === u.id),
                        )
                        .map((u) => (
                          <option key={u.id} value={u.id}>
                            {u.displayName}
                          </option>
                        ))}
                    </Select>
                  </>
                ) : (
                  <Notice tone="info">{t('wizard.teamLater')}</Notice>
                )}
                <Notice tone="info">{t('wizard.segregation')}</Notice>
              </>
            )}

            {step === 'review' && (
              <>
                <StepTitle title={t('wizard.reviewTitle')} hint={t('wizard.reviewHint')} />
                <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
                  <Summary label={t('wizard.projectName')}>{name || '—'}</Summary>
                  <Summary label={t('wizard.flow')}>{t(`flows.${flow}`)}</Summary>
                  <Summary label={t('wizard.stepNames.source')}>{sources.map(sourceName).join(', ')}</Summary>
                  <Summary label={t('setup.uiTitle')}>
                    {t('setup.summaryUi', {
                      screens: uiRefs.screens.length,
                      figma: uiRefs.figma.length,
                      prototypes: uiRefs.prototypes.length,
                    })}
                  </Summary>
                  <Summary label={t('wizard.stepNames.target')}>
                    {AXES.map((axis) => {
                      const version = catalog.targets
                        .find((o) => o.axis === axis && o.key === target[axis])
                        ?.versions?.find((v) => v.key === target.versions?.[axis])
                      return version
                        ? `${optionName(axis, target[axis])} ${version.key}`
                        : optionName(axis, target[axis])
                    }).join(' · ')}
                  </Summary>
                  <Summary label={t('wizard.stepNames.agents')}>
                    {t('wizard.agentsSelected', { count: agentIds.length })}
                  </Summary>
                  <Summary label={t('wizard.stepNames.skills')}>
                    {t('wizard.skillsSelected', { count: skillIds.length })}
                  </Summary>
                  <Summary label={t('wizard.artifactLanguage')}>{language === 'en' ? 'English' : 'Español'}</Summary>
                  <Summary label={t('wizard.budget')}>{Number(budget) > 0 ? formatUsd(Number(budget)) : '—'}</Summary>
                  <Summary label={t('wizard.estimate')}>{formatUsd(result?.estimateUsd ?? 0)}</Summary>
                  <Summary label={t('wizard.stepNames.pipeline')}>
                    {t(`templates.${template}.name`, { defaultValue: template })}
                  </Summary>
                  <Summary label={t('hitl.autonomyTitle')}>{t(`hitl.levels.${autonomy}.name`)}</Summary>
                </dl>
                {result?.warnings.map((w) => (
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
                <Button
                  variant="primary"
                  disabled={blockers.length > 0 || !result || create.isPending}
                  onClick={() => void submit()}
                >
                  {create.isPending && <Loader2 size={14} className="animate-spin" />} {t('wizard.create')}
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

function Creating({ tasks, projectId, onBack }: { tasks: TaskState[]; projectId: string | null; onBack: () => void }) {
  const { t } = useTranslation()
  const done = tasks.every((task) => task.status !== 'pending')
  return (
    <>
      <PageHeader title={t('wizard.creatingTitle')} description={t('wizard.creatingHint')} />
      <Card>
        <CardBody className="space-y-3">
          {projectId && (
            <div className="flex items-center gap-2 text-sm text-text">
              <CheckCircle2 size={16} className="text-good" /> {t('wizard.projectCreated')}
            </div>
          )}
          <ul className="space-y-2" aria-live="polite">
            {tasks.map((task) => (
              <li key={task.label} className="flex items-start gap-2 text-sm">
                {task.status === 'pending' ? (
                  <Loader2 size={16} className="mt-0.5 animate-spin text-muted" />
                ) : task.status === 'ok' ? (
                  <CheckCircle2 size={16} className="mt-0.5 text-good" />
                ) : (
                  <XCircle size={16} className="mt-0.5 text-critical" />
                )}
                <span>
                  <span className="font-mono text-xs text-text">{task.label}</span>
                  {task.detail && <span className="block text-text-2">{task.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
          {done && (
            <div className="flex gap-2 border-t border-border pt-4">
              {projectId ? (
                <Link to="/projects/$projectId" params={{ projectId }}>
                  <Button variant="primary">{t('wizard.openProject')}</Button>
                </Link>
              ) : (
                <Button onClick={onBack}>{t('common.back')}</Button>
              )}
            </div>
          )}
        </CardBody>
      </Card>
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

function ChoiceCard({
  selected,
  onClick,
  title,
  body,
}: {
  selected: boolean
  onClick: () => void
  title: string
  body: string
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={selected}
      className={cn(
        'rounded-lg border p-4 text-left',
        selected ? 'border-series-1 ring-1 ring-series-1' : 'border-border hover:bg-surface-2',
      )}
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
