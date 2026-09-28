import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Table2 } from 'lucide-react'
import { formatCompact, formatMonth, formatUsd } from '@/lib/format'
import { costByProvider, monthlyCost, projects, tenants } from '@/mocks/data'
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  PageHeader,
  Progress,
  Select,
  StatTile,
  Table,
  Td,
  Th,
} from '@/components/ui/primitives'
import { BarList, LineChart } from '@/components/charts/charts'
import { Notice } from '@/features/projects/NewProjectWizard'

export function UsagePage() {
  const { t } = useTranslation()
  const [showTable, setShowTable] = useState(false)
  const total = monthlyCost[monthlyCost.length - 1].usd
  const tokens = projects.reduce((s, p) => s + p.tokens, 0)
  const rulesExtracted = projects.reduce((s, p) => s + p.rules.total, 0)

  return (
    <>
      <PageHeader
        title={t('usage.title')}
        description={t('usage.description')}
        actions={
          <>
            <Select className="w-44" defaultValue="30" aria-label={t('usage.range')}>
              <option value="30">{t('usage.last30')}</option>
              <option value="90">{t('usage.last90')}</option>
              <option value="mtd">{t('usage.monthToDate')}</option>
            </Select>
            <Button>
              <Download size={16} /> {t('usage.export')}
            </Button>
          </>
        }
      />
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile label={t('usage.thisMonth')} value={formatUsd(total)} hint={t('usage.vsLastMonth', { pct: 45 })} />
          <StatTile label={t('usage.tokens')} value={formatCompact(tokens)} />
          <StatTile label={t('usage.costPerKloc')} value={formatUsd(4.8, 2)} hint={t('usage.unitHint')} />
          <StatTile
            label={t('usage.costPerRule')}
            value={formatUsd(total / rulesExtracted, 2)}
            hint={t('usage.rulesExtracted', { count: rulesExtracted })}
          />
        </div>
        <Card>
          <CardHeader
            title={t('usage.trend')}
            action={
              <Button size="sm" variant="ghost" onClick={() => setShowTable((v) => !v)} aria-pressed={showTable}>
                <Table2 size={14} /> {showTable ? t('usage.showChart') : t('usage.showTable')}
              </Button>
            }
          />
          <CardBody>
            {showTable ? (
              <Table>
                <thead>
                  <tr>
                    <Th>{t('usage.month')}</Th>
                    <Th className="text-right">{t('usage.cost')}</Th>
                  </tr>
                </thead>
                <tbody>
                  {monthlyCost.map((m) => (
                    <tr key={m.month}>
                      <Td>{formatMonth(m.month)}</Td>
                      <Td className="text-right tabular">{formatUsd(m.usd)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <LineChart
                data={monthlyCost.map((m) => ({ x: formatMonth(m.month), y: m.usd }))}
                format={(v) => formatUsd(v)}
                label={t('usage.trend')}
              />
            )}
          </CardBody>
        </Card>
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title={t('usage.byTenant')} />
            <CardBody>
              <BarList
                data={tenants.map((x) => ({ label: x.name, value: x.monthCostUsd }))}
                format={(v) => formatUsd(v)}
              />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t('usage.byProvider')} />
            <CardBody>
              <BarList
                data={costByProvider.map((c) => ({ label: t(`providers.${c.key}`), value: c.usd }))}
                format={(v) => formatUsd(v)}
              />
            </CardBody>
          </Card>
        </div>
        <Card>
          <CardHeader title={t('usage.budgets')} subtitle={t('usage.budgetsHint')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('projects.name')}</Th>
                <Th>{t('usage.consumed')}</Th>
                <Th className="text-right">{t('usage.spent')}</Th>
                <Th className="text-right">{t('usage.forecast')}</Th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => {
                const pct = Math.round((p.costUsd / p.budgetUsd) * 100)
                const forecast = (p.costUsd / Math.max(p.progress, 1)) * 100
                return (
                  <tr key={p.id}>
                    <Td className="text-text">{p.name}</Td>
                    <Td className="w-56">
                      <Progress value={pct} tone={pct >= 100 ? 'critical' : pct >= 80 ? 'warning' : 'brand'} />
                      <div className="mt-1 text-xs text-muted tabular">{pct}%</div>
                    </Td>
                    <Td className="text-right tabular">
                      {formatUsd(p.costUsd)} / {formatUsd(p.budgetUsd)}
                    </Td>
                    <Td className="text-right tabular">{formatUsd(forecast)}</Td>
                  </tr>
                )
              })}
            </tbody>
          </Table>
        </Card>
        <Notice tone="info">{t('usage.ledgerNote')}</Notice>
      </div>
    </>
  )
}
