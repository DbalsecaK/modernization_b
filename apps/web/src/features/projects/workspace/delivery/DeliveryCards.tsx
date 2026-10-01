import { useTranslation } from 'react-i18next'
import { GitBranch, Loader2, ShieldAlert, ShieldCheck } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { severityCounts, useHardening, useReleases, type Release } from '@/api/delivery'
import { Badge, Card, CardBody, CardHeader, EmptyState, Table, Td, Th } from '@/components/ui/primitives'

const SEVERITY_TONE = { critical: 'critical', high: 'critical', medium: 'warning', low: 'neutral' } as const
const RELEASE_TONE = { pushed: 'good', failed: 'critical', ready: 'info' } as const

/** The hardening report of the newest generation (spec 6.1 phase 12, ADR-0023): what was checked and what was found. */
export function HardeningCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const report = useHardening(projectId)
  if (report.isLoading) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('delivery.loading')}
      </p>
    )
  }
  if (!report.data) {
    return (
      <Card>
        <CardHeader title={t('delivery.hardening')} subtitle={t('delivery.hardeningHint')} />
        <CardBody>
          <p className="text-sm text-muted">{t('delivery.noHardening')}</p>
        </CardBody>
      </Card>
    )
  }
  const data = report.data
  const counts = severityCounts(data)
  return (
    <Card>
      <CardHeader
        title={t('delivery.hardening')}
        subtitle={t('delivery.hardeningAt', { date: formatDateTime(data.generatedAt) })}
        action={
          <div className="flex flex-wrap gap-1">
            {counts.length === 0 ? (
              <Badge tone="good">
                <ShieldCheck size={12} aria-hidden /> {t('delivery.noFindings')}
              </Badge>
            ) : (
              counts.map((c) => (
                <Badge key={c.severity} tone={SEVERITY_TONE[c.severity as keyof typeof SEVERITY_TONE]}>
                  {t(`delivery.severity.${c.severity}`)}: {c.count}
                </Badge>
              ))
            )}
          </div>
        }
      />
      <CardBody className="space-y-3">
        <ul className="grid gap-2 text-sm sm:grid-cols-2">
          {data.checks.map((c) => (
            <li key={c.kind} className="rounded-md border border-border p-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-text">{t(`delivery.kind.${c.kind}`)}</span>
                <Badge tone={c.status === 'checked' ? 'good' : 'warning'}>{t(`delivery.status.${c.status}`)}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted">{c.detail}</p>
            </li>
          ))}
        </ul>
      </CardBody>
      {data.findings.length > 0 && (
        <Table>
          <thead>
            <tr>
              <Th>{t('delivery.severityLabel')}</Th>
              <Th>{t('delivery.rule')}</Th>
              <Th>{t('delivery.where')}</Th>
              <Th>{t('delivery.what')}</Th>
            </tr>
          </thead>
          <tbody>
            {data.findings.map((f, i) => (
              <tr key={`${f.rule}-${f.file}-${f.line ?? 0}-${i}`}>
                <Td>
                  <Badge tone={SEVERITY_TONE[f.severity]}>{t(`delivery.severity.${f.severity}`)}</Badge>
                </Td>
                <Td className="font-mono text-xs">{f.rule}</Td>
                <Td className="font-mono text-xs">{f.line ? `${f.file}:${f.line}` : f.file}</Td>
                <Td className="text-sm">{f.message}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

/** The releases of the project (spec 6.1 phase 13): pushed to a branch, failed with the reason, or left as a ZIP. */
export function ReleasesCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const releases = useReleases(projectId)
  const rows = releases.data ?? []
  return (
    <Card>
      <CardHeader title={t('delivery.releases')} subtitle={t('delivery.releasesHint')} />
      {rows.length === 0 ? (
        <CardBody>
          <EmptyState title={t('delivery.noReleases')} description={t('delivery.noReleasesHint')} />
        </CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('delivery.when')}</Th>
              <Th>{t('delivery.how')}</Th>
              <Th>{t('delivery.branch')}</Th>
              <Th>{t('delivery.files')}</Th>
              <Th>{t('delivery.findings')}</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <ReleaseRow key={r.id} release={r} />
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function ReleaseRow({ release: r }: { release: Release }) {
  const { t } = useTranslation()
  const findings = severityCounts({ counts: r.findings })
  return (
    <tr>
      <Td className="whitespace-nowrap text-xs">{formatDateTime(r.createdAt)}</Td>
      <Td>
        <Badge tone={RELEASE_TONE[r.status]}>{t(`delivery.release.${r.status}`)}</Badge>
        {r.error && <div className="mt-1 max-w-xs text-xs text-critical-ink">{r.error}</div>}
      </Td>
      <Td className="font-mono text-xs">
        {r.branch ? (
          <span className="inline-flex items-center gap-1">
            <GitBranch size={12} aria-hidden /> {r.branch}
            {r.commitSha && <span className="text-muted">@{r.commitSha.slice(0, 10)}</span>}
          </span>
        ) : (
          '—'
        )}
      </Td>
      <Td>{r.files}</Td>
      <Td>
        {findings.length === 0 ? (
          <span className="text-xs text-muted">—</span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs">
            <ShieldAlert size={12} aria-hidden />
            {findings.map((f) => `${t(`delivery.severity.${f.severity}`)} ${f.count}`).join(' · ')}
          </span>
        )}
      </Td>
    </tr>
  )
}
