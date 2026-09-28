// Deterministic migration plan (spec 5.2, 7.7). The platform suggests waves from the story dependencies taken
// from the knowledge graph; people may reorder them and every change is checked here, never by a model.

export interface PlanStory {
  id: string
  priority: 'P0' | 'P1' | 'P2'
  points: number
  dependsOn: { story: string; kind: 'hard' | 'soft'; reason: string }[]
}

export type Plan = string[][]

export interface PlanIssue {
  story: string
  dependency: string
  kind: 'hard' | 'soft'
  // before: the dependency is planned in a later wave; missing: it is not in the plan (discarded or not planned).
  problem: 'before' | 'missing'
  reason: string
}

const rank = { P0: 0, P1: 1, P2: 2 }

// Wave = length of the longest dependency chain (hard and soft), so every story comes after what it needs.
// Inside a wave: priority first, then fewer points first. Cycles are cut and reported as issues by validatePlan.
export function suggestPlan(stories: PlanStory[]): Plan {
  const byId = new Map(stories.map((s) => [s.id, s]))
  const level = new Map<string, number>()
  const visit = (id: string, path: Set<string>): number => {
    if (level.has(id)) return level.get(id)!
    const s = byId.get(id)
    if (!s || path.has(id)) return -1
    path.add(id)
    const deps = s.dependsOn.filter((d) => byId.has(d.story)).map((d) => visit(d.story, path))
    path.delete(id)
    const l = deps.length ? Math.max(...deps) + 1 : 0
    level.set(id, l)
    return l
  }
  stories.forEach((s) => visit(s.id, new Set()))
  const waves: Plan = []
  stories.forEach((s) => {
    const l = level.get(s.id)!
    ;(waves[l] ??= []).push(s.id)
  })
  return waves
    .filter(Boolean)
    .map((w) => w.sort((a, b) => rank[byId.get(a)!.priority] - rank[byId.get(b)!.priority] || byId.get(a)!.points - byId.get(b)!.points || a.localeCompare(b)))
}

export function waveOf(plan: Plan, id: string): number {
  return plan.findIndex((w) => w.includes(id))
}

// A story may share a wave with its dependency (they are built together) but never come before it.
export function validatePlan(plan: Plan, stories: PlanStory[]): PlanIssue[] {
  const issues: PlanIssue[] = []
  plan.forEach((wave, w) =>
    wave.forEach((id) => {
      const s = stories.find((x) => x.id === id)
      s?.dependsOn.forEach((d) => {
        const dw = waveOf(plan, d.story)
        if (dw === -1) issues.push({ story: id, dependency: d.story, kind: d.kind, problem: 'missing', reason: d.reason })
        else if (dw > w) issues.push({ story: id, dependency: d.story, kind: d.kind, problem: 'before', reason: d.reason })
      })
    }),
  )
  return issues
}

// Moves a story. A move that creates a new hard dependency problem is rejected; soft ones are allowed with a
// warning (a temporary ACL or stub covers the gap, strangler fig).
export function moveStory(plan: Plan, stories: PlanStory[], id: string, toWave: number, index?: number): { plan: Plan; accepted: boolean; newIssues: PlanIssue[] } {
  const next = plan.map((w) => w.filter((x) => x !== id))
  while (next.length <= toWave) next.push([])
  const target = next[toWave]
  target.splice(index === undefined ? target.length : Math.max(0, Math.min(index, target.length)), 0, id)
  const key = (i: PlanIssue) => `${i.story}>${i.dependency}:${i.problem}`
  const before = new Set(validatePlan(plan, stories).map(key))
  const newIssues = validatePlan(next, stories).filter((i) => !before.has(key(i)))
  const accepted = !newIssues.some((i) => i.kind === 'hard')
  return { plan: accepted ? next : plan, accepted, newIssues }
}

// Stories whose wave differs from the suggestion (the plan shows "suggested vs yours").
export function planDiff(suggested: Plan, current: Plan): { story: string; from: number; to: number }[] {
  return current
    .flatMap((w, i) => w.map((id) => ({ story: id, from: waveOf(suggested, id), to: i })))
    .filter((d) => d.from !== d.to)
}
