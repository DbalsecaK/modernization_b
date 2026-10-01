import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle2, CircleDashed, Download, Loader2, ShieldCheck, XCircle } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { ApiError } from '@/api/client'
import type { ProjectDetail } from '@/api/projects'
import { CODE_VIEW, proofPackUrl, useVerdicts, type VerdictOut } from '@/api/validation'
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Table, Td, Th } from '@/components/ui/primitives'
import { VerdictBadge } from '@/components/ui/status'
import { HardeningCard } from './delivery/DeliveryCards'
import {
  allChecks,
  byModule,
  checkStatusKey,
  checkTitleKey,
  checkTone,
  passedCount,
  toVerdict,
  type CheckStatus,
  type ModuleVerdicts,
} from './validation/model'

const LIMITS = ['samples', 'masks', 'unextracted', 'nonFunctional', 'signoff'] as const

const statusIcon: Record<CheckStatus, typeof CheckCircle2> = {
  passed: CheckCircle2,
  failed: XCircle,
  not_checked: AlertTriangle,
}
const iconColor: Record<CheckStatus, string> = {
  passed: 'text-good',
  failed: 'text-critical',
  not_checked: 'text-warning',
}

// Validation tab (spec 11.3, 18.x), connected to the API: per module, the newest verdict the worker computed by code
// with its six checks, what it does not prove and its proof pack; older verdicts below. PROVEN is evidence, not
// approval: a person signs off at gate C4 in the Runs tab. Same look as the prototype's ValidationTab.
export function ProjectValidation({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const verdicts = useVerdicts(project.id)
  const canViewCode = project.permissions.includes(CODE_VIEW)

  if (verdicts.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('validation.loading')}
      </p>
    )
  }
  if (verdicts.isError) {
    return (
      <EmptyState
        title={t('validation.loadError')}
        description={verdicts.error instanceof ApiError ? verdicts.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void verdicts.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  const modules = byModule(verdicts.data ?? [])
  if (modules.length === 0) {
    return (
      <EmptyState
        title={t('validation.emptyTitle')}
        description={t('validation.notYet')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const history = modules.flatMap((m) => m.history).sort((a, b) => b.createdAt.localeCompare(a.createdAt))

  return (
    <div className="space-y-6">
      {modules.map((m) => (
        <ModuleVerdict key={m.module} group={m} projectId={project.id} canViewCode={canViewCode} />
      ))}

      <HardeningCard projectId={project.id} />

      <Card>
        <CardHeader title={t('validation.signoff')} subtitle={t('validation.signoffHint')} />
        <CardBody className="flex flex-wrap items-center gap-3 text-sm">
          <ShieldCheck size={16} className="shrink-0 text-muted" />
          <p className="min-w-0 flex-1 text-text-2">{t('validation.signoffInRuns')}</p>
          <Button size="sm" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        </CardBody>
      </Card>

      {history.length > 0 && (
        <Card>
          <CardHeader title={t('validation.history')} subtitle={t('validation.historyHint')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('validation.when')}</Th>
                <Th>{t('validation.module')}</Th>
                <Th>{t('validation.verdict')}</Th>
                <Th>{t('validation.checksPassed')}</Th>
                <Th>{t('validation.run')}</Th>
                <Th>
                  <span className="sr-only">{t('validation.proofPack')}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {history.map((v) => (
                <tr key={v.id}>
                  <Td className="text-xs whitespace-nowrap">{formatDateTime(v.createdAt)}</Td>
                  <Td className="text-xs">{v.module}</Td>
                  <Td>
                    <VerdictBadge verdict={toVerdict(v.verdict)} />
                  </Td>
                  <Td className="text-xs">
                    {t('validation.passedOf', { passed: passedCount(v), total: v.checks.length })}
                  </Td>
                  <Td className="font-mono text-xs">{v.runId.slice(0, 8)}</Td>
                  <Td>
                    {v.hasProofPack && canViewCode && (
                      <a
                        href={proofPackUrl(project.id, v.id)}
                        download
                        className="inline-flex items-center gap-1 text-xs text-info-ink hover:underline"
                      >
                        <Download size={12} aria-hidden /> {t('validation.downloadShort')}
                        <span className="sr-only">
                          {' '}
                          {t('validation.proofPackOf', { module: v.module, date: formatDateTime(v.createdAt) })}
                        </span>
                      </a>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </div>
  )
}

function ModuleVerdict({
  group,
  projectId,
  canViewCode,
}: {
  group: ModuleVerdicts
  projectId: string
  canViewCode: boolean
}) {
  const { t } = useTranslation()
  const v: VerdictOut = group.latest
  return (
    <section className="space-y-6" aria-label={t('validation.moduleVerdict', { module: group.module })}>
      <Card>
        <CardHeader
          title={
            <span>
              {t('validation.verdict')} · <span className="font-mono">{group.module}</span>
            </span>
          }
          subtitle={
            <>
              {t('validation.computedByCode')}{' '}
              <span className="whitespace-nowrap">
                {t('validation.computedOn', { date: formatDateTime(v.createdAt), run: v.runId.slice(0, 8) })}
              </span>
            </>
          }
          action={<VerdictBadge verdict={toVerdict(v.verdict)} />}
        />
        <CardBody className="space-y-3">
          <ul className="space-y-3" aria-label={t('validation.checksOf', { module: group.module })}>
            {allChecks(v.checks, v.module).map((c) => {
              const Icon = c.missing ? CircleDashed : statusIcon[c.status]
              return (
                <li key={c.key} className="flex items-start gap-3 rounded-md border border-border p-3">
                  <Icon size={16} className={`mt-0.5 shrink-0 ${iconColor[c.status]}`} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-text">
                      {t(checkTitleKey(c.key), { defaultValue: c.title })}
                    </div>
                    <div className="text-sm break-words text-text-2">
                      {c.missing ? t('validation.checkNotRun') : c.detail}
                    </div>
                  </div>
                  <Badge tone={checkTone(c.status)}>{t(checkStatusKey(c.status))}</Badge>
                </li>
              )
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-3 pt-1">
            {v.hasProofPack && canViewCode && (
              <a
                href={proofPackUrl(projectId, v.id)}
                download
                className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3 text-sm font-medium text-text hover:bg-surface-2"
              >
                <Download size={16} aria-hidden /> {t('validation.downloadProofPack')}
              </a>
            )}
            <span className="text-xs text-muted">
              {!v.hasProofPack
                ? t('validation.noProofPack')
                : canViewCode
                  ? t('validation.proofPackHint')
                  : t('validation.proofPackNeedsCode')}
            </span>
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title={t('validation.doesNotProve')} subtitle={t('validation.doesNotProveHint')} />
        <CardBody className="grid gap-4 md:grid-cols-2">
          <div>
            <h4 className="mb-1.5 text-xs font-medium text-muted">{t('validation.thisVerdict')}</h4>
            {v.notProven.length === 0 ? (
              <p className="text-sm text-muted">{t('validation.nothingListed')}</p>
            ) : (
              <ul className="list-disc space-y-1.5 pl-5 text-sm break-words text-text-2">
                {v.notProven.map((note, i) => (
                  <li key={i}>{note}</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h4 className="mb-1.5 text-xs font-medium text-muted">{t('validation.anyVerdict')}</h4>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-text-2">
              {LIMITS.map((k) => (
                <li key={k}>{t(`validation.limits.${k}`)}</li>
              ))}
            </ul>
          </div>
        </CardBody>
      </Card>
    </section>
  )
}
