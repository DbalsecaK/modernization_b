import { useTranslation } from 'react-i18next'
import { Loader2, RefreshCw } from 'lucide-react'
import { formatDateTime, formatNumber } from '@/lib/format'
import { ApiError } from '@/api/client'
import { usePlatformStatus, type LicenseStatus } from '@/api/operations'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  PageHeader,
  StatTile,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'

// Platform operations (spec 18.4, NexTI only), connected to the API: the workers with their heartbeat and jobs, the
// queues, the runs in progress across tenants, the jobs that failed in the last day and every API and worker instance
// with its version and deployment profile (ADR-0024), and the offline license with its read-only mode (ADR-0030).
// Same look as the prototype.
export function PlatformPage() {
  const { t } = useTranslation()
  const status = usePlatformStatus()

  return (
    <>
      <PageHeader
        title={t('platform.title')}
        description={t('platform.description')}
        actions={
          <Button size="sm" onClick={() => void status.refetch()} disabled={status.isFetching}>
            <RefreshCw size={14} aria-hidden className={status.isFetching ? 'animate-spin' : undefined} />
            {t('platform.refresh')}
          </Button>
        }
      />
      {status.isLoading ? (
        <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
          <Loader2 size={16} className="animate-spin" /> {t('platform.loading')}
        </p>
      ) : status.isError || !status.data ? (
        <EmptyState
          title={t('platform.loadError')}
          description={status.error instanceof ApiError ? status.error.message : undefined}
          action={
            <Button size="sm" onClick={() => void status.refetch()}>
              {t('spec.retry')}
            </Button>
          }
        />
      ) : (
        <PlatformView status={status.data} />
      )}
    </>
  )
}

function PlatformView({ status }: { status: NonNullable<ReturnType<typeof usePlatformStatus>['data']> }) {
  const { t } = useTranslation()
  const waiting = status.queues.reduce((s, q) => s + q.waiting, 0)
  const alive = status.workers.filter((w) => w.alive).length
  return (
    <div className="space-y-6">
      <LicenseCard license={status.license} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label={t('platform.queue')} value={formatNumber(waiting)} hint={t('platform.queueHint')} />
        <StatTile label={t('platform.workers')} value={`${alive} / ${status.workers.length}`} />
        <StatTile
          label={t('platform.errors')}
          value={formatNumber(status.failedLastDay)}
          hint={t('platform.errorsHint')}
        />
        <StatTile
          label={t('platform.runs')}
          value={formatNumber(status.activeRuns)}
          hint={t('platform.runsHint', { count: status.waitingRuns })}
        />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('platform.workersTitle')} subtitle={t('platform.workersHint')} />
          {status.workers.length === 0 ? (
            <CardBody>
              <p className="text-sm text-muted">{t('platform.noWorkers')}</p>
            </CardBody>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t('platform.worker')}</Th>
                  <Th>{t('platform.heartbeat')}</Th>
                  <Th>{t('platform.jobs')}</Th>
                  <Th>{t('admin.status')}</Th>
                </tr>
              </thead>
              <tbody>
                {status.workers.map((w) => (
                  <tr key={w.id}>
                    <Td className="font-mono text-xs text-text">#{w.id}</Td>
                    <Td className="text-xs">{formatDateTime(w.lastHeartbeat)}</Td>
                    <Td className="tabular">{w.runningJobs}</Td>
                    <Td>
                      <Badge tone={!w.alive ? 'critical' : w.runningJobs > 0 ? 'info' : 'good'}>
                        {t(`platform.status.${!w.alive ? 'offline' : w.runningJobs > 0 ? 'busy' : 'idle'}`)}
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title={t('platform.queuesTitle')} />
          {status.queues.length === 0 ? (
            <CardBody>
              <p className="text-sm text-muted">{t('platform.queuesEmpty')}</p>
            </CardBody>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>{t('platform.queueName')}</Th>
                  <Th>{t('platform.waiting')}</Th>
                  <Th>{t('platform.running')}</Th>
                </tr>
              </thead>
              <tbody>
                {status.queues.map((q) => (
                  <tr key={q.queue}>
                    <Td className="font-mono text-xs text-text">{q.queue}</Td>
                    <Td className="tabular">{q.waiting}</Td>
                    <Td className="tabular">{q.running}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
      <Card>
        <CardHeader title={t('platform.failuresTitle')} subtitle={t('platform.failuresHint')} />
        {status.recentFailures.length === 0 ? (
          <CardBody>
            <p className="text-sm text-muted">{t('platform.noFailures')}</p>
          </CardBody>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('platform.job')}</Th>
                <Th>{t('platform.queueName')}</Th>
                <Th>{t('platform.attempts')}</Th>
                <Th>{t('platform.failedAt')}</Th>
              </tr>
            </thead>
            <tbody>
              {status.recentFailures.map((f) => (
                <tr key={f.id}>
                  <Td className="font-mono text-xs text-text">
                    {f.task} #{f.id}
                  </Td>
                  <Td className="font-mono text-xs">{f.queue}</Td>
                  <Td className="tabular">{f.attempts}</Td>
                  <Td className="text-xs">{formatDateTime(f.failedAt)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Card>
        <CardHeader
          title={t('platform.deployments')}
          subtitle={t('platform.deploymentsHint')}
          action={<Badge tone="brand">{t('platform.apiVersionIs', { version: status.apiVersion })}</Badge>}
        />
        {status.instances.length === 0 ? (
          <CardBody>
            <p className="text-sm text-muted">{t('platform.noInstances')}</p>
          </CardBody>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>{t('platform.instance')}</Th>
                <Th>{t('platform.component')}</Th>
                <Th>{t('platform.version')}</Th>
                <Th>{t('platform.profile')}</Th>
                <Th>{t('platform.lastSeen')}</Th>
              </tr>
            </thead>
            <tbody>
              {status.instances.map((i) => (
                <tr key={i.name}>
                  <Td className="font-mono text-xs">{i.name}</Td>
                  <Td>{t(`platform.components.${i.component}`)}</Td>
                  <Td className="font-mono text-xs">{i.version}</Td>
                  <Td>{i.profile}</Td>
                  <Td className="text-xs">
                    <Badge tone={i.alive ? 'good' : 'warning'}>
                      {i.alive ? t('platform.instanceAlive') : t('platform.instanceSilent')}
                    </Badge>{' '}
                    {formatDateTime(i.lastSeenAt)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  )
}

function LicenseCard({ license }: { license: LicenseStatus }) {
  const { t } = useTranslation()
  const tone = license.state === 'valid' ? 'good' : license.state === 'not_required' ? 'neutral' : 'critical'
  const usage = (used: number | null | undefined, max: number | null | undefined) =>
    max == null ? '—' : t('platform.license.usage', { used: used ?? '—', max })
  return (
    <Card>
      <CardHeader
        title={t('platform.license.title')}
        subtitle={t('platform.license.hint')}
        action={<Badge tone={tone}>{t(`platform.license.states.${license.state}`)}</Badge>}
      />
      <CardBody>
        {license.state === 'not_required' ? (
          <p className="text-sm text-muted">{t('platform.license.notRequired')}</p>
        ) : (
          <div className="space-y-4">
            {license.readOnly && (
              <div className="space-y-1 rounded-md bg-critical/10 p-3 text-sm" role="alert">
                <p className="font-medium text-text">{t('platform.license.readOnly')}</p>
                {license.reason && <p>{t(`platform.license.reasons.${license.reason}`)}</p>}
              </div>
            )}
            {license.customer && (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm lg:grid-cols-4">
                <dt className="text-muted">{t('platform.license.customer')}</dt>
                <dd>{license.customer}</dd>
                <dt className="text-muted">{t('platform.license.profile')}</dt>
                <dd>{license.deploymentProfile}</dd>
                <dt className="text-muted">{t('platform.license.issued')}</dt>
                <dd className="text-xs">{license.issuedAt ? formatDateTime(license.issuedAt) : '—'}</dd>
                <dt className="text-muted">{t('platform.license.expires')}</dt>
                <dd className="text-xs">{license.expiresAt ? formatDateTime(license.expiresAt) : '—'}</dd>
                <dt className="text-muted">{t('platform.license.tenants')}</dt>
                <dd className="tabular">{usage(license.tenants, license.maxTenants)}</dd>
                <dt className="text-muted">{t('platform.license.projects')}</dt>
                <dd className="tabular">{usage(license.projects, license.maxProjects)}</dd>
                <dt className="text-muted">{t('platform.license.features')}</dt>
                <dd>{license.features?.length ? license.features.join(', ') : t('platform.license.noFeatures')}</dd>
                <dt className="text-muted">{t('platform.license.licenseId')}</dt>
                <dd className="font-mono text-xs break-all">{license.licenseId}</dd>
              </dl>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  )
}
