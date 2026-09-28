import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, Maximize2, Minus, Plus, Search, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { businessFlows, edgeGroup, graphEdges, graphNodes, rules, type GraphNode, type GraphNodeType, type MigrationState } from '@/mocks/data'
import { Badge, Button, Card, CardBody, CardHeader, StatTile } from '@/components/ui/primitives'

// Interactive knowledge graph (spec section 5): relation filters, orphan/isolated filter, business-flow
// walkthrough, business-rule focus, search, zoom and pan. The real view renders Neo4j results.

type Relation = 'calls' | 'reads' | 'writes' | 'includes'
type Visibility = 'all' | 'orphans' | 'hideOrphans'

const TYPES: GraphNodeType[] = ['transaction', 'job', 'program', 'map', 'copybook', 'file']
const COLUMNS: Record<GraphNodeType, number> = { transaction: 0, job: 0, program: 1, map: 2, copybook: 2, file: 3 }
const RELATIONS: Relation[] = ['calls', 'reads', 'writes', 'includes']
const relationStyle: Record<Relation, { color: string; dash?: string }> = {
  calls: { color: 'var(--text-2)' },
  reads: { color: 'var(--series-1)' },
  writes: { color: 'var(--series-2)' },
  includes: { color: 'var(--text-muted)', dash: '4 3' },
}
const domainColor: Record<GraphNode['domain'], string> = { Accounts: 'var(--series-1)', Cards: 'var(--series-2)', Authorizations: 'var(--series-3)' }
const stateColor: Record<MigrationState, string> = { verified: 'var(--good)', generated: 'var(--info)', inProgress: 'var(--warning)', pending: 'var(--text-muted)' }
const NODE_W = 140
const NODE_H = 36

function layout(nodes: GraphNode[]) {
  const cols: Record<number, GraphNode[]> = {}
  nodes.forEach((n) => (cols[COLUMNS[n.type]] ??= []).push(n))
  const pos: Record<string, { x: number; y: number }> = {}
  Object.entries(cols).forEach(([c, list]) => list.forEach((n, i) => (pos[n.id] = { x: 90 + Number(c) * 200, y: 50 + i * 62 })))
  return pos
}

// Orphan: nobody uses it and it is not an entry point. Isolated: no relation at all.
function classify(id: string, type: GraphNodeType) {
  const incoming = graphEdges.some((e) => e.to === id)
  const outgoing = graphEdges.some((e) => e.from === id)
  if (!incoming && !outgoing) return 'isolated' as const
  if (!incoming && type !== 'transaction' && type !== 'job') return 'orphan' as const
  return null
}

export function KnowledgeGraph({ onCompare }: { onCompare: (ruleId: string) => void }) {
  const { t } = useTranslation()
  const [relations, setRelations] = useState<Relation[]>(RELATIONS)
  const [types, setTypes] = useState<GraphNodeType[]>(TYPES)
  const [visibility, setVisibility] = useState<Visibility>('all')
  const [domain, setDomain] = useState<'all' | GraphNode['domain']>('all')
  const [impact, setImpact] = useState<string[]>([])
  const [order, setOrder] = useState<string[] | null>(null)
  const [colorBy, setColorBy] = useState<'domain' | 'state'>('domain')
  const [query, setQuery] = useState('')
  const [flowId, setFlowId] = useState('')
  const [ruleId, setRuleId] = useState('')
  const [step, setStep] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  const svgRef = useRef<SVGSVGElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  const [boxWidth, setBoxWidth] = useState(800)

  const flow = businessFlows.find((f) => f.id === flowId)
  const rule = rules.find((r) => r.id === ruleId)

  // Visible nodes after type and orphan filters.
  const nodes = graphNodes.filter((n) => {
    if (!types.includes(n.type)) return false
    if (domain !== 'all' && n.domain !== domain) return false
    const kind = classify(n.id, n.type)
    if (visibility === 'orphans') return kind !== null
    if (visibility === 'hideOrphans') return kind === null
    return true
  })
  const ids = new Set(nodes.map((n) => n.id))
  const edges = graphEdges.filter((e) => ids.has(e.from) && ids.has(e.to) && relations.includes(edgeGroup[e.kind] ?? 'calls'))
  const pos = useMemo(() => layout(nodes), [nodes])
  const height = Math.max(0, ...Object.values(pos).map((p) => p.y)) + 60
  // Fit the whole graph to the available width (on load and on reset).
  const contentWidth = Math.max(0, ...Object.values(pos).map((p) => p.x)) + NODE_W / 2 + 40
  const fitK = Math.min(1.2, Math.max(0.5, boxWidth / Math.max(contentWidth, 1)))
  const fit = { k: fitK, x: 0, y: 0 }

  // Flow highlight: nodes in order of first appearance get a step number; edges between consecutive nodes.
  const flowNodes = new Map<string, number>()
  const flowEdges = new Set<string>()
  flow?.steps.forEach((s, i) => {
    s.nodes.forEach((n) => !flowNodes.has(n) && flowNodes.set(n, i + 1))
    s.nodes.slice(1).forEach((n, j) => {
      flowEdges.add(`${s.nodes[j]}>${n}`)
      flowEdges.add(`${n}>${s.nodes[j]}`)
    })
  })
  const stepNodes = new Set(flow?.steps[step]?.nodes ?? [])

  // Rule focus: nodes implementing the rule plus their direct neighbours.
  const ruleNodes = new Set<string>()
  if (rule) {
    graphNodes.filter((n) => n.rules.includes(rule.id)).forEach((n) => {
      ruleNodes.add(n.id)
      graphEdges.filter((e) => e.from === n.id || e.to === n.id).forEach((e) => (ruleNodes.add(e.from), ruleNodes.add(e.to)))
    })
  }

  // Selected node: highlight it and its direct connections.
  const selNodes = new Set<string>()
  if (selected) {
    selNodes.add(selected)
    graphEdges.filter((e) => e.from === selected || e.to === selected).forEach((e) => (selNodes.add(e.from), selNodes.add(e.to)))
  }

  const q = query.trim().toLowerCase()
  const focusActive = !!flow || !!rule || q.length > 1 || !!selected
  const isFocused = (id: string) =>
    flow ? flowNodes.has(id) : rule ? ruleNodes.has(id) : q.length > 1 ? id.toLowerCase().includes(q) : selected ? selNodes.has(id) : true

  // Everything that (transitively) depends on a node: what could break if it changes.
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

  // Suggested migration order: data and shared layouts first, then programs by fewest dependents, entry points last.
  function migrationOrder() {
    const rank: Record<GraphNodeType, number> = { file: 0, copybook: 1, map: 2, program: 3, transaction: 4, job: 4 }
    return graphNodes
      .filter((n) => classify(n.id, n.type) === null)
      .sort((a, b) => rank[a.type] - rank[b.type] || impactOf(a.id).length - impactOf(b.id).length)
      .map((n) => n.id)
  }

  // Wheel zoom needs a non-passive listener to prevent page scroll.
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      touched.current = true
      setView((v) => ({ ...v, k: Math.min(2.5, Math.max(0.4, v.k * (e.deltaY < 0 ? 1.1 : 0.9))) }))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  useEffect(() => setStep(0), [flowId])

  useEffect(() => {
    const el = boxRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setBoxWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Re-fit when the container size changes, unless the user already zoomed or panned.
  const touched = useRef(false)
  useEffect(() => {
    if (!touched.current) setView({ k: fitK, x: 0, y: 0 })
  }, [fitK])

  const node = graphNodes.find((n) => n.id === selected)
  const counts = TYPES.map((ty) => [ty, graphNodes.filter((n) => n.type === ty).length] as const)
  const orphanCount = graphNodes.filter((n) => classify(n.id, n.type) !== null).length
  const color = (n: GraphNode) => (colorBy === 'domain' ? domainColor[n.domain] : stateColor[n.state])

  function toggle<T>(list: T[], v: T, set: (x: T[]) => void) {
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-7">
        {counts.map(([k, v]) => (
          <StatTile key={k} label={t(`inventory.typesPlural.${k}`)} value={v} />
        ))}
        <button className="text-left" onClick={() => setVisibility('orphans')}>
          <StatTile label={t('graph.orphans')} value={orphanCount} hint={t('graph.orphansHint')} />
        </button>
      </div>

      <div className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)_320px]">
        {/* Filters */}
        <Card className="h-fit">
          <CardBody className="space-y-5">
            <div className="relative">
              <Search size={14} className="absolute top-1/2 left-2.5 -translate-y-1/2 text-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('graph.search')}
                aria-label={t('graph.search')}
                className="h-9 w-full rounded-md border border-border bg-surface pr-3 pl-8 text-sm text-text placeholder:text-muted focus:outline-none"
              />
            </div>

            <FilterGroup title={t('graph.flow')}>
              <select value={flowId} onChange={(e) => (setFlowId(e.target.value), setRuleId(''))} className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text" aria-label={t('graph.flow')}>
                <option value="">{t('graph.none')}</option>
                {businessFlows.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} ({f.persona})
                  </option>
                ))}
              </select>
            </FilterGroup>

            <FilterGroup title={t('graph.rule')}>
              <select value={ruleId} onChange={(e) => (setRuleId(e.target.value), setFlowId(''))} className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text" aria-label={t('graph.rule')}>
                <option value="">{t('graph.none')}</option>
                {rules.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.id} · {r.name}
                  </option>
                ))}
              </select>
            </FilterGroup>

            <FilterGroup title={t('graph.relations')}>
              {RELATIONS.map((r) => (
                <label key={r} className="flex cursor-pointer items-center gap-2 text-sm text-text">
                  <input type="checkbox" checked={relations.includes(r)} onChange={() => toggle(relations, r, setRelations)} className="accent-[var(--series-1)]" />
                  <svg width="22" height="6" aria-hidden>
                    <line x1="0" y1="3" x2="22" y2="3" stroke={relationStyle[r].color} strokeWidth="2.5" strokeDasharray={relationStyle[r].dash} />
                  </svg>
                  {t(`graph.relationNames.${r}`)}
                </label>
              ))}
            </FilterGroup>

            <FilterGroup title={t('graph.nodes')}>
              <select value={visibility} onChange={(e) => setVisibility(e.target.value as Visibility)} className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text" aria-label={t('graph.nodes')}>
                <option value="all">{t('graph.visibility.all')}</option>
                <option value="orphans">{t('graph.visibility.orphans')}</option>
                <option value="hideOrphans">{t('graph.visibility.hideOrphans')}</option>
              </select>
              <select value={domain} onChange={(e) => setDomain(e.target.value as typeof domain)} className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text" aria-label={t('inventory.domain')}>
                <option value="all">{t('inventory.allDomains')}</option>
                {Object.keys(domainColor).map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {TYPES.map((ty) => (
                  <button
                    key={ty}
                    onClick={() => toggle(types, ty, setTypes)}
                    aria-pressed={types.includes(ty)}
                    className={cn('rounded-full border px-2 py-0.5 text-xs', types.includes(ty) ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-muted')}
                  >
                    {t(`inventory.types.${ty}`)}
                  </button>
                ))}
              </div>
            </FilterGroup>

            <FilterGroup title={t('inventory.colorBy')}>
              <div className="flex rounded-md border border-border p-0.5 text-xs" role="group">
                {(['domain', 'state'] as const).map((c) => (
                  <button key={c} onClick={() => setColorBy(c)} aria-pressed={colorBy === c} className={cn('flex-1 rounded px-2 py-1', colorBy === c ? 'bg-brand text-brand-contrast' : 'text-muted')}>
                    {t(`inventory.colorModes.${c}`)}
                  </button>
                ))}
              </div>
              <div className="mt-2 space-y-1 text-xs text-text-2">
                {(colorBy === 'domain' ? Object.entries(domainColor) : Object.entries(stateColor)).map(([k, c]) => (
                  <div key={k} className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
                    {colorBy === 'domain' ? k : t(`inventory.states.${k}`)}
                  </div>
                ))}
              </div>
            </FilterGroup>
          </CardBody>
        </Card>

        {/* Canvas */}
        <Card className="min-w-0">
          <CardHeader
            title={flow ? flow.name : rule ? `${rule.id} · ${rule.name}` : t('inventory.map')}
            subtitle={t('graph.stats', { nodes: nodes.length, edges: edges.length })}
            action={
              <div className="flex items-center gap-1">
                <IconButton label={t('graph.zoomIn')} onClick={() => ((touched.current = true), setView((v) => ({ ...v, k: Math.min(2.5, v.k * 1.2) })))}>
                  <Plus size={14} />
                </IconButton>
                <IconButton label={t('graph.zoomOut')} onClick={() => ((touched.current = true), setView((v) => ({ ...v, k: Math.max(0.4, v.k / 1.2) })))}>
                  <Minus size={14} />
                </IconButton>
                <IconButton label={t('graph.reset')} onClick={() => ((touched.current = false), setView(fit))}>
                  <Maximize2 size={14} />
                </IconButton>
              </div>
            }
          />
          <div ref={boxRef} className="relative overflow-hidden bg-surface-2/40">
            <svg
              ref={svgRef}
              width="100%"
              height={Math.max(420, height * view.k + 50)}
              className="block cursor-grab touch-none active:cursor-grabbing"
              role="img"
              aria-label={t('inventory.map')}
              onPointerDown={(e) => {
                touched.current = true
                drag.current = { x: e.clientX - view.x, y: e.clientY - view.y }
                ;(e.target as Element).setPointerCapture?.(e.pointerId)
              }}
              onPointerMove={(e) => drag.current && setView((v) => ({ ...v, x: e.clientX - drag.current!.x, y: e.clientY - drag.current!.y }))}
              onPointerUp={() => (drag.current = null)}
              onClick={() => !flow && !rule && setSelected(null)}
              onKeyDown={(e) => e.key === 'Escape' && ((touched.current = false), setView(fit), setFlowId(''), setRuleId(''), setSelected(null))}
              tabIndex={0}
            >
              <defs>
                {RELATIONS.map((r) => (
                  <marker key={r} id={`arrow-${r}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                    <path d="M0,0 L10,5 L0,10 z" fill={relationStyle[r].color} />
                  </marker>
                ))}
                <marker id="arrow-flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--text)" />
                </marker>
              </defs>
              <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
                {edges.map((e) => {
                  const a = pos[e.from]
                  const b = pos[e.to]
                  const rel = edgeGroup[e.kind] ?? 'calls'
                  const inFlow = flowEdges.has(`${e.from}>${e.to}`)
                  const touchesSelected = !flow && !rule && !!selected && (e.from === selected || e.to === selected)
                  const dim = focusActive && !inFlow && !touchesSelected && !(isFocused(e.from) && isFocused(e.to) && !selected)
                  const sameCol = a.x === b.x
                  const d = sameCol
                    ? `M${a.x + NODE_W / 2},${a.y} C${a.x + NODE_W / 2 + 50},${a.y} ${b.x + NODE_W / 2 + 50},${b.y} ${b.x + NODE_W / 2},${b.y}`
                    : `M${a.x + NODE_W / 2},${a.y} C${a.x + 120},${a.y} ${b.x - 120},${b.y} ${b.x - NODE_W / 2 - 4},${b.y}`
                  return (
                    <path
                      key={e.from + e.to + e.kind}
                      d={d}
                      fill="none"
                      stroke={inFlow ? 'var(--text)' : relationStyle[rel].color}
                      strokeWidth={inFlow ? 2.5 : touchesSelected ? 2.2 : 1.3}
                      strokeDasharray={inFlow ? undefined : relationStyle[rel].dash}
                      markerEnd={`url(#arrow-${inFlow ? 'flow' : rel})`}
                      opacity={dim ? 0.12 : 0.9}
                    >
                      <title>{`${e.from} ${e.kind} ${e.to}`}</title>
                    </path>
                  )
                })}
                {nodes.map((n) => {
                  const p = pos[n.id]
                  const dim = focusActive && !isFocused(n.id)
                  const orphanKind = classify(n.id, n.type)
                  const stepNo = flowNodes.get(n.id)
                  const inStep = stepNodes.has(n.id)
                  return (
                    <g
                      key={n.id}
                      opacity={dim ? 0.2 : 1}
                      className="cursor-pointer"
                      onClick={(e) => (e.stopPropagation(), setSelected(n.id))}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        touched.current = true
                        const k = Math.min(2.5, Math.max(view.k, 1.6))
                        setView({ k, x: boxWidth / 2 - p.x * k, y: 180 - p.y * k })
                      }}
                      onPointerDown={(e) => e.stopPropagation()}
                      role="button"
                      tabIndex={0}
                      aria-label={`${n.id} · ${t(`inventory.types.${n.type}`)}`}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setSelected(n.id)}
                    >
                      <rect
                        x={p.x - NODE_W / 2}
                        y={p.y - NODE_H / 2}
                        width={NODE_W}
                        height={NODE_H}
                        rx={n.type === 'transaction' || n.type === 'job' ? NODE_H / 2 : 6}
                        fill={impact.includes(n.id) ? 'color-mix(in srgb, var(--critical) 12%, var(--surface))' : 'var(--surface)'}
                        stroke={impact.includes(n.id) ? 'var(--critical)' : color(n)}
                        strokeWidth={selected === n.id || inStep ? 3.5 : 2}
                        strokeDasharray={orphanKind ? '5 3' : undefined}
                      />
                      <text x={p.x} y={p.y - 3} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--text)">
                        {n.id}
                      </text>
                      <text x={p.x} y={p.y + 11} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
                        {orphanKind ? t(`graph.kind.${orphanKind}`) : t(`inventory.types.${n.type}`)}
                      </text>
                      {stepNo && (
                        <g>
                          <circle cx={p.x - NODE_W / 2 + 2} cy={p.y - NODE_H / 2 - 2} r={10} fill="var(--brand)" stroke="var(--surface)" strokeWidth={2} />
                          <text x={p.x - NODE_W / 2 + 2} y={p.y - NODE_H / 2 + 2} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--brand-contrast)">
                            {stepNo}
                          </text>
                        </g>
                      )}
                    </g>
                  )
                })}
              </g>
            </svg>
            <p className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted">{t('graph.help')}</p>
          </div>
        </Card>

        {/* Side panel: flow walkthrough, rule focus or node detail */}
        <Card className="h-fit">
          {flow ? (
            <>
              <CardHeader
                title={flow.name}
                subtitle={t('graph.persona', { persona: flow.persona })}
                action={
                  <button onClick={() => setFlowId('')} className="rounded p-1 text-muted hover:text-text" aria-label={t('common.close')}>
                    <X size={16} />
                  </button>
                }
              />
              <CardBody className="space-y-4 text-sm">
                <p className="text-text-2">{flow.summary}</p>
                <div className="text-xs font-medium tracking-wide text-muted uppercase">{t('graph.steps')}</div>
                <ol className="space-y-1">
                  {flow.steps.map((s, i) => (
                    <li key={s.title}>
                      <button onClick={() => setStep(i)} className={cn('flex w-full gap-3 rounded-md p-2 text-left', step === i ? 'bg-brand/10 dark:bg-accent/10' : 'hover:bg-surface-2')}>
                        <span className={cn('flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold', step === i ? 'bg-brand text-brand-contrast' : 'bg-surface-2 text-muted')}>{i + 1}</span>
                        <span className="min-w-0">
                          <span className="block text-text">{s.title}</span>
                          <span className="block font-mono text-xs text-muted">{s.nodes.join(' → ')}</span>
                          {s.rule && (
                            <span
                              role="link"
                              tabIndex={0}
                              onClick={(e) => (e.stopPropagation(), onCompare(s.rule!))}
                              onKeyDown={(e) => e.key === 'Enter' && onCompare(s.rule!)}
                              className="mt-1 inline-block rounded border border-border px-1.5 py-0.5 font-mono text-xs text-info hover:bg-surface-2"
                            >
                              {s.rule}
                            </span>
                          )}
                        </span>
                      </button>
                    </li>
                  ))}
                </ol>
                <div className="flex justify-between border-t border-border pt-3">
                  <Button size="sm" variant="ghost" disabled={step === 0} onClick={() => setStep(step - 1)}>
                    <ChevronLeft size={14} /> {t('common.back')}
                  </Button>
                  <Button size="sm" disabled={step === flow.steps.length - 1} onClick={() => setStep(step + 1)}>
                    {t('common.next')} <ChevronRight size={14} />
                  </Button>
                </div>
              </CardBody>
            </>
          ) : rule ? (
            <>
              <CardHeader title={`${rule.id} · ${rule.name}`} subtitle={`${rule.domain} · ${rule.priority}`} />
              <CardBody className="space-y-3 text-sm">
                <p className="text-text-2">{rule.statement}</p>
                <div className="text-xs text-muted">{t('graph.implementedIn')}</div>
                <div className="flex flex-wrap gap-1.5">
                  {graphNodes
                    .filter((n) => n.rules.includes(rule.id))
                    .map((n) => (
                      <button key={n.id} onClick={() => setSelected(n.id)} className="rounded border border-border px-2 py-0.5 font-mono text-xs text-text hover:bg-surface-2">
                        {n.id}
                      </button>
                    ))}
                </div>
                <div className="text-xs text-muted">{t('graph.inFlows')}</div>
                <ul className="space-y-1">
                  {businessFlows
                    .filter((f) => f.rules.includes(rule.id))
                    .map((f) => (
                      <li key={f.id}>
                        <button onClick={() => (setRuleId(''), setFlowId(f.id))} className="text-left text-info hover:underline">
                          {f.name}
                        </button>
                      </li>
                    ))}
                </ul>
                <Button size="sm" variant="primary" className="w-full" onClick={() => onCompare(rule.id)}>
                  {t('inventory.openCompare')}
                </Button>
              </CardBody>
            </>
          ) : node ? (
            <NodeDetail
              node={node}
              onSelect={setSelected}
              onCompare={onCompare}
              impact={impact}
              onImpact={() => setImpact(impactOf(node.id))}
              onClearImpact={() => setImpact([])}
            />
          ) : (
            <CardBody className="space-y-3 text-sm text-text-2">
              <p>{t('graph.emptyPanel')}</p>
              <Button size="sm" onClick={() => setFlowId(businessFlows[0].id)}>
                {t('graph.tryFlow')}
              </Button>
            </CardBody>
          )}
        </Card>
      </div>

      <Card>
        <CardHeader title={t('inventory.impact')} subtitle={t('inventory.impactHint')} />
        <CardBody className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => (setSelected('CVACT01Y'), setImpact(impactOf('CVACT01Y')), setOrder(null))}>
              {t('inventory.impactCopybook')}
            </Button>
            <Button size="sm" onClick={() => (setDomain('Accounts'), setImpact([]), setOrder(null))}>
              {t('inventory.impactDomain')}
            </Button>
            <Button size="sm" onClick={() => (setOrder(migrationOrder()), setImpact([]))}>
              {t('inventory.impactOrder')}
            </Button>
            <Button
              size="sm"
              onClick={() => (setVisibility('all'), setImpact(graphNodes.filter((n) => n.type === 'program' && n.rules.length === 0).map((n) => n.id)), setOrder(null))}
            >
              {t('inventory.impactOrphans')}
            </Button>
            <Button size="sm" onClick={() => (setVisibility('orphans'), setImpact([]), setOrder(null))}>
              {t('inventory.impactUnused')}
            </Button>
          </div>
          {order && (
            <div>
              <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('graph.orderTitle')}</div>
              <ol className="flex flex-wrap gap-2 text-xs">
                {order.map((id, i) => (
                  <li key={id}>
                    <button onClick={() => setSelected(id)} className="rounded-md border border-border px-2 py-1 font-mono text-text hover:bg-surface-2">
                      {i + 1}. {id}
                    </button>
                  </li>
                ))}
              </ol>
              <p className="mt-2 text-xs text-muted">{t('graph.orderHint')}</p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

function NodeDetail({
  node,
  onSelect,
  onCompare,
  impact,
  onImpact,
  onClearImpact,
}: {
  node: GraphNode
  onSelect: (id: string) => void
  onCompare: (r: string) => void
  impact: string[]
  onImpact: () => void
  onClearImpact: () => void
}) {
  const { t } = useTranslation()
  const outgoing = graphEdges.filter((e) => e.from === node.id)
  const incoming = graphEdges.filter((e) => e.to === node.id)
  const kind = classify(node.id, node.type)
  const connections = [
    ...outgoing.map((e) => ({ dir: 'out' as const, id: e.to, kind: e.kind })),
    ...incoming.map((e) => ({ dir: 'in' as const, id: e.from, kind: e.kind })),
  ]
  return (
    <>
      <CardHeader title={node.id} subtitle={`${t(`inventory.types.${node.type}`)} · ${node.domain}`} action={kind ? <Badge tone="warning">{t(`graph.kind.${kind}`)}</Badge> : undefined} />
      <CardBody className="space-y-4 text-sm">
        {node.description ? (
          <div>
            <p className="leading-relaxed text-text">{node.description}</p>
            <p className="mt-1 text-xs text-muted">{t('graph.writtenBy')}</p>
          </div>
        ) : (
          <p className="text-xs text-muted">{t('graph.noDescription')}</p>
        )}
        {kind && <p className="text-xs text-warning-ink">{t(`graph.kindHint.${kind}`)}</p>}
        <div className="flex flex-wrap gap-1.5">
          <Badge>{t('graph.fanIn', { count: incoming.length })}</Badge>
          <Badge>{t('graph.fanOut', { count: outgoing.length })}</Badge>
          <Badge tone={node.state === 'verified' ? 'good' : node.state === 'pending' ? 'neutral' : 'info'}>{t(`inventory.states.${node.state}`)}</Badge>
          {node.loc && <Badge>{t('graph.loc', { count: node.loc })}</Badge>}
        </div>
        {node.source && (
          <div>
            <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('graph.source')}</div>
            <p className="font-mono text-xs text-text">{node.source}</p>
          </div>
        )}
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('inventory.target')}</div>
          <p className="font-mono text-xs text-text">{node.target ?? '—'}</p>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('graph.connections', { count: connections.length })}</div>
          {connections.length === 0 ? (
            <p className="text-xs text-muted">—</p>
          ) : (
            <ul className="space-y-0.5">
              {connections.map((c) => (
                <li key={c.dir + c.id + c.kind}>
                  <button onClick={() => onSelect(c.id)} className="flex w-full items-baseline gap-2 rounded px-1.5 py-1 text-left hover:bg-surface-2">
                    <span className="text-info" aria-label={t(`graph.dir.${c.dir}`)}>
                      {c.dir === 'out' ? '→' : '←'}
                    </span>
                    <span className="font-mono text-xs text-info">{c.id}</span>
                    <span className="ml-auto text-[10px] text-muted">{t(`graph.edgeKinds.${c.kind}`)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <Relations title={t('inventory.uses')} items={outgoing.map((e) => ({ id: e.to, kind: e.kind }))} onSelect={onSelect} />
        <Relations title={t('inventory.usedBy')} items={incoming.map((e) => ({ id: e.from, kind: e.kind }))} onSelect={onSelect} />
        <div className="space-y-2 border-t border-border pt-3">
          <Button size="sm" className="w-full" onClick={onImpact}>
            {t('inventory.showImpact')}
          </Button>
          {impact.length > 0 && (
            <p className="text-xs text-critical-ink">
              {t('inventory.impactResult', { count: impact.length, items: impact.join(', ') })}{' '}
              <button className="text-info hover:underline" onClick={onClearImpact}>
                {t('inventory.clearImpact')}
              </button>
            </p>
          )}
        </div>
        {node.rules.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('inventory.rules')}</div>
            <div className="flex flex-wrap gap-1.5">
              {node.rules.map((r) => (
                <button key={r} onClick={() => onCompare(r)} className="rounded-md border border-border px-2 py-0.5 font-mono text-xs text-info hover:bg-surface-2">
                  {r}
                </button>
              ))}
            </div>
          </div>
        )}
        {node.rules[0] && (
          <Button size="sm" variant="primary" className="w-full" onClick={() => onCompare(node.rules[0])}>
            {t('inventory.openCompare')}
          </Button>
        )}
      </CardBody>
    </>
  )
}

function Relations({ title, items, onSelect }: { title: string; items: { id: string; kind: string }[]; onSelect: (id: string) => void }) {
  const { t } = useTranslation()
  return (
    <div>
      <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{title}</div>
      {items.length === 0 ? (
        <p className="text-xs text-muted">—</p>
      ) : (
        <ul className="space-y-0.5">
          {items.map((i) => (
            <li key={i.id + i.kind}>
              <button onClick={() => onSelect(i.id)} className="flex w-full items-center justify-between rounded px-1.5 py-0.5 text-left hover:bg-surface-2">
                <span className="font-mono text-xs text-text">{i.id}</span>
                <span className="text-[10px] text-muted">{t(`graph.edgeKinds.${i.kind}`)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function FilterGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} aria-label={label} title={label} className="rounded-md border border-border p-1.5 text-muted hover:bg-surface-2 hover:text-text">
      {children}
    </button>
  )
}
