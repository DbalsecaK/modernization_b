import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { hierarchy, pack } from 'd3-hierarchy'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronLeft, ChevronRight, Layers, Maximize2, Minus, Plus, Search, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import type {
  GraphData,
  GraphEdge,
  GraphFlow,
  GraphInsights,
  GraphNode,
  GraphNodeType,
  MigrationState,
} from '@/api/graph'
import { Badge, Button, Card, CardBody, CardHeader, StatTile } from '@/components/ui/primitives'
import {
  SCENARIO_PREFIX,
  childrenOf,
  flowOptions,
  groupKeyOf,
  isDrawable,
  parentsOf,
  phaseOf,
  summaryOf,
  topLevel,
  unitForStep,
  unitView,
} from './graphModel'

// Interactive knowledge graph (spec 5.2.1): relation filters, orphan/isolated filter, business-flow walkthrough,
// business-rule focus, search, zoom and pan, over the project's real graph (GET /graph). Same view as the prototype.
// Deep inventory (ADR-0032) adds on top: entering a unit to see its blocks, grouping by transactional phase, model
// descriptions, flows by scenario, architect observations, a summary header and a marker on tables without DDL.

type Relation = 'calls' | 'reads' | 'writes' | 'includes' | 'follows' | 'jumps' | 'onError'
type Visibility = 'all' | 'orphans' | 'hideOrphans' | 'external' | 'hideExternal'

const TYPES: GraphNodeType[] = ['transaction', 'program', 'map', 'copybook', 'file']
const COLUMNS: Record<GraphNodeType, number> = { transaction: 0, program: 1, map: 2, copybook: 2, file: 3 }
const edgeGroup: Record<string, Relation> = {
  STARTS: 'calls',
  CALLS: 'calls',
  READS: 'reads',
  WRITES: 'writes',
  COPIES: 'includes',
  USES_MAP: 'includes',
  // Between the blocks of a unit (ADR-0032). CONTAINS is structure and is never drawn.
  NEXT: 'follows',
  GOTO: 'jumps',
  ON_ERROR: 'onError',
}
const RELATIONS: Relation[] = ['calls', 'reads', 'writes', 'includes', 'follows', 'jumps', 'onError']
// The order of the tiles: units of code first, then screens and shared layouts, then data.
const KIND_ORDER = ['StoredProcedure', 'Program', 'Class', 'Transaction', 'Page', 'BmsMap', 'Copybook', 'Table', 'File']
const relationStyle: Record<Relation, { color: string; dash?: string }> = {
  calls: { color: 'var(--text-2)' },
  reads: { color: 'var(--series-1)' },
  writes: { color: 'var(--series-2)' },
  includes: { color: 'var(--text-muted)', dash: '4 3' },
  follows: { color: 'var(--series-3)' },
  jumps: { color: 'var(--warning)', dash: '7 3' },
  onError: { color: 'var(--critical)', dash: '2 3' },
}
const PALETTE = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--info)',
  'var(--warning)',
  'var(--good)',
]
const stateColor: Record<MigrationState, string> = {
  verified: 'var(--good)',
  generated: 'var(--info)',
  inProgress: 'var(--warning)',
  pending: 'var(--text-muted)',
}
const NODE_W = 140
const NODE_H = 36

type Walk = { name: string; steps: { title: string; nodes: string[]; rule: string | null }[] }

function layout(nodes: GraphNode[]) {
  const cols: Record<number, GraphNode[]> = {}
  nodes.forEach((n) => (cols[COLUMNS[n.type]] ??= []).push(n))
  const pos: Record<string, { x: number; y: number }> = {}
  Object.entries(cols).forEach(([c, list]) =>
    list.forEach((n, i) => (pos[n.id] = { x: 90 + Number(c) * 200, y: 50 + i * 62 })),
  )
  return pos
}

// Circle-packing layout: system → domains (entry points, programs, maps, copybooks) and a separate data-stores
// group (files and tables). Circle size follows lines of code where known.
type PackGroup = { id: string; label: string; x: number; y: number; r: number; depth: number }
const PACK_SIZE = 760

// `groupOf` picks the circle of each non-data node (by default its domain; inside a unit, optionally its phase).
function packLayout(
  nodes: GraphNode[],
  dataLabel: string,
  systemLabel: string,
  groupOf: (n: GraphNode) => { key: string; label: string } = (n) => ({ key: n.domain, label: n.domain }),
) {
  type Datum = { id: string; label: string; value?: number; children?: Datum[] }
  const size = (n: GraphNode) =>
    n.loc ? Math.max(60, n.loc / 12) : n.type === 'file' ? 70 : n.type === 'copybook' ? 55 : 60
  const byGroup = new Map<string, Datum>()
  nodes
    .filter((n) => n.type !== 'file')
    .forEach((n) => {
      const g = groupOf(n)
      if (!byGroup.has(g.key)) byGroup.set(g.key, { id: `group:${g.key}`, label: g.label, children: [] })
      byGroup.get(g.key)!.children!.push({ id: n.id, label: n.name, value: size(n) })
    })
  const children: Datum[] = [...byGroup.values()]
  const files = nodes.filter((n) => n.type === 'file')
  if (files.length)
    children.push({
      id: 'group:data',
      label: dataLabel,
      children: files.map((n) => ({ id: n.id, label: n.name, value: size(n) })),
    })
  const root = hierarchy<Datum>({ id: 'root', label: systemLabel, children })
    .sum((d) => d.value ?? 0)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  const packed = pack<Datum>()
    .size([PACK_SIZE, PACK_SIZE])
    .padding((d) => (d.depth === 0 ? 28 : 10))(root)
  const pos: Record<string, { x: number; y: number; r: number }> = {}
  const groups: PackGroup[] = []
  packed.descendants().forEach((d) => {
    if (d.children) groups.push({ id: d.data.id, label: d.data.label, x: d.x, y: d.y, r: d.r, depth: d.depth })
    else pos[d.data.id] = { x: d.x, y: d.y, r: d.r }
  })
  return { pos, groups }
}

// Orphan: nobody uses it and it is not an entry point (decided by the server). Isolated: no relation at all.
function classify(node: GraphNode, edges: GraphEdge[]) {
  if (!node.orphan) return null
  return edges.some((e) => e.from === node.id || e.to === node.id) ? ('orphan' as const) : ('isolated' as const)
}

export function KnowledgeGraph({
  data,
  insights,
  onCompare,
  onImpact,
}: {
  data: GraphData
  /** Model-written reading aids (descriptions, observations, scenarios); absent or empty without deep inventory. */
  insights?: GraphInsights
  onCompare: (ruleId: string) => void
  onImpact: (nodeId: string) => Promise<string[]>
}) {
  const { t } = useTranslation()
  const { nodes: graphNodes, edges: graphEdges, rules, flows: businessFlows } = data
  const scenarios = insights?.scenarios ?? []
  const observations = insights?.observations ?? []
  // Blocks (children of a unit) are hidden at the top level and shown when the user enters their unit.
  const parents = useMemo(() => parentsOf(graphNodes, graphEdges), [graphNodes, graphEdges])
  const topNodes = useMemo(() => topLevel(graphNodes, parents), [graphNodes, parents])
  const drawableEdges = useMemo(() => graphEdges.filter(isDrawable), [graphEdges])
  const summary = summaryOf(data, parents)
  const options = flowOptions(businessFlows, scenarios)
  const domains = useMemo(() => [...new Set(graphNodes.map((n) => n.domain))].sort(), [graphNodes])
  const domainColor: Record<string, string> = Object.fromEntries(
    domains.map((d, i) => [d, PALETTE[i % PALETTE.length]]),
  )
  const nameOf = (id: string) => graphNodes.find((n) => n.id === id)?.name ?? id
  const stepTitle = (s: GraphFlow['steps'][number]) =>
    t(`graph.stepKinds.${s.kind}`, { from: nameOf(s.nodes[0]), to: nameOf(s.nodes[s.nodes.length - 1]) })
  const showImpact = (id: string) => void onImpact(id).then(setImpact)
  const [relations, setRelations] = useState<Relation[]>(RELATIONS)
  const [types, setTypes] = useState<GraphNodeType[]>(TYPES)
  const [visibility, setVisibility] = useState<Visibility>('all')
  const [domain, setDomain] = useState<string>('all')
  const [impact, setImpact] = useState<string[]>([])
  const [order, setOrder] = useState<string[] | null>(null)
  const [colorBy, setColorBy] = useState<'domain' | 'state'>('domain')
  const [mode, setMode] = useState<'circles' | 'layers'>('circles')
  const [query, setQuery] = useState('')
  const [flowId, setFlowId] = useState('')
  const [ruleId, setRuleId] = useState('')
  const [step, setStep] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [unit, setUnit] = useState<string | null>(null)
  const [groupBy, setGroupBy] = useState<'domain' | 'phase'>('domain')
  const [observationsOpen, setObservationsOpen] = useState(true)
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  const svgRef = useRef<SVGSVGElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)
  // Set once the user zooms or pans, so a container resize no longer re-fits the view.
  const touched = useRef(false)
  const [boxWidth, setBoxWidth] = useState(800)

  const flow = businessFlows.find((f) => f.id === flowId)
  const scenario = scenarios.find((s) => `${SCENARIO_PREFIX}${s.id}` === flowId)
  const rule = rules.find((r) => r.id === ruleId)
  // The walkthrough on the right: an entry-point flow or a scenario, both as titled steps over graph nodes.
  const walk: Walk | undefined = flow
    ? { name: flow.name, steps: flow.steps.map((s) => ({ title: stepTitle(s), nodes: s.nodes, rule: s.rule })) }
    : scenario
      ? { name: scenario.name, steps: scenario.steps.map((s) => ({ ...s, rule: s.rule ?? null })) }
      : undefined
  const stepNodesOf = (value: string) =>
    (
      businessFlows.find((f) => f.id === value)?.steps ??
      scenarios.find((s) => `${SCENARIO_PREFIX}${s.id}` === value)?.steps ??
      []
    ).map((s) => s.nodes)
  const unitNode = unit ? graphNodes.find((n) => n.id === unit) : undefined
  const unitNodes = useMemo(
    () => (unit ? unitView(unit, graphNodes, graphEdges, parents) : null),
    [unit, graphNodes, graphEdges, parents],
  )
  const childCount = (id: string) => childrenOf(id, parents).length

  // Visible nodes after type and orphan filters: the top level, or the blocks of the entered unit and what they touch.
  const nodes = (unitNodes ?? topNodes).filter((n) => {
    if (!types.includes(n.type)) return false
    if (!unitNodes && domain !== 'all' && n.domain !== domain) return false
    const kind = classify(n, graphEdges)
    if (visibility === 'orphans') return kind !== null
    if (visibility === 'hideOrphans') return kind === null
    if (visibility === 'external') return n.external
    if (visibility === 'hideExternal') return !n.external
    return true
  })
  const ids = new Set(nodes.map((n) => n.id))
  const edges = drawableEdges.filter(
    (e) => ids.has(e.from) && ids.has(e.to) && relations.includes(edgeGroup[e.kind] ?? 'calls'),
  )
  const groupLabel = (key: string) =>
    key === 'outside'
      ? t('graph.outsideUnit')
      : key.startsWith('phase:')
        ? t(`graph.phases.${key.slice('phase:'.length)}`)
        : key
  const packed = packLayout(nodes, t('graph.dataStores'), unitNode ? unitNode.name : t('graph.system'), (n) => {
    const key = groupKeyOf(n, unit ? groupBy : 'domain', parents)
    return { key, label: groupLabel(key) }
  })
  const layered = layout(nodes)
  const pos: Record<string, { x: number; y: number; r?: number }> = mode === 'circles' ? packed.pos : layered
  const height = mode === 'circles' ? PACK_SIZE : Math.max(0, ...Object.values(pos).map((p) => p.y)) + 60
  // Fit the whole graph to the available width (on load and on reset).
  const contentWidth =
    mode === 'circles' ? PACK_SIZE : Math.max(0, ...Object.values(pos).map((p) => p.x)) + NODE_W / 2 + 40
  const fitK = Math.min(1.2, Math.max(0.5, boxWidth / Math.max(contentWidth, 1)))
  const fit = { k: fitK, x: 0, y: 0 }

  // Flow highlight: nodes in order of first appearance get a step number; edges between consecutive nodes.
  const flowNodes = new Map<string, number>()
  const flowEdges = new Set<string>()
  walk?.steps.forEach((s, i) => {
    s.nodes.forEach((n) => !flowNodes.has(n) && flowNodes.set(n, i + 1))
    s.nodes.slice(1).forEach((n, j) => {
      flowEdges.add(`${s.nodes[j]}>${n}`)
      flowEdges.add(`${n}>${s.nodes[j]}`)
    })
  })
  const stepNodes = new Set(walk?.steps[step]?.nodes ?? [])

  // Rule focus: nodes implementing the rule plus their direct neighbours.
  const ruleNodes = new Set<string>()
  if (rule) {
    graphNodes
      .filter((n) => n.rules.includes(rule.id))
      .forEach((n) => {
        ruleNodes.add(n.id)
        graphEdges
          .filter((e) => e.from === n.id || e.to === n.id)
          .forEach((e) => (ruleNodes.add(e.from), ruleNodes.add(e.to)))
      })
  }

  // Selected node: highlight it and its direct connections.
  const selNodes = new Set<string>()
  if (selected) {
    selNodes.add(selected)
    graphEdges
      .filter((e) => e.from === selected || e.to === selected)
      .forEach((e) => (selNodes.add(e.from), selNodes.add(e.to)))
  }

  const q = query.trim().toLowerCase()
  const focusActive = !!walk || !!rule || q.length > 1 || !!selected
  const isFocused = (id: string) =>
    walk
      ? flowNodes.has(id)
      : rule
        ? ruleNodes.has(id)
        : q.length > 1
          ? nameOf(id).toLowerCase().includes(q)
          : selected
            ? selNodes.has(id)
            : true

  // Everything that (transitively) depends on a node: what could break if it changes.
  function impactOf(id: string) {
    const out = new Set<string>()
    const walk = (x: string) =>
      graphEdges
        .filter((e) => e.to === x)
        .forEach((e) => {
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
    const rank: Record<GraphNodeType, number> = { file: 0, copybook: 1, map: 2, program: 3, transaction: 4 }
    return topNodes
      .filter((n) => classify(n, graphEdges) === null && !n.external)
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

  // Restart the walkthrough when another flow is picked.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setStep(0), [flowId])

  useEffect(() => {
    const el = boxRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setBoxWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Re-fit when the container size changes, unless the user already zoomed or panned.
  useEffect(() => {
    if (!touched.current) setView({ k: fitK, x: 0, y: 0 })
  }, [fitK])
  useEffect(() => {
    touched.current = false
    // Switching between map and circles resets the zoom on purpose.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setView({ k: fitK, x: 0, y: 0 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, unit])

  // Enter a unit (its blocks) or go back to the system (null).
  function enterUnit(id: string | null) {
    setUnit(id)
    setSelected(null)
    setImpact([])
  }
  // Select a node from a list: a block opens its unit, a node outside the entered unit goes back to the system.
  function select(id: string) {
    const p = parents.get(id)
    if (p && p !== unit) enterUnit(p)
    else if (!p && unitNodes && !unitNodes.some((n) => n.id === id)) enterUnit(null)
    setSelected(id)
  }
  // Move the walkthrough to a step; a step over the blocks of a unit enters that unit, a top-level step leaves it.
  function goToStep(i: number, steps: string[][] = walk?.steps.map((s) => s.nodes) ?? []) {
    setStep(i)
    const nodesOfStep = steps[i] ?? []
    if (nodesOfStep.length === 0) return
    const target = unitForStep(nodesOfStep, parents)
    if (target !== unit) enterUnit(target)
  }
  function pickWalk(value: string) {
    setFlowId(value)
    setRuleId('')
    goToStep(0, stepNodesOf(value))
  }

  const node = graphNodes.find((n) => n.id === selected)
  // What the inventory found, by what each unit is (a stored procedure, a table, a COBOL program...): only the kinds
  // present get a tile, and the units the code calls but the inputs do not bring are counted apart (dependencies).
  const kindCounts = Object.entries(
    topNodes
      .filter((n) => !n.external)
      .reduce<Record<string, number>>(
        (acc, n) => ({ ...acc, [n.kind || n.type]: (acc[n.kind || n.type] ?? 0) + 1 }),
        {},
      ),
  ).sort(([a], [b]) => KIND_ORDER.indexOf(a) - KIND_ORDER.indexOf(b))
  const externalCount = topNodes.filter((n) => n.external).length
  const kindLabel = (k: string) => t(`inventory.kinds.${k}`, { defaultValue: k })
  const presentTypes = TYPES.filter((ty) => (unitNodes ?? topNodes).some((n) => n.type === ty))
  const presentRelations = RELATIONS.filter((r) => drawableEdges.some((e) => (edgeGroup[e.kind] ?? 'calls') === r))
  const includedKinds = [
    ...new Set(
      graphEdges
        .filter((e) => edgeGroup[e.kind] === 'includes')
        .map((e) => graphNodes.find((n) => n.id === e.to))
        .filter((n): n is GraphNode => !!n)
        .map((n) => kindLabel(n.kind || n.type).toLowerCase()),
    ),
  ]
  const relationLabel = (r: Relation) =>
    r === 'includes' && includedKinds.length
      ? `${t('graph.relationNames.includesShort')} (${includedKinds.join(', ')})`
      : t(`graph.relationNames.${r}`)
  const orphanCount = topNodes.filter((n) => classify(n, graphEdges) !== null).length
  const topCopybook = topNodes
    .filter((n) => n.type === 'copybook' || n.type === 'file')
    .sort((a, b) => impactOf(b.id).length - impactOf(a.id).length)[0]
  const color = (n: GraphNode) =>
    n.external ? 'var(--text-muted)' : colorBy === 'domain' ? domainColor[n.domain] : stateColor[n.state]

  function toggle<T>(list: T[], v: T, set: (x: T[]) => void) {
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v])
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-3 xl:grid-cols-7">
        {kindCounts.map(([k, v]) => (
          <StatTile key={k} label={kindLabel(k)} value={v} />
        ))}
        {externalCount > 0 && (
          <button className="text-left" onClick={() => setVisibility('external')}>
            <StatTile label={t('graph.externalCalls')} value={externalCount} hint={t('graph.externalHint')} />
          </button>
        )}
        <button className="text-left" onClick={() => setVisibility('orphans')}>
          <StatTile label={t('graph.orphans')} value={orphanCount} hint={t('graph.orphansHint')} />
        </button>
      </div>

      <p className="text-sm text-text-2" aria-label={t('graph.summary.label')}>
        {[
          t('graph.summary.modules', { count: summary.modules }),
          t('graph.summary.stores', { count: summary.stores }),
          t('graph.summary.relations', { count: summary.relations }),
          t('graph.summary.entryPoints', { count: summary.entryPoints }),
        ].join(' · ')}
      </p>

      <div className="grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)_320px]">
        <div className="h-fit space-y-6">
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
                <select
                  value={flowId}
                  onChange={(e) => pickWalk(e.target.value)}
                  className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text"
                  aria-label={t('graph.flow')}
                >
                  <option value="">{t('graph.none')}</option>
                  {options.entry.length > 0 && (
                    <optgroup label={t('graph.flowGroups.entry')}>
                      {options.entry.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {options.scenario.length > 0 && (
                    <optgroup label={t('graph.flowGroups.scenario')}>
                      {options.scenario.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <p className="text-xs text-muted">{t('graph.flowHint', { count: businessFlows.length })}</p>
                {scenarios.length > 0 && (
                  <p className="text-xs text-muted">{t('graph.scenarioHint', { count: scenarios.length })}</p>
                )}
              </FilterGroup>

              <FilterGroup title={t('graph.rule')}>
                <select
                  value={ruleId}
                  onChange={(e) => (setRuleId(e.target.value), setFlowId(''))}
                  className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text"
                  aria-label={t('graph.rule')}
                >
                  <option value="">{t('graph.none')}</option>
                  {rules.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.id} · {r.name}
                    </option>
                  ))}
                </select>
              </FilterGroup>

              <FilterGroup title={t('graph.relations')}>
                {presentRelations.map((r) => (
                  <label key={r} className="flex cursor-pointer items-center gap-2 text-sm text-text">
                    <input
                      type="checkbox"
                      checked={relations.includes(r)}
                      onChange={() => toggle(relations, r, setRelations)}
                      className="accent-[var(--series-1)]"
                    />
                    <svg width="22" height="6" aria-hidden>
                      <line
                        x1="0"
                        y1="3"
                        x2="22"
                        y2="3"
                        stroke={relationStyle[r].color}
                        strokeWidth="2.5"
                        strokeDasharray={relationStyle[r].dash}
                      />
                    </svg>
                    {relationLabel(r)}
                  </label>
                ))}
              </FilterGroup>

              <FilterGroup title={t('graph.nodes')}>
                <select
                  value={visibility}
                  onChange={(e) => setVisibility(e.target.value as Visibility)}
                  className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text"
                  aria-label={t('graph.nodes')}
                >
                  <option value="all">{t('graph.visibility.all')}</option>
                  <option value="orphans">{t('graph.visibility.orphans')}</option>
                  <option value="hideOrphans">{t('graph.visibility.hideOrphans')}</option>
                  {externalCount > 0 && <option value="external">{t('graph.visibility.external')}</option>}
                  {externalCount > 0 && <option value="hideExternal">{t('graph.visibility.hideExternal')}</option>}
                </select>
                <select
                  value={domain}
                  onChange={(e) => setDomain(e.target.value as typeof domain)}
                  className="h-9 w-full rounded-md border border-border bg-surface px-2 text-sm text-text"
                  aria-label={t('inventory.domain')}
                >
                  <option value="all">{t('inventory.allDomains')}</option>
                  {domains.map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {presentTypes.map((ty) => (
                    <button
                      key={ty}
                      onClick={() => toggle(types, ty, setTypes)}
                      aria-pressed={types.includes(ty)}
                      className={cn(
                        'rounded-full border px-2 py-0.5 text-xs',
                        types.includes(ty) ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-muted',
                      )}
                    >
                      {t(`inventory.types.${ty}`)}
                    </button>
                  ))}
                </div>
              </FilterGroup>

              <FilterGroup title={t('inventory.colorBy')}>
                <div className="flex rounded-md border border-border p-0.5 text-xs" role="group">
                  {(['domain', 'state'] as const).map((c) => (
                    <button
                      key={c}
                      onClick={() => setColorBy(c)}
                      aria-pressed={colorBy === c}
                      className={cn(
                        'flex-1 rounded px-2 py-1',
                        colorBy === c ? 'bg-brand text-brand-contrast' : 'text-muted',
                      )}
                    >
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

          {/* Architect observations (model-written reading aid); hidden when there are none. */}
          {observations.length > 0 && (
            <Card className="h-fit">
              <button
                onClick={() => setObservationsOpen((o) => !o)}
                aria-expanded={observationsOpen}
                aria-controls="graph-observations"
                className="flex w-full items-center justify-between gap-2 px-5 py-4 text-left text-sm font-semibold text-text"
              >
                {t('graph.observations', { count: observations.length })}
                <ChevronDown
                  size={16}
                  className={cn('shrink-0 text-muted transition-transform', observationsOpen && 'rotate-180')}
                />
              </button>
              {observationsOpen && (
                <CardBody className="space-y-2 border-t border-border text-sm">
                  <ul id="graph-observations" className="list-disc space-y-1.5 pl-4 text-text-2">
                    {observations.map((o, i) => (
                      <li key={i}>{o}</li>
                    ))}
                  </ul>
                  <p className="text-xs text-muted">{t('graph.writtenByModel')}</p>
                </CardBody>
              )}
            </Card>
          )}
        </div>

        {/* Canvas */}
        <Card className="min-w-0">
          <CardHeader
            title={walk ? walk.name : rule ? `${rule.id} · ${rule.name}` : t('inventory.map')}
            subtitle={t('graph.stats', { nodes: nodes.length, edges: edges.length })}
            action={
              <div className="flex items-center gap-1">
                <div
                  className="mr-2 flex rounded-md border border-border p-0.5 text-xs"
                  role="group"
                  aria-label={t('graph.layout')}
                >
                  {(['circles', 'layers'] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode(m)}
                      aria-pressed={mode === m}
                      className={cn('rounded px-2 py-1', mode === m ? 'bg-brand text-brand-contrast' : 'text-muted')}
                    >
                      {t(`graph.layouts.${m}`)}
                    </button>
                  ))}
                </div>
                <IconButton
                  label={t('graph.zoomIn')}
                  onClick={() => ((touched.current = true), setView((v) => ({ ...v, k: Math.min(2.5, v.k * 1.2) })))}
                >
                  <Plus size={14} />
                </IconButton>
                <IconButton
                  label={t('graph.zoomOut')}
                  onClick={() => ((touched.current = true), setView((v) => ({ ...v, k: Math.max(0.4, v.k / 1.2) })))}
                >
                  <Minus size={14} />
                </IconButton>
                <IconButton label={t('graph.reset')} onClick={() => ((touched.current = false), setView(fit))}>
                  <Maximize2 size={14} />
                </IconButton>
              </div>
            }
          />
          {unitNode && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-2">
              <nav aria-label={t('graph.breadcrumb')} className="flex min-w-0 items-center gap-1 text-sm">
                <button
                  onClick={() => enterUnit(null)}
                  className="flex items-center gap-1 rounded px-1 text-info hover:underline"
                  title={t('graph.backToSystem')}
                >
                  <ChevronLeft size={14} aria-hidden />
                  {t('graph.breadcrumbSystem')}
                </button>
                <span className="text-muted" aria-hidden>
                  ›
                </span>
                <span className="truncate font-mono text-text" aria-current="page">
                  {unitNode.name}
                </span>
              </nav>
              {mode === 'circles' && (
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span id="graph-group-by">{t('graph.groupBy')}</span>
                  <div
                    className="flex rounded-md border border-border p-0.5"
                    role="group"
                    aria-labelledby="graph-group-by"
                  >
                    {(['domain', 'phase'] as const).map((g) => (
                      <button
                        key={g}
                        onClick={() => setGroupBy(g)}
                        aria-pressed={groupBy === g}
                        className={cn(
                          'rounded px-2 py-1',
                          groupBy === g ? 'bg-brand text-brand-contrast' : 'text-muted',
                        )}
                      >
                        {t(`graph.groupModes.${g}`)}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
          <div ref={boxRef} className="relative overflow-hidden bg-surface-2/40">
            <svg
              ref={svgRef}
              width="100%"
              height={Math.max(420, height * view.k + 50)}
              className="block cursor-grab touch-none active:cursor-grabbing"
              role="group"
              aria-label={t('inventory.map')}
              onPointerDown={(e) => {
                touched.current = true
                drag.current = { x: e.clientX - view.x, y: e.clientY - view.y }
                ;(e.target as Element).setPointerCapture?.(e.pointerId)
              }}
              onPointerMove={(e) => {
                const start = drag.current
                if (start) setView((v) => ({ ...v, x: e.clientX - start.x, y: e.clientY - start.y }))
              }}
              onPointerUp={() => (drag.current = null)}
              onClick={() => !walk && !rule && setSelected(null)}
              onKeyDown={(e) =>
                e.key === 'Escape' &&
                // Inside a unit, Esc first goes back to the system; at the top level it resets the view.
                (unit
                  ? enterUnit(null)
                  : ((touched.current = false), setView(fit), setFlowId(''), setRuleId(''), setSelected(null)))
              }
              tabIndex={0}
            >
              <defs>
                {RELATIONS.map((r) => (
                  <marker
                    key={r}
                    id={`arrow-${r}`}
                    viewBox="0 0 10 10"
                    refX="9"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse"
                  >
                    <path d="M0,0 L10,5 L0,10 z" fill={relationStyle[r].color} />
                  </marker>
                ))}
                <marker
                  id="arrow-flow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M0,0 L10,5 L0,10 z" fill="var(--text)" />
                </marker>
              </defs>
              <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
                {mode === 'circles' &&
                  packed.groups.map((g) => (
                    <g key={g.id}>
                      <circle
                        cx={g.x}
                        cy={g.y}
                        r={g.r}
                        fill={
                          g.id === 'group:data'
                            ? 'color-mix(in srgb, var(--series-3) 6%, transparent)'
                            : g.id === 'group:phase:error'
                              ? 'color-mix(in srgb, var(--critical) 6%, transparent)'
                              : g.depth === 0
                                ? 'transparent'
                                : 'color-mix(in srgb, var(--text) 3%, transparent)'
                        }
                        stroke="var(--border)"
                        strokeWidth={g.depth === 0 ? 1.5 : 1}
                      />
                      <text
                        x={g.x}
                        y={g.y - g.r + (g.depth === 0 ? 22 : 18)}
                        textAnchor="middle"
                        fontSize={g.depth === 0 ? 16 : 13}
                        fontWeight={600}
                        fill="var(--text-muted)"
                        className="pointer-events-none select-none"
                      >
                        {g.label}
                      </text>
                    </g>
                  ))}
                {edges.map((e) => {
                  const a = pos[e.from]
                  const b = pos[e.to]
                  const rel = edgeGroup[e.kind] ?? 'calls'
                  const inFlow = flowEdges.has(`${e.from}>${e.to}`)
                  const touchesSelected = !walk && !rule && !!selected && (e.from === selected || e.to === selected)
                  const dim =
                    focusActive && !inFlow && !touchesSelected && !(isFocused(e.from) && isFocused(e.to) && !selected)
                  const sameCol = a.x === b.x
                  const d =
                    mode === 'circles'
                      ? circleEdge(a as Circle, b as Circle)
                      : sameCol
                        ? `M${a.x + NODE_W / 2},${a.y} C${a.x + NODE_W / 2 + 50},${a.y} ${b.x + NODE_W / 2 + 50},${b.y} ${b.x + NODE_W / 2},${b.y}`
                        : `M${a.x + NODE_W / 2},${a.y} C${a.x + 120},${a.y} ${b.x - 120},${b.y} ${b.x - NODE_W / 2 - 4},${b.y}`
                  const label = relationLabel(rel)
                  const labelled = inFlow || touchesSelected
                  return (
                    <g key={e.from + e.to + e.kind}>
                      <path
                        d={d}
                        fill="none"
                        stroke={inFlow ? 'var(--text)' : relationStyle[rel].color}
                        strokeWidth={inFlow ? 2.5 : touchesSelected ? 2.2 : 1.3}
                        strokeDasharray={inFlow ? undefined : relationStyle[rel].dash}
                        markerEnd={`url(#arrow-${inFlow ? 'flow' : rel})`}
                        opacity={dim ? 0.12 : 0.9}
                      >
                        <title>{`${nameOf(e.from)} → ${label.toLowerCase()} → ${nameOf(e.to)}`}</title>
                      </path>
                      {labelled && (
                        <text
                          x={(a.x + b.x) / 2}
                          y={(a.y + b.y) / 2 - 4}
                          textAnchor="middle"
                          fontSize={10}
                          fontWeight={600}
                          fill="var(--text)"
                          stroke="var(--surface)"
                          strokeWidth={3}
                          paintOrder="stroke"
                          pointerEvents="none"
                        >
                          {label.toLowerCase()}
                        </text>
                      )}
                    </g>
                  )
                })}
                {nodes.map((n) => {
                  const p = pos[n.id]
                  const dim = focusActive && !isFocused(n.id)
                  const orphanKind = classify(n, graphEdges)
                  const stepNo = flowNodes.get(n.id)
                  const inStep = stepNodes.has(n.id)
                  return (
                    <g
                      key={n.id}
                      opacity={dim ? 0.2 : 1}
                      className="cursor-pointer outline-none"
                      onClick={(e) => (e.stopPropagation(), setSelected(n.id))}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        // A unit with blocks opens them; any other node zooms in as before.
                        if (childCount(n.id) > 0) return enterUnit(n.id)
                        touched.current = true
                        const k = Math.min(2.5, Math.max(view.k, 1.6))
                        setView({ k, x: boxWidth / 2 - p.x * k, y: 180 - p.y * k })
                      }}
                      onPointerDown={(e) => e.stopPropagation()}
                      role="button"
                      tabIndex={0}
                      aria-label={`${n.name} · ${t(`inventory.types.${n.type}`)}${n.schemaKnown === false ? ` · ${t('graph.noDdl')}` : ''}`}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && setSelected(n.id)}
                    >
                      {mode === 'circles' ? (
                        <CircleNode
                          node={n}
                          p={p as Circle}
                          color={impact.includes(n.id) ? 'var(--critical)' : color(n)}
                          strong={selected === n.id || inStep}
                          dashed={!!orphanKind || n.external}
                          stepNo={stepNo}
                          noDdl={n.schemaKnown === false}
                          noDdlLabel={t('graph.noDdlHint')}
                        />
                      ) : (
                        <>
                          <rect
                            x={p.x - NODE_W / 2}
                            y={p.y - NODE_H / 2}
                            width={NODE_W}
                            height={NODE_H}
                            rx={n.type === 'transaction' ? NODE_H / 2 : 6}
                            fill={
                              impact.includes(n.id)
                                ? 'color-mix(in srgb, var(--critical) 12%, var(--surface))'
                                : 'var(--surface)'
                            }
                            stroke={impact.includes(n.id) ? 'var(--critical)' : color(n)}
                            strokeWidth={selected === n.id || inStep ? 3.5 : 2}
                            strokeDasharray={orphanKind || n.external ? '5 3' : undefined}
                          />
                          <text
                            x={p.x}
                            y={p.y - 3}
                            textAnchor="middle"
                            fontSize={11}
                            fontWeight={600}
                            fill="var(--text)"
                          >
                            {n.name}
                          </text>
                          <text x={p.x} y={p.y + 11} textAnchor="middle" fontSize={9} fill="var(--text-muted)">
                            {orphanKind
                              ? t(`graph.kind.${orphanKind}`)
                              : n.external
                                ? t('graph.externalShort')
                                : t(`inventory.types.${n.type}`)}
                          </text>
                          {n.schemaKnown === false && (
                            <NoDdlMarker
                              x={p.x + NODE_W / 2 - 2}
                              y={p.y - NODE_H / 2 - 2}
                              label={t('graph.noDdlHint')}
                            />
                          )}
                          {stepNo && (
                            <g>
                              <circle
                                cx={p.x - NODE_W / 2 + 2}
                                cy={p.y - NODE_H / 2 - 2}
                                r={10}
                                fill="var(--brand)"
                                stroke="var(--surface)"
                                strokeWidth={2}
                              />
                              <text
                                x={p.x - NODE_W / 2 + 2}
                                y={p.y - NODE_H / 2 + 2}
                                textAnchor="middle"
                                fontSize={10}
                                fontWeight={700}
                                fill="var(--brand-contrast)"
                              >
                                {stepNo}
                              </text>
                            </g>
                          )}
                        </>
                      )}
                    </g>
                  )
                })}
              </g>
            </svg>
            <p className="pointer-events-none absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted">
              {t('graph.help')}
            </p>
          </div>
        </Card>

        {/* Side panel: flow walkthrough, rule focus or node detail */}
        <Card className="h-fit">
          {walk ? (
            <>
              <CardHeader
                title={walk.name}
                subtitle={flow ? t('graph.entryPoint', { entry: nameOf(flow.entry) }) : t('graph.scenario')}
                action={
                  <button
                    onClick={() => setFlowId('')}
                    className="rounded p-1 text-muted hover:text-text"
                    aria-label={t('common.close')}
                  >
                    <X size={16} />
                  </button>
                }
              />
              <CardBody className="space-y-4 text-sm">
                {flow && (
                  <p className="text-text-2">
                    {t('graph.flowSummary', { steps: flow.steps.length, rules: flow.rules.length })}
                  </p>
                )}
                {scenario && (
                  <div className="space-y-1">
                    {scenario.persona && (
                      <p className="text-xs font-medium text-text">
                        {t('graph.persona', { persona: scenario.persona })}
                      </p>
                    )}
                    {scenario.summary && <p className="text-text-2">{scenario.summary}</p>}
                    <p className="text-xs text-muted">{t('graph.writtenByModel')}</p>
                  </div>
                )}
                <div className="text-xs font-medium tracking-wide text-muted uppercase">{t('graph.steps')}</div>
                <ol className="space-y-1">
                  {walk.steps.map((s, i) => (
                    <li key={i}>
                      <button
                        onClick={() => goToStep(i)}
                        className={cn(
                          'flex w-full gap-3 rounded-md p-2 text-left',
                          step === i ? 'bg-brand/10 dark:bg-accent/10' : 'hover:bg-surface-2',
                        )}
                      >
                        <span
                          className={cn(
                            'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                            step === i ? 'bg-brand text-brand-contrast' : 'bg-surface-2 text-muted',
                          )}
                        >
                          {i + 1}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-text">{s.title || '—'}</span>
                          <span className="block font-mono text-xs text-muted">{s.nodes.map(nameOf).join(' → ')}</span>
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
                  <Button size="sm" variant="ghost" disabled={step === 0} onClick={() => goToStep(step - 1)}>
                    <ChevronLeft size={14} /> {t('common.back')}
                  </Button>
                  <Button size="sm" disabled={step >= walk.steps.length - 1} onClick={() => goToStep(step + 1)}>
                    {t('common.next')} <ChevronRight size={14} />
                  </Button>
                </div>
              </CardBody>
            </>
          ) : rule ? (
            <>
              <CardHeader title={`${rule.id} · ${rule.name}`} subtitle={rule.priority} />
              <CardBody className="space-y-3 text-sm">
                <div className="text-xs text-muted">{t('graph.implementedIn')}</div>
                <div className="flex flex-wrap gap-1.5">
                  {graphNodes
                    .filter((n) => n.rules.includes(rule.id))
                    .map((n) => (
                      <button
                        key={n.id}
                        onClick={() => select(n.id)}
                        className="rounded border border-border px-2 py-0.5 font-mono text-xs text-text hover:bg-surface-2"
                      >
                        {n.name}
                      </button>
                    ))}
                </div>
                <div className="text-xs text-muted">{t('graph.inFlows')}</div>
                <ul className="space-y-1">
                  {businessFlows
                    .filter((f) => f.rules.includes(rule.id))
                    .map((f) => (
                      <li key={f.id}>
                        <button
                          onClick={() => (setRuleId(''), pickWalk(f.id))}
                          className="text-left text-info hover:underline"
                        >
                          {f.name}
                        </button>
                      </li>
                    ))}
                  {scenarios
                    .filter((sc) => sc.rules.includes(rule.id))
                    .map((sc) => (
                      <li key={`${SCENARIO_PREFIX}${sc.id}`}>
                        <button
                          onClick={() => pickWalk(`${SCENARIO_PREFIX}${sc.id}`)}
                          className="text-left text-info hover:underline"
                        >
                          {sc.name}
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
              edges={drawableEdges}
              nameOf={nameOf}
              onSelect={select}
              description={insights?.descriptions[node.id]}
              blocks={childCount(node.id)}
              onEnter={() => enterUnit(node.id)}
              onCompare={onCompare}
              impact={impact}
              onImpact={() => showImpact(node.id)}
              onClearImpact={() => setImpact([])}
            />
          ) : (
            <CardBody className="space-y-3 text-sm text-text-2">
              <p>{t('graph.emptyPanel')}</p>
              {businessFlows.length > 0 && (
                <Button size="sm" onClick={() => pickWalk(businessFlows[0].id)}>
                  {t('graph.tryFlow')}
                </Button>
              )}
            </CardBody>
          )}
        </Card>
      </div>

      <Card>
        <CardHeader title={t('inventory.impact')} subtitle={t('inventory.impactHint')} />
        <CardBody className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={!topCopybook}
              onClick={() => topCopybook && (select(topCopybook.id), showImpact(topCopybook.id), setOrder(null))}
            >
              {t('inventory.impactCopybook', { name: topCopybook?.name ?? '—' })}
            </Button>
            <Button
              size="sm"
              disabled={domains.length === 0}
              onClick={() => (setDomain(domains[0]), setImpact([]), setOrder(null))}
            >
              {t('inventory.impactDomain', { domain: domains[0] ?? '—' })}
            </Button>
            <Button size="sm" onClick={() => (setOrder(migrationOrder()), setImpact([]))}>
              {t('inventory.impactOrder')}
            </Button>
            <Button
              size="sm"
              onClick={() => (
                setVisibility('all'),
                setImpact(graphNodes.filter((n) => n.type === 'program' && n.rules.length === 0).map((n) => n.id)),
                setOrder(null)
              )}
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
                    <button
                      onClick={() => select(id)}
                      className="rounded-md border border-border px-2 py-1 font-mono text-text hover:bg-surface-2"
                    >
                      {i + 1}. {nameOf(id)}
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
  edges,
  nameOf,
  onSelect,
  onCompare,
  impact,
  onImpact,
  onClearImpact,
  description,
  blocks = 0,
  onEnter,
}: {
  node: GraphNode
  edges: GraphEdge[]
  nameOf: (id: string) => string
  onSelect: (id: string) => void
  onCompare: (r: string) => void
  impact: string[]
  onImpact: () => void
  onClearImpact: () => void
  /** The model-written description (ADR-0032), when the run had the deep inventory. */
  description?: string
  /** How many blocks the unit has: with any, the panel offers to enter it. */
  blocks?: number
  onEnter?: () => void
}) {
  const { t } = useTranslation()
  const outgoing = edges.filter((e) => e.from === node.id)
  const incoming = edges.filter((e) => e.to === node.id)
  const kind = classify(node, edges)
  const connections = [
    ...outgoing.map((e) => ({ dir: 'out' as const, id: e.to, kind: e.kind })),
    ...incoming.map((e) => ({ dir: 'in' as const, id: e.from, kind: e.kind })),
  ]
  return (
    <>
      <CardHeader
        title={node.name}
        subtitle={`${t(`inventory.types.${node.type}`)} · ${node.domain}${node.external ? ` · ${t('graph.external')}` : ''}`}
        action={kind ? <Badge tone="warning">{t(`graph.kind.${kind}`)}</Badge> : undefined}
      />
      <CardBody className="space-y-4 text-sm">
        {description ? (
          <div className="space-y-1">
            <p className="whitespace-pre-line text-text-2">{description}</p>
            <p className="text-xs text-muted">{t('graph.writtenByModel')}</p>
          </div>
        ) : (
          <p className="text-xs text-muted">{t('graph.noDescription')}</p>
        )}
        {node.schemaKnown === false && <p className="text-xs text-warning-ink">{t('graph.noDdlHint')}</p>}
        {kind && <p className="text-xs text-warning-ink">{t(`graph.kindHint.${kind}`)}</p>}
        <div className="flex flex-wrap gap-1.5">
          <Badge>{t('graph.fanIn', { count: incoming.length })}</Badge>
          <Badge>{t('graph.fanOut', { count: outgoing.length })}</Badge>
          <Badge tone={node.state === 'verified' ? 'good' : node.state === 'pending' ? 'neutral' : 'info'}>
            {t(`inventory.states.${node.state}`)}
          </Badge>
          {node.loc && <Badge>{t('graph.loc', { count: node.loc })}</Badge>}
          {node.schemaKnown === false && <Badge tone="warning">{t('graph.noDdl')}</Badge>}
          {node.phase && <Badge>{t(`graph.phases.${phaseOf(node)}`)}</Badge>}
        </div>
        {blocks > 0 && onEnter && (
          <Button size="sm" className="w-full" onClick={onEnter}>
            <Layers size={14} /> {t('graph.viewBlocks', { count: blocks })}
          </Button>
        )}
        {node.source && (
          <div>
            <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('graph.source')}</div>
            <p className="font-mono text-xs text-text">{node.source}</p>
          </div>
        )}
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">{t('inventory.target')}</div>
          <p className="font-mono text-xs text-text">—</p>
        </div>
        <div>
          <div className="mb-1 text-xs font-medium tracking-wide text-muted uppercase">
            {t('graph.connections', { count: connections.length })}
          </div>
          {connections.length === 0 ? (
            <p className="text-xs text-muted">—</p>
          ) : (
            <ul className="space-y-0.5">
              {connections.map((c) => (
                <li key={c.dir + c.id + c.kind}>
                  <button
                    onClick={() => onSelect(c.id)}
                    className="flex w-full items-baseline gap-2 rounded px-1.5 py-1 text-left hover:bg-surface-2"
                  >
                    <span className="text-info" aria-label={t(`graph.dir.${c.dir}`)}>
                      {c.dir === 'out' ? '→' : '←'}
                    </span>
                    <span className="font-mono text-xs text-info">{nameOf(c.id)}</span>
                    <span className="ml-auto text-[10px] text-muted">{t(`graph.edgeKinds.${c.kind}`)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <Relations
          title={t('inventory.uses')}
          items={outgoing.map((e) => ({ id: e.to, kind: e.kind }))}
          nameOf={nameOf}
          onSelect={onSelect}
        />
        <Relations
          title={t('inventory.usedBy')}
          items={incoming.map((e) => ({ id: e.from, kind: e.kind }))}
          nameOf={nameOf}
          onSelect={onSelect}
        />
        <div className="space-y-2 border-t border-border pt-3">
          <Button size="sm" className="w-full" onClick={onImpact}>
            {t('inventory.showImpact')}
          </Button>
          {impact.length > 0 && (
            <p className="text-xs text-critical-ink">
              {t('inventory.impactResult', { count: impact.length, items: impact.map(nameOf).join(', ') })}{' '}
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
                <button
                  key={r}
                  onClick={() => onCompare(r)}
                  className="rounded-md border border-border px-2 py-0.5 font-mono text-xs text-info hover:bg-surface-2"
                >
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

function Relations({
  title,
  items,
  nameOf,
  onSelect,
}: {
  title: string
  items: { id: string; kind: string }[]
  nameOf: (id: string) => string
  onSelect: (id: string) => void
}) {
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
              <button
                onClick={() => onSelect(i.id)}
                className="flex w-full items-center justify-between rounded px-1.5 py-0.5 text-left hover:bg-surface-2"
              >
                <span className="font-mono text-xs text-text">{nameOf(i.id)}</span>
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
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      className="rounded-md border border-border p-1.5 text-muted hover:bg-surface-2 hover:text-text"
    >
      {children}
    </button>
  )
}

type Circle = { x: number; y: number; r: number }

// Curved edge between two circles, bent toward the centre of the pack so bundles read as arcs.
function circleEdge(a: Circle, b: Circle) {
  const c = PACK_SIZE / 2
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2
  const cx = mx + (c - mx) * 0.35
  const cy = my + (c - my) * 0.35
  const trim = (from: { x: number; y: number }, to: Circle) => {
    const dx = from.x - to.x
    const dy = from.y - to.y
    const len = Math.hypot(dx, dy) || 1
    return { x: to.x + (dx / len) * (to.r + 3), y: to.y + (dy / len) * (to.r + 3) }
  }
  const start = trim({ x: cx, y: cy }, a)
  const end = trim({ x: cx, y: cy }, b)
  return `M${start.x},${start.y} Q${cx},${cy} ${end.x},${end.y}`
}

function CircleNode({
  node,
  p,
  color,
  strong,
  dashed,
  stepNo,
  noDdl = false,
  noDdlLabel = '',
}: {
  node: GraphNode
  p: Circle
  color: string
  strong: boolean
  dashed: boolean
  stepNo?: number
  /** A table known only from the code (no DDL in the inputs) gets a small marker. */
  noDdl?: boolean
  noDdlLabel?: string
}) {
  const inside = p.r >= 26
  const maxChars = Math.max(4, Math.floor((p.r * 2) / 7))
  const label = node.name.length > maxChars ? `${node.name.slice(0, maxChars - 1)}…` : node.name
  return (
    <>
      <circle
        cx={p.x}
        cy={p.y}
        r={p.r}
        fill={`color-mix(in srgb, ${color} ${strong ? 38 : 24}%, var(--surface))`}
        stroke={color}
        strokeWidth={strong ? 3.5 : 1.5}
        strokeDasharray={dashed ? '5 3' : undefined}
      />
      <text
        x={p.x}
        y={inside ? p.y + 4 : p.y + p.r + 12}
        textAnchor="middle"
        fontSize={inside ? Math.min(13, Math.max(10, p.r / 3.2)) : 10}
        fontWeight={600}
        fill="var(--text)"
        className="pointer-events-none select-none"
      >
        {inside ? label : node.name}
      </text>
      {stepNo && (
        <g>
          <circle
            cx={p.x - p.r * 0.72}
            cy={p.y - p.r * 0.72}
            r={10}
            fill="var(--brand)"
            stroke="var(--surface)"
            strokeWidth={2}
          />
          <text
            x={p.x - p.r * 0.72}
            y={p.y - p.r * 0.72 + 4}
            textAnchor="middle"
            fontSize={10}
            fontWeight={700}
            fill="var(--brand-contrast)"
          >
            {stepNo}
          </text>
        </g>
      )}
      {noDdl && <NoDdlMarker x={p.x + p.r * 0.72} y={p.y - p.r * 0.72} label={noDdlLabel} />}
    </>
  )
}

// The marker of a table without DDL: a small warning dot with a question mark and the explanation as a tooltip.
function NoDdlMarker({ x, y, label }: { x: number; y: number; label: string }) {
  return (
    <g>
      <title>{label}</title>
      <circle cx={x} cy={y} r={8} fill="var(--warning)" stroke="var(--surface)" strokeWidth={2} />
      <text x={x} y={y + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill="var(--surface)">
        ?
      </text>
    </g>
  )
}
