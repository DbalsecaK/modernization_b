import { describe, expect, it } from 'vitest'
import type { Dashboard, DashboardProject } from '@/api/dashboard'
import { adminAlerts, progressOf, risks, runPhaseStatus, totals } from './model'

const project = (extra: Partial<DashboardProject>): DashboardProject => ({
  id: 'p',
  name: 'Payments',
  runStatus: null,
  currentPhase: null,
  waitingReason: null,
  phasesDone: 0,
  phasesTotal: 0,
  rulesTotal: 0,
  rulesVerified: 0,
  verdict: null,
  spentUsd: null,
  budgetUsd: null,
  ...extra,
})

const board = (projects: DashboardProject[], extra: Partial<Dashboard> = {}): Dashboard => ({
  costVisible: true,
  projects,
  monthlySpend: [],
  delivery: { running: 0, gatesWaiting: 0, escalations: 0, tokensToday: 0, costTodayUsd: null },
  admin: null,
  ...extra,
})

describe('dashboard model', () => {
  it('maps run statuses to phase icons and phases to progress', () => {
    expect(['running', 'waiting', 'succeeded', 'failed', null].map(runPhaseStatus)).toEqual([
      'running',
      'waiting',
      'done',
      'failed',
      'pending',
    ])
    expect(progressOf(project({ phasesDone: 3, phasesTotal: 4 }))).toBe(75)
    expect(progressOf(project({}))).toBe(0)
  })

  it('adds up rules, PROVEN projects and money only when money is visible', () => {
    const projects = [
      project({ rulesTotal: 10, rulesVerified: 4, verdict: 'PROVEN', spentUsd: '1.5', budgetUsd: '10' }),
      project({ runStatus: 'succeeded', rulesTotal: 5, rulesVerified: 5, spentUsd: '0.5' }),
    ]
    expect(totals(board(projects))).toEqual({
      active: 1,
      rulesTotal: 15,
      rulesVerified: 9,
      proven: 1,
      spent: 2,
      budget: 10,
    })
    expect(totals(board(projects, { costVisible: false })).spent).toBeNull()
  })

  it('lists escalations, budgets at 80% or more, unproven verdicts and waiting gates', () => {
    const found = risks(
      board(
        [
          project({ name: 'A', spentUsd: '9', budgetUsd: '10' }),
          project({ name: 'B', waitingReason: 'escalation', verdict: 'PARTLY PROVEN' }),
          project({ name: 'C', spentUsd: '1', budgetUsd: '10', verdict: 'PROVEN' }),
        ],
        { delivery: { running: 0, gatesWaiting: 2, escalations: 1, tokensToday: 0, costTodayUsd: null } },
      ),
    )
    expect(found).toEqual([
      { kind: 'escalation', project: 'B' },
      { kind: 'budget', project: 'A', pct: 90 },
      { kind: 'partly', project: 'B', verdict: 'PARTLY_PROVEN' },
      { kind: 'gates', count: 2 },
    ])
  })

  it('alerts the administrator of failed connections and crossed budgets', () => {
    expect(
      adminAlerts({
        activeUsers: 3,
        pendingInvitations: 0,
        connections: [
          { name: 'OpenRouter', provider: 'openrouter', status: 'ok' },
          { name: 'Azure', provider: 'azure', status: 'failed' },
        ],
        budgetAlerts: [{ projectName: 'Payments', level: 80, amountUsd: '5' }],
      }),
    ).toEqual([
      { kind: 'connection', name: 'Azure' },
      { kind: 'budget', project: 'Payments', level: 80 },
    ])
  })
})
