import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, FileArchive, FileText, GitBranch, Image, PenTool, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatCompact, formatDateTime, formatUsd } from '@/lib/format'
import type { Project } from '@/mocks/types'
import { Badge, Button, Card, CardBody, CardHeader, Progress, StatTile, Table, Td, Th } from '@/components/ui/primitives'
import { PhaseStatusIcon } from '@/components/ui/status'
import type { ProjectTab } from '../ProjectWorkspace'

export function OverviewTab({ project, onOpen }: { project: Project; onOpen: (tab: ProjectTab) => void }) {
  const { t } = useTranslation()
  const current = project.phases.find((p) => p.status !== 'done')
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={t('overview.pipeline')} subtitle={t('overview.pipelineHint')} />
        <CardBody>
          <ol className="flex gap-2 overflow-x-auto pb-2">
            {project.phases.map((phase, i) => (
              <li key={phase.key} className="flex items-center gap-2">
                <div
                  className={cn(
                    'min-w-32 rounded-md border px-3 py-2',
                    phase.status === 'waiting' && 'border-warning bg-warning/8',
                    phase.status === 'running' && 'border-info bg-info/8',
                    phase.status === 'done' && 'border-border',
                    phase.status === 'pending' && 'border-dashed border-border',
                  )}
                >
                  <div className="flex items-center gap-1.5 text-xs text-muted">
                    <PhaseStatusIcon status={phase.status} size={12} />
                    {t(`phaseStatus.${phase.status}`)}
                    {phase.gate && <Badge className="ml-auto">{phase.gate}</Badge>}
                  </div>
                  <div className="mt-1 text-sm font-medium whitespace-nowrap text-text">{t(`phases.${phase.key}`)}</div>
                </div>
                {i < project.phases.length - 1 && <ArrowRight size={14} className="shrink-0 text-muted" />}
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('overview.progress')} value={`${project.progress}%`} hint={<Progress value={project.progress} />} />
        <StatTile label={t('overview.rules')} value={`${project.rules.approved} / ${project.rules.total}`} hint={t('overview.rulesHint', { verified: project.rules.verified })} />
        <StatTile label={t('overview.openQuestions')} value={project.openQuestions} />
        <StatTile label={t('overview.tokens')} value={formatCompact(project.tokens)} hint={formatUsd(project.costUsd)} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('overview.nextSteps')} />
          <CardBody className="space-y-3 text-sm">
            {current?.status === 'waiting' && (
              <NextStep text={t('overview.gateWaiting', { gate: current.gate, phase: t(`phases.${current.key}`) })} action={t('overview.review')} onClick={() => onOpen(current.key === 'ui' ? 'uiDesign' : 'specification')} />
            )}
            {project.openQuestions > 0 && <NextStep text={t('overview.answerQuestions', { count: project.openQuestions })} action={t('overview.open')} onClick={() => onOpen('specification')} />}
            <NextStep text={t('overview.checkRuns')} action={t('overview.open')} onClick={() => onOpen('runs')} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('overview.stack')} />
          <CardBody>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted">{t('overview.source')}</dt>
                <dd className="text-text">{project.sources.join(', ')}</dd>
              </div>
              {(Object.keys(project.target) as (keyof Project['target'])[]).map((k) => (
                <div key={k}>
                  <dt className="text-xs text-muted">{t(`target.${k}`)}</dt>
                  <dd className="text-text">{project.target[k]}</dd>
                </div>
              ))}
              <div>
                <dt className="text-xs text-muted">{t('wizard.artifactLanguage')}</dt>
                <dd className="text-text">{project.artifactLanguage === 'en' ? 'English' : 'Español'}</dd>
              </div>
            </dl>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function NextStep({ text, action, onClick }: { text: string; action: string; onClick: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border p-3">
      <span className="flex-1 text-text-2">{text}</span>
      <Button size="sm" onClick={onClick}>
        {action}
      </Button>
    </div>
  )
}

const inputs = {
  modernization: [
    { name: 'carddemo-cics (main)', kind: 'git', size: '1,240 files', version: 'a41f9c2', at: '2026-09-18T14:00:00Z', status: 'scanned' },
    { name: 'db2-ddl.zip', kind: 'zip', size: '2.1 MB', version: 'v1', at: '2026-09-18T14:05:00Z', status: 'scanned' },
    { name: 'golden-master-traces-2026-09.zip', kind: 'zip', size: '48 MB', version: 'v2', at: '2026-09-25T10:30:00Z', status: 'quarantined' },
  ],
  newFeature: [
    { name: 'ONB-101 … ONB-142 (Jira)', kind: 'doc', size: '42 stories', version: 'sync 09-27', at: '2026-09-27T20:00:00Z', status: 'scanned' },
    { name: 'onboarding.fig', kind: 'figma', size: '8 frames', version: 'v14', at: '2026-09-27T21:05:00Z', status: 'scanned' },
    { name: 'user-manual-v3.pdf', kind: 'doc', size: '36 pages', version: 'v3', at: '2026-09-26T09:00:00Z', status: 'scanned' },
    { name: 'current-onboarding-screens.png', kind: 'image', size: '6 images', version: 'v1', at: '2026-09-26T09:10:00Z', status: 'scanned' },
  ],
}

const kindIcon = { git: GitBranch, zip: FileArchive, doc: FileText, figma: PenTool, image: Image }

export function InputsTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader
        title={t('inputs.title')}
        subtitle={t('inputs.subtitle')}
        action={
          <Button size="sm" variant="primary">
            <Upload size={14} /> {t('inputs.add')}
          </Button>
        }
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('inputs.name')}</Th>
            <Th>{t('inputs.size')}</Th>
            <Th>{t('inputs.version')}</Th>
            <Th>{t('inputs.added')}</Th>
            <Th>{t('inputs.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {inputs[project.flow].map((input) => {
            const Icon = kindIcon[input.kind as keyof typeof kindIcon]
            return (
              <tr key={input.name}>
                <Td>
                  <span className="flex items-center gap-2 text-text">
                    <Icon size={16} className="text-muted" /> {input.name}
                  </span>
                </Td>
                <Td>{input.size}</Td>
                <Td className="font-mono text-xs">{input.version}</Td>
                <Td>{formatDateTime(input.at)}</Td>
                <Td>
                  <Badge tone={input.status === 'scanned' ? 'good' : 'warning'}>{t(`inputs.statuses.${input.status}`)}</Badge>
                </Td>
              </tr>
            )
          })}
        </tbody>
      </Table>
      <CardBody>
        <p className="text-xs text-muted">{t('inputs.securityNote')}</p>
      </CardBody>
    </Card>
  )
}

// Small, fixed layout of the legacy graph. The real view renders the Neo4j graph (Cytoscape/Sigma).
const graphNodes = [
  { id: 'CAUP', label: 'CAUP (txn)', type: 'transaction', domain: 0, x: 80, y: 60 },
  { id: 'CCUP', label: 'CCUP (txn)', type: 'transaction', domain: 1, x: 80, y: 200 },
  { id: 'CAVW', label: 'CAVW (txn)', type: 'transaction', domain: 2, x: 80, y: 330 },
  { id: 'COACTUPC', label: 'COACTUPC', type: 'program', domain: 0, x: 280, y: 60 },
  { id: 'COCRDUPC', label: 'COCRDUPC', type: 'program', domain: 1, x: 280, y: 200 },
  { id: 'COACTVWC', label: 'COACTVWC', type: 'program', domain: 2, x: 280, y: 330 },
  { id: 'COACTUP', label: 'COACTUP (map)', type: 'map', domain: 0, x: 480, y: 30 },
  { id: 'COCRDUP', label: 'COCRDUP (map)', type: 'map', domain: 1, x: 480, y: 170 },
  { id: 'CVACT01Y', label: 'CVACT01Y (copybook)', type: 'copybook', domain: 0, x: 480, y: 110 },
  { id: 'ACCTDAT', label: 'ACCTDAT (VSAM)', type: 'file', domain: 0, x: 680, y: 150 },
  { id: 'CARDDAT', label: 'CARDDAT (VSAM)', type: 'file', domain: 1, x: 680, y: 260 },
]
const graphEdges: [string, string, string][] = [
  ['CAUP', 'COACTUPC', 'STARTS'],
  ['CCUP', 'COCRDUPC', 'STARTS'],
  ['CAVW', 'COACTVWC', 'STARTS'],
  ['COACTUPC', 'COACTUP', 'USES_MAP'],
  ['COACTUPC', 'CVACT01Y', 'COPIES'],
  ['COCRDUPC', 'COCRDUP', 'USES_MAP'],
  ['COACTUPC', 'ACCTDAT', 'WRITES'],
  ['COCRDUPC', 'CARDDAT', 'WRITES'],
  ['COCRDUPC', 'ACCTDAT', 'READS'],
  ['COACTVWC', 'ACCTDAT', 'READS'],
  ['COACTVWC', 'CARDDAT', 'READS'],
]
const domainNames = ['Accounts', 'Cards', 'Account view']
const domainColor = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']

export function InventoryTab() {
  const { t } = useTranslation()
  const [hover, setHover] = useState<string | null>(null)
  const node = graphNodes.find((n) => n.id === hover)
  const pos = (id: string) => graphNodes.find((n) => n.id === id)!

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ['programs', 44],
          ['copybooks', 62],
          ['maps', 21],
          ['transactions', 19],
          ['files', 14],
        ].map(([k, v]) => (
          <StatTile key={k} label={t(`inventory.${k}`)} value={v} />
        ))}
      </div>
      <Card>
        <CardHeader title={t('inventory.map')} subtitle={t('inventory.mapHint')} />
        <CardBody>
          <div className="mb-3 flex flex-wrap gap-4 text-xs text-text-2" aria-label={t('inventory.legend')}>
            {domainNames.map((d, i) => (
              <span key={d} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: domainColor[i] }} /> {d}
              </span>
            ))}
          </div>
          <div className="relative overflow-x-auto">
            <svg viewBox="0 0 800 380" className="min-w-[640px]" role="img" aria-label={t('inventory.map')}>
              {graphEdges.map(([a, b, label]) => {
                const from = pos(a)
                const to = pos(b)
                const active = hover === a || hover === b
                return (
                  <g key={a + b}>
                    <line x1={from.x + 60} y1={from.y} x2={to.x - 60} y2={to.y} stroke={active ? 'var(--text-2)' : 'var(--axis)'} strokeWidth={active ? 2 : 1} />
                    {active && (
                      <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 6} fontSize={10} textAnchor="middle" fill="var(--text-muted)">
                        {label}
                      </text>
                    )}
                  </g>
                )
              })}
              {graphNodes.map((n) => (
                <g key={n.id} onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} className="cursor-pointer">
                  <rect x={n.x - 60} y={n.y - 16} width={120} height={32} rx={n.type === 'transaction' ? 16 : 6} fill="var(--surface)" stroke={domainColor[n.domain]} strokeWidth={hover === n.id ? 3 : 2} />
                  <text x={n.x} y={n.y} dominantBaseline="middle" textAnchor="middle" fontSize={11} fill="var(--text)">
                    {n.label}
                  </text>
                </g>
              ))}
            </svg>
          </div>
          <p className="mt-3 min-h-5 text-sm text-text-2">
            {node ? t('inventory.nodeDetail', { name: node.id, type: t(`inventory.types.${node.type}`), domain: domainNames[node.domain] }) : t('inventory.hoverHint')}
          </p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('inventory.impact')} subtitle={t('inventory.impactHint')} />
        <CardBody className="flex flex-wrap gap-2">
          {['impactCopybook', 'impactDomain', 'impactOrder', 'impactOrphans'].map((q) => (
            <Button key={q} size="sm">
              {t(`inventory.${q}`)}
            </Button>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}
