import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import type { Contracts } from '@/api/architecture'
import { Card, CardHeader, EmptyState, Table, Td, Th } from '@/components/ui/primitives'

// The contracts of the specification (spec 18.3): each HTTP operation of the target with the rules it serves, from
// the OpenAPI document the frontend pack derived from the design or, without a frontend, from the design's use cases.
// Same look as the prototype's ContractsView.
export function ContractsView({ projectId, contracts }: { projectId: string; contracts: Contracts | null }) {
  const { t } = useTranslation()
  if (!contracts) {
    return <EmptyState title={t('spec.noContracts')} description={t('spec.noContractsHint')} />
  }
  return (
    <Card>
      <CardHeader
        title={t('spec.contractsTitle')}
        subtitle={contracts.source === 'openapi' ? t('spec.contractsFromOpenapi') : t('spec.contractsFromDesign')}
      />
      <Table>
        <thead>
          <tr>
            <Th>{t('spec.operation')}</Th>
            <Th>{t('spec.operationName')}</Th>
            <Th>{t('architecture.rules')}</Th>
          </tr>
        </thead>
        <tbody>
          {contracts.operations.map((o) => (
            <tr key={`${o.method} ${o.path}`}>
              <Td>
                <span className="mr-2 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text">{o.method}</span>
                <span className="font-mono text-xs text-text">{o.path}</span>
                {o.summary && o.summary !== o.name && <div className="mt-1 text-xs text-muted">{o.summary}</div>}
              </Td>
              <Td className="font-mono text-xs">{o.name}</Td>
              <Td>
                <span className="flex flex-wrap gap-x-2 gap-y-1">
                  {o.rules.map((rule) => (
                    <Link
                      key={rule}
                      to="/projects/$projectId"
                      params={{ projectId }}
                      search={{ tab: 'traceability', rule }}
                      className="font-mono text-xs text-brand underline-offset-2 hover:underline"
                    >
                      {rule}
                    </Link>
                  ))}
                </span>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}
