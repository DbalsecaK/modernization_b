import { useTranslation } from 'react-i18next'
import { deployments, workers } from '@/mocks/data'
import { Badge, Card, CardHeader, PageHeader, Progress, StatTile, Table, Td, Th } from '@/components/ui/primitives'

export function PlatformPage() {
  const { t } = useTranslation()
  return (
    <>
      <PageHeader title={t('platform.title')} description={t('platform.description')} />
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile label={t('platform.queue')} value="37" hint={t('platform.queueHint')} />
          <StatTile
            label={t('platform.workers')}
            value={`${workers.filter((w) => w.status !== 'offline').length} / ${workers.length}`}
          />
          <StatTile label={t('platform.errors')} value="2" hint={t('platform.errorsHint')} />
          <StatTile label={t('platform.sandboxes')} value="3" hint={t('platform.sandboxesHint')} />
        </div>
        <Card>
          <CardHeader title={t('platform.workersTitle')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('platform.worker')}</Th>
                <Th>{t('platform.pool')}</Th>
                <Th>{t('platform.jobs')}</Th>
                <Th>{t('platform.cpu')}</Th>
                <Th>{t('admin.status')}</Th>
              </tr>
            </thead>
            <tbody>
              {workers.map((w) => (
                <tr key={w.id}>
                  <Td className="font-mono text-xs text-text">{w.id}</Td>
                  <Td>{w.pool}</Td>
                  <Td className="tabular">{w.jobs}</Td>
                  <Td className="w-40">
                    <Progress value={w.cpu} tone={w.cpu > 85 ? 'warning' : 'brand'} />
                  </Td>
                  <Td>
                    <Badge tone={w.status === 'busy' ? 'info' : w.status === 'idle' ? 'good' : 'critical'}>
                      {t(`platform.status.${w.status}`)}
                    </Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card>
          <CardHeader title={t('platform.deployments')} subtitle={t('platform.deploymentsHint')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('platform.instance')}</Th>
                <Th>{t('admin.deployment')}</Th>
                <Th>{t('platform.version')}</Th>
                <Th>{t('admin.projects')}</Th>
                <Th>{t('admin.status')}</Th>
              </tr>
            </thead>
            <tbody>
              {deployments.map((d) => (
                <tr key={d.id}>
                  <Td className="text-text">{d.name}</Td>
                  <Td>
                    <Badge tone="brand">{t(`deployment.${d.model}`)}</Badge>
                  </Td>
                  <Td className="font-mono text-xs">{d.version}</Td>
                  <Td className="tabular">{d.tenants}</Td>
                  <Td>
                    <Badge tone={d.status === 'healthy' ? 'good' : 'info'}>{t(`platform.status.${d.status}`)}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      </div>
    </>
  )
}
