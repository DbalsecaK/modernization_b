import { useTranslation } from 'react-i18next'
import { Loader2, RefreshCw } from 'lucide-react'
import { formatDateTime, formatNumber } from '@/lib/format'
import { ApiError } from '@/api/client'
import { usePlatformStatus } from '@/api/operations'
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
// queues, the runs in progress across tenants and the jobs that failed in the last day. Versions per deployed instance
// come with the deployment profiles (M9). Same look as the prototype.
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
        <CardHeader title={t('platform.deployments')} subtitle={t('platform.deploymentsHint')} />
        <CardBody className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-text-2">{t('platform.apiVersion')}</span>
          <Badge tone="brand">{status.apiVersion}</Badge>
          <span className="text-xs text-muted">{t('platform.instancesLater')}</span>
        </CardBody>
      </Card>
    </div>
  )
}
