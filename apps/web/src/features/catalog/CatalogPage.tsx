import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { agents, skills } from '@/mocks/data'
import type { AgentGroup, SkillType, SupportLevel } from '@/mocks/types'
import { Badge, Button, Card, CardBody, CardHeader, PageHeader, Select, Table, Tabs, Td, Th } from '@/components/ui/primitives'
import { LevelBadge } from '@/components/ui/status'
import { AgentCard, agentName } from './AgentCard'

const TABS = ['agents', 'skills', 'adapters', 'packs', 'compatibility', 'templates'] as const

const adapters: { name: string; level: SupportLevel; version: string; validation: string }[] = [
  { name: 'COBOL batch (+ JCL, copybooks, VSAM)', level: 'certified', version: '1.2.0', validation: 'goldenMasterLocal' },
  { name: 'COBOL CICS + BMS maps', level: 'certified', version: '1.1.0', validation: 'traces' },
  { name: 'Sybase ASE stored procedures', level: 'certified', version: '0.9.0', validation: 'goldenMasterLocal' },
  { name: 'ASP.NET WebForms / .NET Framework', level: 'assisted', version: '0.6.0', validation: 'windowsRunner' },
  { name: 'PL/SQL (Oracle)', level: 'experimental', version: '0.2.0', validation: 'goldenMasterLocal' },
]

const packs: { axis: string; name: string; level: SupportLevel; wave: 1 | 2 | 3 }[] = [
  { axis: 'backend', name: 'Java Spring Boot', level: 'certified', wave: 1 },
  { axis: 'backend', name: '.NET 10', level: 'certified', wave: 1 },
  { axis: 'backend', name: 'Java Quarkus', level: 'assisted', wave: 2 },
  { axis: 'backend', name: 'Next.js', level: 'assisted', wave: 2 },
  { axis: 'backend', name: 'Go', level: 'experimental', wave: 3 },
  { axis: 'frontend', name: 'Angular', level: 'certified', wave: 1 },
  { axis: 'frontend', name: 'React', level: 'certified', wave: 1 },
  { axis: 'database', name: 'PostgreSQL', level: 'certified', wave: 1 },
  { axis: 'database', name: 'SQL Server', level: 'certified', wave: 1 },
  { axis: 'database', name: 'Oracle', level: 'certified', wave: 1 },
  { axis: 'database', name: 'MySQL', level: 'assisted', wave: 2 },
  { axis: 'database', name: 'MongoDB', level: 'experimental', wave: 3 },
  { axis: 'cloud', name: 'AWS', level: 'certified', wave: 1 },
  { axis: 'cloud', name: 'Azure', level: 'certified', wave: 1 },
  { axis: 'cloud', name: 'GCP', level: 'assisted', wave: 2 },
]

const compatRules = ['mongoModeling', 'serverlessBatch', 'serverlessCics', 'nextBff', 'goConventions', 'upliftOption'] as const

export function CatalogPage() {
  const { t, i18n } = useTranslation()
  const [tab, setTab] = useTab(TABS, 'agents')
  const [group, setGroup] = useState<'all' | AgentGroup>('all')
  const [skillType, setSkillType] = useState<'all' | SkillType>('all')

  return (
    <>
      <PageHeader
        title={t('catalog.title')}
        description={t('catalog.description')}
        actions={
          (tab === 'agents' || tab === 'skills') && (
            <Button variant="primary">
              <Plus size={16} /> {t(tab === 'agents' ? 'catalog.newAgent' : 'catalog.newSkill')}
            </Button>
          )
        }
      />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`catalog.tabs.${id}`) }))} value={tab} onChange={setTab} />

      {tab === 'agents' && (
        <>
          <Select className="mb-4 max-w-xs" value={group} onChange={(e) => setGroup(e.target.value as typeof group)} aria-label={t('catalog.group')}>
            <option value="all">{t('catalog.allGroups')}</option>
            {(['analysis', 'design', 'build', 'quality', 'control'] as const).map((g) => (
              <option key={g} value={g}>
                {t(`agentGroups.${g}`)}
              </option>
            ))}
          </Select>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {agents
              .filter((a) => group === 'all' || a.group === group)
              .map((a) => (
                <AgentCard key={a.id} agent={a} />
              ))}
          </div>
        </>
      )}

      {tab === 'skills' && (
        <Card>
          <CardHeader
            title={t('catalog.skillsTitle', { count: skills.length })}
            action={
              <Select className="h-9 w-48" value={skillType} onChange={(e) => setSkillType(e.target.value as typeof skillType)} aria-label={t('catalog.skillType')}>
                <option value="all">{t('catalog.allTypes')}</option>
                {(['source', 'target', 'conversion', 'crossCutting', 'customer'] as const).map((s) => (
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
              {skills
                .filter((s) => skillType === 'all' || s.type === skillType)
                .map((s) => (
                  <tr key={s.id}>
                    <Td>
                      <div className="font-medium text-text">{s.name}</div>
                      <div className="text-xs text-muted">{s.description}</div>
                      {s.conflictsWith.length > 0 && (
                        <div className="mt-1 text-xs text-critical-ink">
                          {t('catalog.conflictsWith', { names: s.conflictsWith.map((c) => skills.find((x) => x.id === c)?.name).join(', ') })}
                        </div>
                      )}
                    </Td>
                    <Td>
                      <Badge>{t(`skillTypes.${s.type}`)}</Badge>
                    </Td>
                    <Td className="text-xs">{s.appliesTo.map((id) => agentName(agents.find((a) => a.id === id)!, i18n.language)).join(', ')}</Td>
                    <Td className="tabular">{s.evalScore === null ? '—' : `${Math.round(s.evalScore * 100)}%`}</Td>
                    <Td>
                      <Badge tone={s.status === 'published' ? 'good' : 'info'}>{t(`skillStatus.${s.status}`)}</Badge>
                      <div className="mt-1 text-xs text-muted">v{s.version}</div>
                    </Td>
                  </tr>
                ))}
            </tbody>
          </Table>
        </Card>
      )}

      {tab === 'adapters' && (
        <Card>
          <CardHeader title={t('catalog.adaptersTitle')} subtitle={t('catalog.adaptersHint')} />
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
              {adapters.map((a) => (
                <tr key={a.name}>
                  <Td className="text-text">{a.name}</Td>
                  <Td>
                    <LevelBadge level={a.level} />
                  </Td>
                  <Td>{t(`catalog.validation.${a.validation}`)}</Td>
                  <Td>{a.version}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      {tab === 'packs' && (
        <div className="grid gap-6 lg:grid-cols-2">
          {(['backend', 'frontend', 'database', 'cloud'] as const).map((axis) => (
            <Card key={axis}>
              <CardHeader title={t(`target.${axis}`)} />
              <CardBody className="space-y-2">
                {packs
                  .filter((p) => p.axis === axis)
                  .map((p) => (
                    <div key={p.name} className="flex items-center gap-3 text-sm">
                      <span className="flex-1 text-text">{p.name}</span>
                      <span className="text-xs text-muted">{t('catalog.wave', { wave: p.wave })}</span>
                      <LevelBadge level={p.level} />
                    </div>
                  ))}
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {tab === 'compatibility' && (
        <Card>
          <CardHeader title={t('catalog.compatTitle')} subtitle={t('catalog.compatHint')} />
          <CardBody className="space-y-3">
            {compatRules.map((r) => (
              <div key={r} className="rounded-md border border-border p-3 text-sm text-text-2">
                <span className="mr-2 font-mono text-xs text-muted">{r}</span>
                {t(`compat.${r}`)}
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      {tab === 'templates' && (
        <div className="grid gap-6 lg:grid-cols-2">
          {(['bankStandard', 'internalAgile'] as const).map((tpl) => (
            <Card key={tpl}>
              <CardHeader title={t(`templates.${tpl}.name`)} subtitle={t(`templates.${tpl}.body`)} />
              <CardBody className="flex flex-wrap gap-2">
                {(tpl === 'bankStandard' ? ['C1', 'C2', 'C3', 'C4'] : ['C1', 'C4']).map((g) => (
                  <Badge key={g} tone="brand">
                    {t('catalog.gateRequired', { gate: g })}
                  </Badge>
                ))}
                <Badge>{t('catalog.maxIterations', { count: tpl === 'bankStandard' ? 3 : 5 })}</Badge>
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
