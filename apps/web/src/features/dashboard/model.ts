import type { AdminSummary, Dashboard, DashboardProject } from '@/api/dashboard'
import type { PhaseStatus } from '@/mocks/types'
import { toVerdict } from '@/features/projects/workspace/validation/model'

const amount = (value: string | number | null | undefined) => (value == null ? null : Number(value))

/** The newest run's status as the phase icon shows it; a project without runs has not started. */
export function runPhaseStatus(status: string | null | undefined): PhaseStatus {
  if (status === 'running' || status === 'queued') return 'running'
  if (status === 'waiting') return 'waiting'
  if (status === 'succeeded') return 'done'
  if (status === 'failed' || status === 'cancelled') return 'failed'
  return 'pending'
}

/** Share of the newest run's phases that finished (succeeded or skipped), 0 to 100. */
export const progressOf = (p: DashboardProject) =>
  p.phasesTotal > 0 ? Math.round((p.phasesDone / p.phasesTotal) * 100) : 0

/** A project is active until its newest run succeeds. */
export const isActive = (p: DashboardProject) => p.runStatus !== 'succeeded'

export interface Totals {
  active: number
  rulesTotal: number
  rulesVerified: number
  proven: number
  spent: number | null
  budget: number | null
}

export function totals(board: Dashboard): Totals {
  const sum = (pick: (p: DashboardProject) => number | null) =>
    board.costVisible ? board.projects.reduce((s, p) => s + (pick(p) ?? 0), 0) : null
  return {
    active: board.projects.filter(isActive).length,
    rulesTotal: board.projects.reduce((s, p) => s + p.rulesTotal, 0),
    rulesVerified: board.projects.reduce((s, p) => s + p.rulesVerified, 0),
    proven: board.projects.filter((p) => p.verdict === 'PROVEN').length,
    spent: sum((p) => amount(p.spentUsd)),
    budget: sum((p) => amount(p.budgetUsd)),
  }
}

export type Risk =
  | { kind: 'budget'; project: string; pct: number }
  | { kind: 'escalation'; project: string }
  | { kind: 'gates'; count: number }
  | { kind: 'partly'; project: string; verdict: string }

/** What needs attention, most serious first: escalations, budgets at 80% or more, unproven verdicts, waiting gates. */
export function risks(board: Dashboard): Risk[] {
  const out: Risk[] = []
  for (const p of board.projects)
    if (p.waitingReason === 'escalation') out.push({ kind: 'escalation', project: p.name })
  for (const p of board.projects) {
    const spent = amount(p.spentUsd)
    const budget = amount(p.budgetUsd)
    if (spent != null && budget) {
      const pct = Math.round((spent / budget) * 100)
      if (pct >= 80) out.push({ kind: 'budget', project: p.name, pct })
    }
  }
  for (const p of board.projects) {
    const verdict = toVerdict(p.verdict)
    if (verdict === 'PARTLY_PROVEN' || verdict === 'NOT_PROVEN') out.push({ kind: 'partly', project: p.name, verdict })
  }
  if (board.delivery.gatesWaiting > 0) out.push({ kind: 'gates', count: board.delivery.gatesWaiting })
  return out
}

export type Alert = { kind: 'connection'; name: string } | { kind: 'budget'; project: string | null; level: number }

/** The administrator's alerts: AI connections whose last check failed and budgets that crossed a threshold. */
export function adminAlerts(admin: AdminSummary): Alert[] {
  return [
    ...admin.connections.filter((c) => c.status === 'failed').map((c): Alert => ({ kind: 'connection', name: c.name })),
    ...admin.budgetAlerts.map((a): Alert => ({ kind: 'budget', project: a.projectName ?? null, level: a.level })),
  ]
}
