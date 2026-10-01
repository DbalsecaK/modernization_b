import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import { useContracts, useDesign } from '@/api/architecture'
import type { ProjectDetail } from '@/api/projects'
import { useVerdicts } from '@/api/validation'
import { Badge, Button, Card, CardBody, CardHeader, Code, EmptyState, Table, Td, Th } from '@/components/ui/primitives'
import { contextSummary, contractText, serviceOf } from './architecture/model'
import { allChecks, byModule, checkStatusKey, checkTitleKey, checkTone } from './validation/model'

// Architecture tab (spec 18.3), connected to the API: the bounded context of the design approved at C3 with its use
// cases, entities and ports, the design decisions (ADR), the OpenAPI contract and, as fitness functions, the checks
// of the newest verdict of each module. Same look as the prototype's ArchitectureTab.
export function ProjectArchitecture({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const design = useDesign(project.id)
  const contracts = useContracts(project.id)
  const verdicts = useVerdicts(project.id)

  if (design.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('architecture.loading')}
      </p>
    )
  }
  if (design.isError) {
    return (
      <EmptyState
        title={t('architecture.loadError')}
        description={design.error instanceof ApiError ? design.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void design.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  if (!design.data) {
    return (
      <EmptyState
        title={t('project.later.architecture')}
        description={t('architecture.emptyHint')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }
  const d = design.data
  const summary = contextSummary(d)
  const target = project.config?.target
  const contract = contracts.data?.openapi ? contractText(contracts.data.openapi) : null
  const modules = byModule(verdicts.data ?? [])

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={t('architecture.contexts')}
          subtitle={
            target
              ? `${target.architecture} · ${target.backend} · ${target.database} · ${d.basePackage}`
              : d.basePackage
          }
        />
        <Table>
          <thead>
            <tr>
              <Th>{t('architecture.context')}</Th>
              <Th>{t('architecture.rules')}</Th>
              <Th>{t('architecture.services')}</Th>
              <Th>{t('architecture.endpoints')}</Th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <Td className="font-medium text-text">{summary.name}</Td>
              <Td className="tabular">{summary.rules}</Td>
              <Td className="font-mono text-xs">{summary.services.join(', ')}</Td>
              <Td className="tabular">{summary.endpoints}</Td>
            </tr>
          </tbody>
        </Table>
      </Card>

      <Card>
        <CardHeader title={t('architecture.useCases')} subtitle={t('architecture.useCasesHint')} />
        <Table>
          <thead>
            <tr>
              <Th>{t('architecture.useCase')}</Th>
              <Th>{t('architecture.rules')}</Th>
              <Th>{t('architecture.ports')}</Th>
              <Th>{t('architecture.legacy')}</Th>
            </tr>
          </thead>
          <tbody>
            {(d.useCases ?? []).map((u) => (
              <tr key={u.name}>
                <Td>
                  <div className="font-medium text-text">{serviceOf(u.name)}</div>
                  {u.description && <div className="text-xs text-muted">{u.description}</div>}
                </Td>
                <Td className="font-mono text-xs">{(u.rules ?? []).join(', ')}</Td>
                <Td className="font-mono text-xs">{(u.ports ?? []).join(', ') || '—'}</Td>
                <Td className="font-mono text-xs">{u.legacyProgram ?? '—'}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('architecture.entities')} />
          <Table>
            <thead>
              <tr>
                <Th>{t('architecture.entity')}</Th>
                <Th>{t('architecture.table')}</Th>
                <Th>{t('architecture.legacyTable')}</Th>
              </tr>
            </thead>
            <tbody>
              {(d.entities ?? []).map((e) => (
                <tr key={e.name}>
                  <Td>
                    <div className="font-medium text-text">{e.name}</div>
                    <div className="text-xs text-muted">
                      {t('architecture.fieldCount', { count: (e.fields ?? []).length })}
                    </div>
                  </Td>
                  <Td className="font-mono text-xs">{e.table ?? '—'}</Td>
                  <Td className="font-mono text-xs">{e.legacyTable ?? '—'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
        <Card>
          <CardHeader title={t('architecture.portsTitle')} subtitle={t('architecture.portsHint')} />
          <CardBody className="space-y-3">
            {(d.ports ?? []).map((p) => (
              <div key={p.name} className="text-sm">
                <div className="font-medium text-text">{p.name}</div>
                <div className="font-mono text-xs text-muted">
                  {(p.methods ?? []).map((m) => m.name).join(', ')}
                  {p.legacyProgram && ` · ${t('architecture.replaces', { program: p.legacyProgram })}`}
                </div>
              </div>
            ))}
            {(d.ports ?? []).length === 0 && <p className="text-sm text-muted">{t('architecture.noPorts')}</p>}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('architecture.adrs')} subtitle={t('architecture.adrsHint')} />
          <CardBody className="space-y-3">
            {(d.decisions ?? []).map((adr, i) => (
              <details key={adr.title} className="rounded-md border border-border p-3 text-sm">
                <summary className="cursor-pointer">
                  <span className="mr-2 font-mono text-xs text-muted">ADR-{String(i + 1).padStart(3, '0')}</span>
                  <span className="text-text">{adr.title}</span>
                </summary>
                <dl className="mt-2 space-y-2 text-text-2">
                  {adr.context && (
                    <div>
                      <dt className="text-xs font-medium text-muted uppercase">{t('architecture.adrContext')}</dt>
                      <dd>{adr.context}</dd>
                    </div>
                  )}
                  <div>
                    <dt className="text-xs font-medium text-muted uppercase">{t('architecture.adrDecision')}</dt>
                    <dd>{adr.decision}</dd>
                  </div>
                  {adr.consequences && (
                    <div>
                      <dt className="text-xs font-medium text-muted uppercase">{t('architecture.adrConsequences')}</dt>
                      <dd>{adr.consequences}</dd>
                    </div>
                  )}
                </dl>
              </details>
            ))}
            {(d.decisions ?? []).length === 0 && <p className="text-sm text-muted">{t('architecture.noAdrs')}</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader
            title={t('architecture.contract')}
            subtitle={contract ? 'openapi.json · OpenAPI 3.1' : t('architecture.contractFromDesign')}
            action={
              <Link
                to="/projects/$projectId"
                params={{ projectId: project.id }}
                search={{ tab: 'specification', view: 'contracts' }}
                className="text-sm text-brand underline-offset-2 hover:underline"
              >
                {t('architecture.seeOperations')}
              </Link>
            }
          />
          <CardBody>
            {contract ? (
              <>
                <Code label={t('architecture.contract')} className="max-h-96">
                  {contract.text}
                </Code>
                {contract.truncated && <p className="mt-2 text-xs text-muted">{t('architecture.contractTruncated')}</p>}
              </>
            ) : (
              <p className="text-sm text-muted">{t('architecture.noOpenapi')}</p>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={t('architecture.fitness')} subtitle={t('architecture.fitnessHint')} />
        <CardBody className="space-y-4">
          {modules.length === 0 && <p className="text-sm text-muted">{t('architecture.noFitness')}</p>}
          {modules.map(({ module, latest }) => (
            <div key={module}>
              <div className="mb-2 font-mono text-xs text-muted">{module}</div>
              <ul className="grid gap-2 text-sm sm:grid-cols-2" aria-label={t('architecture.fitnessOf', { module })}>
                {allChecks(latest.checks, module).map((c) => (
                  <li key={c.key} className="flex items-center gap-2 text-text-2">
                    <Badge tone={checkTone(c.status)}>{t(checkStatusKey(c.status))}</Badge>
                    {t(checkTitleKey(c.key), { defaultValue: c.title })}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}
