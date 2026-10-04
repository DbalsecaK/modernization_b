import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { type Classification, type ClassLabel, useClassification } from '@/api/graph'
import { Badge, Button, Card, CardBody, CardHeader, StatTile, Table, Td, Th } from '@/components/ui/primitives'
import { cn } from '@/lib/cn'

// The classification of the legacy's statements (spec 6.1 phase 4): which are business logic (what the rule extractors
// read), control flow and infrastructure (error handling, logging, work tables), with the reason for each.
const LABELS: ClassLabel[] = ['business', 'control_flow', 'infrastructure']
const TONE: Record<ClassLabel, 'good' | 'info' | 'neutral'> = {
  business: 'good',
  control_flow: 'info',
  infrastructure: 'neutral',
}
const PAGE = 200

export function shareOf(data: Classification, label: ClassLabel): number {
  const total = Object.values(data.counts).reduce((a, b) => a + b, 0)
  return total ? Math.round(((data.counts[label] ?? 0) / total) * 100) : 0
}

export function ClassificationPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation()
  const query = useClassification(projectId)
  const [label, setLabel] = useState<ClassLabel | 'all'>('all')
  const [shown, setShown] = useState(PAGE)
  const data = query.data
  if (!data) return null
  const rows = data.statements.filter((s) => label === 'all' || s.label === label)
  return (
    <Card>
      <CardHeader title={t('inventory.classification.title')} subtitle={t('inventory.classification.hint')} />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          {LABELS.map((l) => (
            <button key={l} className="text-left" onClick={() => (setLabel(label === l ? 'all' : l), setShown(PAGE))}>
              <StatTile
                label={t(`inventory.classification.labels.${l}`)}
                value={data.counts[l] ?? 0}
                hint={t('inventory.classification.share', { pct: shareOf(data, l) })}
              />
            </button>
          ))}
        </div>
        {data.statements.length === 0 ? (
          <p className="text-sm text-muted">{t('inventory.classification.noDetail')}</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('inventory.classification.filter')}>
              {(['all', ...LABELS] as const).map((l) => (
                <button
                  key={l}
                  onClick={() => (setLabel(l), setShown(PAGE))}
                  aria-pressed={label === l}
                  className={cn(
                    'rounded-full border px-2.5 py-0.5 text-xs',
                    label === l ? 'border-series-1 bg-series-1/10 text-text' : 'border-border text-muted',
                  )}
                >
                  {l === 'all' ? t('inventory.classification.all') : t(`inventory.classification.labels.${l}`)}
                </button>
              ))}
            </div>
            <Table>
              <thead>
                <tr>
                  <Th>{t('inventory.classification.unit')}</Th>
                  <Th>{t('inventory.classification.lines')}</Th>
                  <Th>{t('inventory.classification.statement')}</Th>
                  <Th>{t('inventory.classification.class')}</Th>
                  <Th>{t('inventory.classification.reason')}</Th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((s) => (
                  <tr key={`${s.file}:${s.lineStart}:${s.statement}`}>
                    <Td className="font-mono text-xs">{s.unit}</Td>
                    <Td className="font-mono text-xs whitespace-nowrap">
                      {s.lineStart === s.lineEnd ? s.lineStart : `${s.lineStart}–${s.lineEnd}`}
                    </Td>
                    <Td className="font-mono text-xs">{s.statement}</Td>
                    <Td>
                      <Badge tone={TONE[s.label]}>{t(`inventory.classification.labels.${s.label}`)}</Badge>
                    </Td>
                    <Td className="text-xs text-muted">{s.reason}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {rows.length > shown && (
              <Button size="sm" variant="ghost" onClick={() => setShown(shown + PAGE)}>
                {t('inventory.classification.more', { count: rows.length - shown })}
              </Button>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}
