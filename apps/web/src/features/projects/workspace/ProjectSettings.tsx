import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Lock, Pencil } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { ApiError } from '@/api/client'
import {
  hasProjectPermission,
  useCatalog,
  useChangeConfig,
  useComposition,
  useConfigVersions,
  useUpdateProject,
  type Catalog,
  type ProjectDetail,
} from '@/api/projects'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  Select,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { Drawer, Textarea, toast } from '@/components/ui/overlay'
import { agentName } from '@/features/catalog/AgentCard'
import { Notice } from '../NewProjectWizard'

type Autonomy = 'guided' | 'balanced' | 'autonomous'

export function ProjectSettings({ project }: { project: ProjectDetail }) {
  const catalog = useCatalog()
  if (!catalog.data) return null
  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <General project={project} />
        <Composition project={project} catalog={catalog.data} />
      </div>
      <Versions project={project} />
    </div>
  )
}

function General({ project }: { project: ProjectDetail }) {
  const { t } = useTranslation()
  const update = useUpdateProject(project.id)
  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description)
  const [language, setLanguage] = useState(project.artifactLanguage)
  const editable = hasProjectPermission(project, 'configure')

  async function save(body: Parameters<typeof update.mutateAsync>[0], message: string) {
    try {
      await update.mutateAsync(body)
      toast(message)
    } catch (error) {
      toast(
        error instanceof ApiError
          ? t(`inputs.rejections.${error.code}`, { defaultValue: error.message })
          : String(error),
      )
    }
  }

  return (
    <Card>
      <CardHeader title={t('projectSettings.general')} />
      <CardBody className="space-y-4">
        <Field label={t('wizard.projectName')}>
          <Input value={name} disabled={!editable} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t('wizard.projectDescription')}>
          <Textarea
            rows={2}
            value={description}
            disabled={!editable}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        <Field label={t('wizard.artifactLanguage')}>
          <Select value={language} disabled={!editable} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')}>
            <option value="en">English</option>
            <option value="es">Español</option>
          </Select>
        </Field>
        {editable && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              disabled={!name.trim() || update.isPending}
              onClick={() =>
                void save({ name: name.trim(), description, artifactLanguage: language }, t('projectSettings.saved'))
              }
            >
              {t('common.save')}
            </Button>
            <Button
              variant="ghost"
              onClick={() =>
                void save(
                  { status: project.status === 'active' ? 'archived' : 'active' },
                  project.status === 'active' ? t('projectSettings.archived') : t('projectSettings.restored'),
                )
              }
            >
              {project.status === 'active' ? t('projectSettings.archive') : t('projectSettings.restore')}
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function Composition({ project, catalog }: { project: ProjectDetail; catalog: Catalog }) {
  const { t, i18n } = useTranslation()
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState(0)
  const config = project.config
  const canEdit = hasProjectPermission(project, 'configure')
  const template = catalog.pipelineTemplates.find((x) => x.key === config?.pipelineTemplate)
  return (
    <Card>
      {config && (
        <ConfigDrawer key={opened} project={project} catalog={catalog} open={open} onClose={() => setOpen(false)} />
      )}
      <CardHeader
        title={t('projectSettings.teamAndAgents')}
        action={
          canEdit &&
          config && (
            <Button
              size="sm"
              onClick={() => {
                setOpened((n) => n + 1)
                setOpen(true)
              }}
            >
              <Pencil size={14} /> {t('projectSettings.editConfig')}
            </Button>
          )
        }
      />
      <CardBody className="space-y-3 text-sm">
        {!config ? (
          <p className="text-muted">{t('projectSettings.noConfig')}</p>
        ) : (
          <>
            <SettingRow
              label={t('projectSettings.pipeline')}
              value={
                template
                  ? t(`templates.${template.key}.name`, { defaultValue: template.name })
                  : config.pipelineTemplate
              }
            />
            <SettingRow label={t('hitl.autonomyTitle')} value={t(`hitl.levels.${config.autonomy}.name`)} />
            <SettingRow label={t('wizard.maxIterations')} value={String(config.maxIterations)} />
            <SettingRow label={t('hitl.sampling')} value={`${config.samplingPct}%`} />
            <SettingRow label={t('projectSettings.versions')} value={t('projectSettings.pinned')} />
            <div>
              <div className="mb-1 text-xs text-muted">{t('projectSettings.agents')}</div>
              <div className="flex flex-wrap gap-1.5">
                {project.agents.map((a) => {
                  const agent = catalog.agents.find((x) => x.key === a.key)
                  return (
                    <Badge key={a.key} tone={agent?.mandatory ? 'brand' : 'neutral'}>
                      {agent ? agentName(agent, i18n.language) : a.key} v{a.version}
                    </Badge>
                  )
                })}
              </div>
            </div>
            <div>
              <div className="mb-1 text-xs text-muted">{t('projectSettings.skills')}</div>
              <div className="flex flex-wrap gap-1.5">
                {project.skills.map((s) => (
                  <Badge key={s.key} tone={s.recommended ? 'accent' : 'neutral'}>
                    {catalog.skills.find((x) => x.key === s.key)?.title ?? s.key} v{s.version}
                  </Badge>
                ))}
              </div>
            </div>
            <p className="pt-2 text-xs text-muted">{t('projectSettings.changeNote')}</p>
          </>
        )}
      </CardBody>
    </Card>
  )
}

function ConfigDrawer({
  project,
  catalog,
  open,
  onClose,
}: {
  project: ProjectDetail
  catalog: Catalog
  open: boolean
  onClose: () => void
}) {
  const { t, i18n } = useTranslation()
  const config = project.config!
  const change = useChangeConfig(project.id)
  const canAgents = hasProjectPermission(project, 'selectAgents')
  const canSkills = hasProjectPermission(project, 'selectSkills')
  const [agents, setAgents] = useState(project.agents.map((a) => a.key))
  const [skills, setSkills] = useState(project.skills.map((s) => s.key))
  const [template, setTemplate] = useState(config.pipelineTemplate)
  const [autonomy, setAutonomy] = useState<Autonomy>(config.autonomy)
  const [maxIterations, setMaxIterations] = useState(config.maxIterations)
  const [sampling, setSampling] = useState(config.samplingPct)
  const [note, setNote] = useState('')
  const composition = useComposition({
    flow: project.flow,
    sources: config.sources,
    target: config.target,
    agents,
    skills,
    projectId: project.id,
  })
  const problems = composition.data?.problems ?? []

  async function save() {
    try {
      await change.mutateAsync({
        sources: config.sources,
        target: config.target,
        agents,
        skills,
        pipelineTemplate: template,
        autonomy,
        maxIterations,
        samplingPct: sampling,
        changeNote: note || null,
      })
      toast(t('projectSettings.configSaved'))
      onClose()
    } catch (error) {
      toast(
        error instanceof ApiError
          ? t(`wizard.problems.${error.code}`, { defaultValue: error.message, subject: '' })
          : String(error),
      )
    }
  }

  const toggle = (list: string[], set: (v: string[]) => void, key: string) =>
    set(list.includes(key) ? list.filter((x) => x !== key) : [...list, key])

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('projectSettings.editConfig')}
      description={t('projectSettings.changeNote')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={problems.length > 0 || change.isPending} onClick={() => void save()}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('projectSettings.pipeline')}>
          <Select value={template} onChange={(e) => setTemplate(e.target.value)}>
            {catalog.pipelineTemplates.map((tpl) => (
              <option key={tpl.key} value={tpl.key}>
                {t(`templates.${tpl.key}.name`, { defaultValue: tpl.name })}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('hitl.autonomyTitle')}>
          <Select value={autonomy} onChange={(e) => setAutonomy(e.target.value as Autonomy)}>
            {(['guided', 'balanced', 'autonomous'] as const).map((a) => (
              <option key={a} value={a}>
                {t(`hitl.levels.${a}.name`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('wizard.maxIterations')}>
          <Input
            type="number"
            min={1}
            max={10}
            value={maxIterations}
            onChange={(e) => setMaxIterations(Number(e.target.value))}
          />
        </Field>
        <Field label={t('hitl.sampling')}>
          <Input
            type="number"
            min={0}
            max={100}
            value={sampling}
            onChange={(e) => setSampling(Number(e.target.value))}
          />
        </Field>
      </div>

      <div>
        <div className="mb-2 text-sm font-medium text-text">{t('projectSettings.agents')}</div>
        {!canAgents && <Notice tone="info">{t('projectSettings.needsAgentsSelect')}</Notice>}
        <div className="grid gap-2 sm:grid-cols-2">
          {catalog.agents.map((a) => {
            const on = agents.includes(a.key)
            const locked = a.mandatory || !canAgents
            return (
              <button
                key={a.key}
                type="button"
                disabled={locked}
                onClick={() => {
                  toggle(agents, setAgents, a.key)
                }}
                aria-pressed={on}
                className={cn(
                  'flex items-center gap-2 rounded-md border px-3 py-2 text-left text-sm',
                  on ? 'border-series-1 bg-series-1/5' : 'border-border',
                  locked && 'opacity-70',
                )}
              >
                <span
                  className={cn(
                    'flex h-4 w-4 items-center justify-center rounded border',
                    on ? 'border-series-1 bg-series-1 text-white' : 'border-border',
                  )}
                >
                  {a.mandatory ? <Lock size={10} /> : on ? <Check size={10} /> : null}
                </span>
                {agentName(a, i18n.language)}
              </button>
            )
          })}
        </div>
      </div>

      <div>
        <div className="mb-2 text-sm font-medium text-text">{t('projectSettings.skills')}</div>
        {!canSkills && <Notice tone="info">{t('projectSettings.needsSkillsSelect')}</Notice>}
        <div className="grid gap-2 sm:grid-cols-2">
          {catalog.skills
            .filter((s) => s.agents.some((a) => agents.includes(a)))
            .map((s) => {
              const on = skills.includes(s.key)
              return (
                <button
                  key={s.key}
                  type="button"
                  disabled={!canSkills}
                  onClick={() => toggle(skills, setSkills, s.key)}
                  aria-pressed={on}
                  className={cn(
                    'flex items-center gap-2 rounded-md border px-3 py-2 text-left text-sm',
                    on ? 'border-series-1 bg-series-1/5' : 'border-border',
                    !canSkills && 'opacity-70',
                  )}
                >
                  <span
                    className={cn(
                      'flex h-4 w-4 items-center justify-center rounded border',
                      on ? 'border-series-1 bg-series-1 text-white' : 'border-border',
                    )}
                  >
                    {on && <Check size={10} />}
                  </span>
                  {s.title}
                </button>
              )
            })}
        </div>
      </div>

      <Field label={t('projectSettings.changeNoteLabel')}>
        <Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
      </Field>
      {(composition.data?.warnings ?? []).map((w) => (
        <Notice key={w} tone="warning">
          {t(`compat.${w}`)}
        </Notice>
      ))}
      {(composition.data?.missingSkills ?? []).map((m) => (
        <Notice key={m.skill} tone="warning">
          {t('wizard.skillMissing', {
            source: catalog.sources.find((s) => s.key === m.source)?.name ?? m.source,
            skill: catalog.skills.find((s) => s.key === m.skill)?.title ?? m.skill,
          })}
        </Notice>
      ))}
      {problems.map((p) => (
        <Notice key={`${p.code}-${p.subject}`} tone="critical">
          {t(`wizard.problems.${p.code}`, {
            defaultValue: p.code,
            subject: p.code.startsWith('uncovered') ? t(`phases.${p.subject}`) : (p.subject ?? ''),
          })}
        </Notice>
      ))}
    </Drawer>
  )
}

function Versions({ project }: { project: ProjectDetail }) {
  const { t } = useTranslation()
  const versions = useConfigVersions(project.id)
  return (
    <Card>
      <CardHeader title={t('projectSettings.history')} subtitle={t('projectSettings.historyHint')} />
      <Table>
        <thead>
          <tr>
            <Th>{t('inputs.version')}</Th>
            <Th>{t('projectSettings.agents')}</Th>
            <Th>{t('projectSettings.skills')}</Th>
            <Th>{t('projectSettings.note')}</Th>
            <Th>{t('inputs.added')}</Th>
          </tr>
        </thead>
        <tbody>
          {(versions.data ?? []).map((v) => (
            <tr key={v.version}>
              <Td className="font-mono text-xs">v{v.version}</Td>
              <Td>{v.agents}</Td>
              <Td>{v.skills}</Td>
              <Td className="text-xs">{v.changeNote ?? '—'}</Td>
              <Td className="text-xs">{formatDateTime(v.createdAt)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-border pb-2 last:border-0">
      <span className="text-muted">{label}</span>
      <span className="text-right text-text">{value}</span>
    </div>
  )
}
