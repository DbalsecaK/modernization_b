import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TenantAdapters } from './AdapterStudio'
import { can, useMe } from '@/api/session'
import { useTab } from '@/lib/useTab'
import { useCatalog, useSkill, type Catalog, type CatalogSkill } from '@/api/projects'
import { Badge, Card, CardBody, CardHeader, PageHeader, Select, Table, Tabs, Td, Th } from '@/components/ui/primitives'
import { Drawer } from '@/components/ui/overlay'
import { LevelBadge } from '@/components/ui/status'
import { Notice } from '@/features/projects/NewProjectWizard'
import { AgentCard, agentName } from './AgentCard'

const TABS = ['agents', 'skills', 'adapters', 'packs', 'compatibility', 'templates'] as const
const GROUPS = ['analysis', 'design', 'build', 'quality', 'control'] as const
const SKILL_TYPES = ['source', 'target', 'conversion', 'crossCutting'] as const

export function CatalogPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useTab(TABS, 'agents')
  const catalog = useCatalog()

  return (
    <>
      <PageHeader title={t('catalog.title')} description={t('catalog.description')} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`catalog.tabs.${id}`) }))} value={tab} onChange={setTab} />
      {catalog.data && (
        <>
          {tab === 'agents' && <Agents catalog={catalog.data} />}
          {tab === 'skills' && <Skills catalog={catalog.data} />}
          {tab === 'adapters' && <Adapters catalog={catalog.data} />}
          {tab === 'packs' && <Packs catalog={catalog.data} />}
          {tab === 'compatibility' && <Compatibility catalog={catalog.data} />}
          {tab === 'templates' && <Templates catalog={catalog.data} />}
        </>
      )}
    </>
  )
}

function Agents({ catalog }: { catalog: Catalog }) {
  const { t } = useTranslation()
  const [group, setGroup] = useState<'all' | (typeof GROUPS)[number]>('all')
  return (
    <div className="space-y-4">
      <Select
        className="max-w-xs"
        value={group}
        onChange={(e) => setGroup(e.target.value as typeof group)}
        aria-label={t('catalog.group')}
      >
        <option value="all">{t('catalog.allGroups')}</option>
        {GROUPS.map((g) => (
          <option key={g} value={g}>
            {t(`agentGroups.${g}`)}
          </option>
        ))}
      </Select>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {catalog.agents
          .filter((a) => group === 'all' || a.group === group)
          .map((a) => (
            <AgentCard key={a.key} agent={a} />
          ))}
      </div>
      <Notice tone="info">{t('catalog.customLater')}</Notice>
    </div>
  )
}

function Skills({ catalog }: { catalog: Catalog }) {
  const { t, i18n } = useTranslation()
  const [skillType, setSkillType] = useState<'all' | (typeof SKILL_TYPES)[number]>('all')
  const [open, setOpen] = useState<CatalogSkill | null>(null)
  const agentLabel = (key: string) => {
    const agent = catalog.agents.find((a) => a.key === key)
    return agent ? agentName(agent, i18n.language) : key
  }
  const title = (key: string) => catalog.skills.find((s) => s.key === key)?.title ?? key
  const skills = catalog.skills.filter((s) => skillType === 'all' || s.type === skillType)
  return (
    <Card>
      <SkillDrawer skill={open} onClose={() => setOpen(null)} />
      <CardHeader
        title={t('catalog.skillsTitle', { count: skills.length })}
        action={
          <Select
            className="h-9 w-48"
            value={skillType}
            onChange={(e) => setSkillType(e.target.value as typeof skillType)}
            aria-label={t('catalog.skillType')}
          >
            <option value="all">{t('catalog.allTypes')}</option>
            {SKILL_TYPES.map((s) => (
              <option key={s} value={s}>
                {t(`skillTypes.${s}`)}
              </option>
            ))}
          </Select>
        }
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('catalog.skill')}</Th>
            <Th>{t('catalog.type')}</Th>
            <Th>{t('catalog.appliesTo')}</Th>
            <Th>{t('catalog.eval')}</Th>
            <Th>{t('catalog.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {skills.map((s) => (
            <tr key={s.key}>
              <Td>
                <button
                  type="button"
                  className="text-left font-medium text-text hover:underline"
                  onClick={() => setOpen(s)}
                >
                  {s.title}
                </button>
                <div className="text-xs text-muted">{s.description}</div>
                {s.conflicts.length > 0 && (
                  <div className="mt-1 text-xs text-critical-ink">
                    {t('catalog.conflictsWith', { names: s.conflicts.map(title).join(', ') })}
                  </div>
                )}
              </Td>
              <Td>
                <Badge>{t(`skillTypes.${s.type}`)}</Badge>
              </Td>
              <Td className="text-xs">
                {s.agents.map(agentLabel).join(', ')}
                {s.technologies.length > 0 && <div className="mt-1 text-muted">{s.technologies.join(', ')}</div>}
              </Td>
              <Td className="tabular">{s.evalScore == null ? '—' : `${Math.round(s.evalScore * 100)}%`}</Td>
              <Td>
                <Badge tone={s.status === 'published' ? 'good' : 'info'}>{t(`skillStatus.${s.status}`)}</Badge>
                <div className="mt-1 text-xs text-muted">v{s.version}</div>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function SkillDrawer({ skill, onClose }: { skill: CatalogSkill | null; onClose: () => void }) {
  const { t } = useTranslation()
  const detail = useSkill(skill?.key ?? null)
  return (
    <Drawer
      open={!!skill}
      onClose={onClose}
      wide
      title={skill?.title ?? ''}
      description={skill ? t('catalog.skillFile', { key: skill.key, version: skill.version }) : undefined}
    >
      <pre className="rounded-md bg-surface-2 p-4 text-sm whitespace-pre-wrap text-text">
        {detail.data?.content ?? ''}
      </pre>
    </Drawer>
  )
}

function Adapters({ catalog }: { catalog: Catalog }) {
  const { t } = useTranslation()
  const me = useMe()
  return (
    <Card>
      <CardHeader title={t('catalog.adaptersTitle')} subtitle={t('catalog.adaptersHint')} />
      {can(me, 'models.configure') && (
        <CardBody>
          <TenantAdapters />
        </CardBody>
      )}
      <Table>
        <thead>
          <tr>
            <Th>{t('catalog.adapter')}</Th>
            <Th>{t('catalog.level')}</Th>
            <Th>{t('catalog.validationMode')}</Th>
            <Th>{t('catalog.version')}</Th>
          </tr>
        </thead>
        <tbody>
          {catalog.adapters.map((a) => (
            <tr key={a.key}>
              <Td className="text-text">
                {a.name}
                <div className="text-xs text-muted">
                  {catalog.sources
                    .filter((s) => s.adapter === a.key)
                    .map((s) => s.name)
                    .join(', ')}
                </div>
              </Td>
              <Td>
                <LevelBadge level={a.level as 'certified' | 'assisted' | 'experimental'} />
              </Td>
              <Td>{t(`catalog.validation.${a.validation}`)}</Td>
              <Td>{a.version}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function Packs({ catalog }: { catalog: Catalog }) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {(['architecture', 'backend', 'frontend', 'database', 'cloud'] as const).map((axis) => (
        <Card key={axis}>
          <CardHeader title={t(`target.${axis}`)} />
          <CardBody className="space-y-2">
            {catalog.targets
              .filter((p) => p.axis === axis)
              .map((p) => (
                <div key={p.key} className="flex items-center gap-3 text-sm">
                  <span className="flex-1 text-text">{p.name}</span>
                  {p.wave != null && <span className="text-xs text-muted">{t('catalog.wave', { wave: p.wave })}</span>}
                  {p.level && <LevelBadge level={p.level as 'certified' | 'assisted' | 'experimental'} />}
                  {(p.versions ?? []).length > 0 && (
                    <div className="mt-1 text-xs text-muted">
                      {t('catalog.versions')}:{' '}
                      {(p.versions ?? [])
                        .map((v) => `${v.name}${v.level === 'planned' ? ` (${t('catalog.planned')})` : ''}`)
                        .join(' · ')}
                    </div>
                  )}
                </div>
              ))}
          </CardBody>
        </Card>
      ))}
    </div>
  )
}

function Compatibility({ catalog }: { catalog: Catalog }) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('catalog.compatTitle')} subtitle={t('catalog.compatHint')} />
      <CardBody className="space-y-3">
        {catalog.compatibilityRules.map((r) => (
          <div key={r.key} className="rounded-md border border-border p-3 text-sm text-text-2">
            <span className="mr-2 font-mono text-xs text-muted">{r.key}</span>
            {t(`compat.${r.key}`, { defaultValue: r.message })}
          </div>
        ))}
      </CardBody>
    </Card>
  )
}

function Templates({ catalog }: { catalog: Catalog }) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      {catalog.pipelineTemplates.map((tpl) => (
        <Card key={tpl.key}>
          <CardHeader
            title={t(`templates.${tpl.key}.name`, { defaultValue: tpl.name })}
            subtitle={t(`templates.${tpl.key}.body`, { defaultValue: tpl.description })}
          />
          <CardBody className="flex flex-wrap gap-2">
            {tpl.requiredGates.map((g) => (
              <Badge key={g} tone="brand">
                {t('catalog.gateRequired', { gate: g })}
              </Badge>
            ))}
            <Badge>{t(`hitl.levels.${tpl.defaultAutonomy}.name`)}</Badge>
          </CardBody>
        </Card>
      ))}
    </div>
  )
}
