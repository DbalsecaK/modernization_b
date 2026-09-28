import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowRight, FileArchive, FileText, GitBranch, Image, PenTool, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatCompact, formatDateTime, formatUsd } from '@/lib/format'
import type { Project } from '@/mocks/types'
import { graphEdges, graphNodes, type GraphNode, type GraphNodeType, type MigrationState } from '@/mocks/data'
import { Badge, Button, Card, CardBody, CardHeader, Progress, StatTile, Table, Td, Th } from '@/components/ui/primitives'
import { PhaseStatusIcon } from '@/components/ui/status'
import type { ProjectTab } from '../ProjectWorkspace'
import { AddInputForm } from '../InputForms'

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
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <AddInputForm open={open} onClose={() => setOpen(false)} flow={project.flow} />
      <CardHeader
        title={t('inputs.title')}
        subtitle={t('inputs.subtitle')}
        action={
          <Button size="sm" variant="primary" onClick={() => setOpen(true)}>
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

// Interactive sample of the knowledge graph (spec section 5). Layered layout: entry points → programs →
// maps and copybooks → data. The real view renders Neo4j results with Cytoscape or Sigma.
const COLUMNS: Record<GraphNodeType, number> = { transaction: 0, job: 0, program: 1, map: 2, copybook: 2, file: 3 }
const domainColor: Record<GraphNode['domain'], string> = { Accounts: 'var(--series-1)', Cards: 'var(--series-2)', Authorizations: 'var(--series-3)' }
const stateColor: Record<MigrationState, string> = { verified: 'var(--good)', generated: 'var(--info)', inProgress: 'var(--warning)', pending: 'var(--text-muted)' }
const TYPES: GraphNodeType[] = ['transaction', 'job', 'program', 'map', 'copybook', 'file']

function layout(nodes: GraphNode[]) {
  const byCol: Record<number, GraphNode[]> = {}
  nodes.forEach((n) => (byCol[COLUMNS[n.type]] ??= []).push(n))
  const pos: Record<string, { x: number; y: number }> = {}
  Object.entries(byCol).forEach(([col, list]) => {
    list.forEach((n, i) => {
      pos[n.id] = { x: 80 + Number(col) * 190, y: 40 + i * 58 }
    })
  })
  return pos
}

export function InventoryTab({ onCompare }: { onCompare: (ruleId: string) => void }) {
  const { t } = useTranslation()
  const [types, setTypes] = useState<GraphNodeType[]>(TYPES)
  const [domain, setDomain] = useState<'all' | GraphNode['domain']>('all')
  const [colorBy, setColorBy] = useState<'domain' | 'state'>('domain')
  const [selected, setSelected] = useState<string | null>('COACTUPC')
  const [impact, setImpact] = useState<string[]>([])

  const nodes = graphNodes.filter((n) => types.includes(n.type) && (domain === 'all' || n.domain === domain))
  const ids = new Set(nodes.map((n) => n.id))
  const edges = graphEdges.filter((e) => ids.has(e.from) && ids.has(e.to))
  const pos = layout(nodes)
  const height = Math.max(...Object.values(pos).map((p) => p.y), 0) + 50
  const node = graphNodes.find((n) => n.id === selected)
  const uses = graphEdges.filter((e) => e.from === selected)
  const usedBy = graphEdges.filter((e) => e.to === selected)
  const color = (n: GraphNode) => (colorBy === 'domain' ? domainColor[n.domain] : stateColor[n.state])

  // Everything that (transitively) depends on the node: what could break if it changes.
  function impactOf(id: string) {
    const out = new Set<string>()
    const walk = (x: string) =>
      graphEdges.filter((e) => e.to === x).forEach((e) => {
        if (!out.has(e.from)) {
          out.add(e.from)
          walk(e.from)
        }
      })
    walk(id)
    return [...out]
  }

  const counts = TYPES.map((ty) => [ty, graphNodes.filter((n) => n.type === ty).length] as const)

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {counts.map(([k, v]) => (
          <StatTile key={k} label={t(`inventory.typesPlural.${k}`)} value={v} />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title={t('inventory.map')} subtitle={t('inventory.mapHint')} />
          <CardBody className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              {TYPES.map((ty) => (
                <button
                  key={ty}
                  onClick={() => setTypes(types.includes(ty) ? types.filter((x) => x !== ty) : [...types, ty])}
                  aria-pressed={types.includes(ty)}
                  className={cn('rounded-full border px-2.5 py-1 text-xs', types.includes(ty) ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-muted')}
                >
                  {t(`inventory.types.${ty}`)}
                </button>
              ))}
              <select className="ml-auto h-8 rounded-md border border-border bg-surface px-2 text-xs text-text" value={domain} onChange={(e) => setDomain(e.target.value as typeof domain)} aria-label={t('inventory.domain')}>
                <option value="all">{t('inventory.allDomains')}</option>
                {Object.keys(domainColor).map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
              <div className="flex rounded-md border border-border p-0.5 text-xs" role="group" aria-label={t('inventory.colorBy')}>
                {(['domain', 'state'] as const).map((c) => (
                  <button key={c} onClick={() => setColorBy(c)} aria-pressed={colorBy === c} className={cn('rounded px-2 py-1', colorBy === c ? 'bg-brand text-brand-contrast' : 'text-muted')}>
                    {t(`inventory.colorModes.${c}`)}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap gap-4 text-xs text-text-2" aria-label={t('inventory.legend')}>
              {colorBy === 'domain'
                ? Object.entries(domainColor).map(([d, c]) => (
                    <span key={d} className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} /> {d}
                    </span>
                  ))
                : (Object.keys(stateColor) as MigrationState[]).map((st) => (
                    <span key={st} className="inline-flex items-center gap-1.5">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: stateColor[st] }} /> {t(`inventory.states.${st}`)}
                    </span>
                  ))}
              {impact.length > 0 && (
                <button className="ml-auto text-info hover:underline" onClick={() => setImpact([])}>
                  {t('inventory.clearImpact')}
                </button>
              )}
            </div>
            <div className="overflow-x-auto rounded-md border border-border bg-surface-2/40">
              <svg width={740} height={height} className="block" role="img" aria-label={t('inventory.map')}>
                {edges.map((e) => {
                  const a = pos[e.from]
                  const b = pos[e.to]
                  const active = selected === e.from || selected === e.to
                  return (
                    <g key={e.from + e.to}>
                      <path
                        d={`M${a.x + 70},${a.y} C${a.x + 140},${a.y} ${b.x - 140},${b.y} ${b.x - 70},${b.y}`}
                        fill="none"
                        stroke={active ? 'var(--text-2)' : 'var(--axis)'}
                        strokeWidth={active ? 2 : 1}
                      />
                      {active && (
                        <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 6} fontSize={10} textAnchor="middle" fill="var(--text-muted)">
                          {e.kind}
                        </text>
                      )}
                    </g>
                  )
                })}
                {nodes.map((n) => {
                  const p = pos[n.id]
                  const isSel = selected === n.id
                  const inImpact = impact.includes(n.id)
                  return (
                    <g
                      key={n.id}
                      className="cursor-pointer"
                      onClick={() => setSelected(n.id)}
                      role="button"
                      tabIndex={0}
                      aria-label={`${n.id} · ${t(`inventory.types.${n.type}`)}`}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setSelected(n.id)}
                    >
                      <rect
                        x={p.x - 70}
                        y={p.y - 18}
                        width={140}
                        height={36}
                        rx={n.type === 'transaction' || n.type === 'job' ? 18 : 6}
                        fill={inImpact ? 'color-mix(in srgb, var(--critical) 12%, var(--surface))' : 'var(--surface)'}
                        stroke={inImpact ? 'var(--critical)' : color(n)}
                        strokeWidth={isSel ? 3.5 : 2}
                      />
                      <text x={p.x} y={p.y - 3} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--text)">
                        {n.id}
                      </text>
                      <text x={p.x} y={p.y + 11} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
                        {t(`inventory.types.${n.type}`)}
                      </text>
                    </g>
                  )
                })}
              </svg>
            </div>
          </CardBody>
        </Card>

        <Card>
          {node ? (
            <>
              <CardHeader title={node.id} subtitle={`${t(`inventory.types.${node.type}`)} · ${node.domain}`} />
              <CardBody className="space-y-4 text-sm">
                <dl className="grid grid-cols-2 gap-3">
                  <div>
                    <dt className="text-xs text-muted">{t('inventory.migrationState')}</dt>
                    <dd className="flex items-center gap-1.5 text-text">
                      <span className="h-2 w-2 rounded-full" style={{ background: stateColor[node.state] }} />
                      {t(`inventory.states.${node.state}`)}
                    </dd>
                  </div>
                  {node.loc && (
                    <div>
                      <dt className="text-xs text-muted">{t('inventory.loc')}</dt>
                      <dd className="text-text tabular">{node.loc.toLocaleString()}</dd>
                    </div>
                  )}
                  <div className="col-span-2">
                    <dt className="text-xs text-muted">{t('inventory.target')}</dt>
                    <dd className="font-mono text-xs text-text">{node.target ?? '—'}</dd>
                  </div>
                </dl>
                <Relation title={t('inventory.uses')} items={uses.map((e) => ({ id: e.to, kind: e.kind }))} onSelect={setSelected} />
                <Relation title={t('inventory.usedBy')} items={usedBy.map((e) => ({ id: e.from, kind: e.kind }))} onSelect={setSelected} />
                <div>
                  <div className="mb-1 text-xs font-medium text-muted uppercase">{t('inventory.rules')}</div>
                  {node.rules.length === 0 ? (
                    <p className="text-xs text-muted">—</p>
                  ) : (
                    <div className="flex flex-wrap gap-1.5">
                      {node.rules.map((r) => (
                        <button key={r} onClick={() => onCompare(r)} className="rounded-md border border-border px-2 py-0.5 font-mono text-xs text-info hover:bg-surface-2">
                          {r}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex flex-col gap-2 border-t border-border pt-4">
                  <Button size="sm" onClick={() => setImpact(impactOf(node.id))}>
                    {t('inventory.showImpact')}
                  </Button>
                  {impact.length > 0 && <p className="text-xs text-critical-ink">{t('inventory.impactResult', { count: impact.length, items: impact.join(', ') })}</p>}
                  {node.rules[0] && (
                    <Button size="sm" variant="primary" onClick={() => onCompare(node.rules[0])}>
                      {t('inventory.openCompare')}
                    </Button>
                  )}
                </div>
              </CardBody>
            </>
          ) : (
            <CardBody>
              <p className="text-sm text-muted">{t('inventory.hoverHint')}</p>
            </CardBody>
          )}
        </Card>
      </div>
    </div>
  )
}

function Relation({ title, items, onSelect }: { title: string; items: { id: string; kind: string }[]; onSelect: (id: string) => void }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted uppercase">{title}</div>
      {items.length === 0 ? (
        <p className="text-xs text-muted">—</p>
      ) : (
        <ul className="space-y-1">
          {items.map((i) => (
            <li key={i.id + i.kind}>
              <button onClick={() => onSelect(i.id)} className="flex w-full items-center justify-between rounded px-1.5 py-0.5 text-left hover:bg-surface-2">
                <span className="font-mono text-xs text-text">{i.id}</span>
                <span className="text-[10px] text-muted">{i.kind}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
