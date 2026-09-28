import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, Download, FileCode2, Folder, GitPullRequest, MessageSquare, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { rules } from '@/mocks/data'
import type { Project, Rule } from '@/mocks/types'
import { Badge, Button, Card, CardBody, CardHeader, Code, Select, Table, Td, Th } from '@/components/ui/primitives'
import { Notice } from '../NewProjectWizard'

const ruleStatusTone = { approved: 'good', inReview: 'info', question: 'warning', draft: 'neutral' } as const

export function SpecificationTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<Rule>(rules[0])
  const [status, setStatus] = useState<'all' | Rule['status']>('all')
  const list = rules.filter((r) => status === 'all' || r.status === status)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Select className="max-w-xs" value={status} onChange={(e) => setStatus(e.target.value as typeof status)} aria-label={t('spec.filterStatus')}>
          <option value="all">{t('spec.allStatuses')}</option>
          {(['approved', 'inReview', 'question', 'draft'] as const).map((s) => (
            <option key={s} value={s}>
              {t(`ruleStatus.${s}`)}
            </option>
          ))}
        </Select>
        <span className="text-sm text-muted">{t('spec.rulesCount', { count: project.rules.total, approved: project.rules.approved })}</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm">
            <Download size={14} /> {t('spec.export')}
          </Button>
          <Button size="sm" variant="primary">
            {t('spec.approveGate')}
          </Button>
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Card>
          <ul className="divide-y divide-border">
            {list.map((r) => (
              <li key={r.id}>
                <button onClick={() => setSelected(r)} className={cn('w-full px-4 py-3 text-left hover:bg-surface-2', selected.id === r.id && 'bg-surface-2')}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted">{r.id}</span>
                    <Badge tone={r.priority === 'P0' ? 'critical' : r.priority === 'P1' ? 'warning' : 'neutral'}>{r.priority}</Badge>
                    <Badge tone={ruleStatusTone[r.status]} className="ml-auto">
                      {t(`ruleStatus.${r.status}`)}
                    </Badge>
                  </div>
                  <div className="mt-1 text-sm font-medium text-text">{r.name}</div>
                  <div className="text-xs text-muted">
                    {r.domain} · {t(`ruleCategory.${r.category}`)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader
            title={
              <span>
                <span className="font-mono text-muted">{selected.id}</span> · {selected.name}
              </span>
            }
            subtitle={t('spec.confidence', { level: t(`confidence.${selected.confidence}`) })}
          />
          <CardBody className="space-y-4">
            <p className="text-sm text-text">{selected.statement}</p>
            <Code className="whitespace-pre-wrap">
              <span className="text-info">Given</span> {selected.given}
              {'\n'}
              <span className="text-info">When</span> {selected.when}
              {'\n'}
              <span className="text-info">Then</span> {selected.then}
            </Code>
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted">{t('spec.source')}</dt>
                <dd className="font-mono text-xs text-text">{selected.source}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted">{t('spec.test')}</dt>
                <dd className="text-text">{t(`testStatus.${selected.testStatus}`)}</dd>
              </div>
            </dl>
            {selected.smeQuestion && (
              <Notice tone="warning">
                <strong>{t('spec.smeQuestion')}:</strong> {selected.smeQuestion}
              </Notice>
            )}
            <div className="flex flex-wrap gap-2 border-t border-border pt-4">
              <Button size="sm" variant="primary">
                <Check size={14} /> {t('spec.approve')}
              </Button>
              <Button size="sm">
                <MessageSquare size={14} /> {t('spec.comment')}
              </Button>
              <Button size="sm" variant="ghost">
                <X size={14} /> {t('spec.reject')}
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

const bmsScreen = `  COACTUP                 Update Account                  09/28/26
                                                               10:42:13
      Account Number : 00000001234        Active Y/N: Y
      Opened         : 2019-03-14         Expiry    : 2029-03-31
      Credit Limit   :      5,000.00      Cash Limit:   1,000.00
      Current Bal    :      4,900.00      Cycle Cr  :     120.00

      Customer
      First Name     : MARIA              Last Name : TORRES
      SSN            : ***-**-6789        FICO      : 742

  ENTER=Save  F3=Exit  F5=Refresh  F12=Cancel`

export function UiDesignTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const isModernization = project.flow === 'modernization'
  return (
    <div className="space-y-6">
      <Notice tone="info">{t(isModernization ? 'uiDesign.fromBms' : 'uiDesign.fromFigma')}</Notice>
      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title={t(isModernization ? 'uiDesign.legacyScreen' : 'uiDesign.inputScreen')} subtitle="COACTUP · COACTUPC" />
          <CardBody>
            <pre className="overflow-x-auto rounded-md bg-black p-4 font-mono text-[11px] leading-5 text-[#33ff66]">{bmsScreen}</pre>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('uiDesign.prototype')} subtitle={t('uiDesign.prototypeHint')} action={<Badge tone="warning">{t('uiDesign.awaitingC2')}</Badge>} />
          <CardBody>
            <PrototypeForm />
          </CardBody>
        </Card>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title={t('uiDesign.designSystem')} subtitle={t('uiDesign.designSystemHint')} />
          <CardBody className="space-y-4">
            <div className="flex flex-wrap gap-3">
              {[
                ['Primary', '#052158'],
                ['Accent', '#05E194'],
                ['Surface', '#FFFFFF'],
                ['Text', '#0B1220'],
                ['Critical', '#D03B3B'],
              ].map(([name, hex]) => (
                <div key={name} className="text-xs">
                  <div className="h-12 w-20 rounded-md border border-border" style={{ background: hex }} />
                  <div className="mt-1 font-medium text-text">{name}</div>
                  <div className="font-mono text-muted">{hex}</div>
                </div>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" size="sm">
                Primary
              </Button>
              <Button size="sm">Secondary</Button>
              <Button size="sm" variant="ghost">
                Ghost
              </Button>
              <Badge tone="good">Success</Badge>
              <Badge tone="warning">Warning</Badge>
              <Badge tone="critical">Error</Badge>
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('uiDesign.comments')} />
          <CardBody className="space-y-3 text-sm">
            <Comment who="María Torres" text="Move the credit limit next to the current balance." />
            <Comment who="UX/UI designer (agent)" text="Regenerated: limits grouped in one section. Iteration 2." />
            <div className="flex gap-2 pt-2">
              <Button size="sm" variant="primary">
                {t('uiDesign.approve')}
              </Button>
              <Button size="sm">{t('uiDesign.requestChanges')}</Button>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function Comment({ who, text }: { who: string; text: string }) {
  return (
    <div className="rounded-md bg-surface-2 p-3">
      <div className="text-xs font-medium text-text">{who}</div>
      <div className="mt-0.5 text-text-2">{text}</div>
    </div>
  )
}

// A sample of what a generated prototype looks like: labelled, accessible fields mapped from the BMS map.
function PrototypeForm() {
  const fields = [
    ['Account number', '00000001234', true],
    ['Status', 'Active', false],
    ['Credit limit', '5,000.00', false],
    ['Current balance', '4,900.00', true],
    ['First name', 'María', false],
    ['Last name', 'Torres', false],
  ] as const
  return (
    <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => e.preventDefault()}>
      {fields.map(([label, value, readOnly]) => (
        <label key={label} className="block text-sm">
          <span className="mb-1 block text-xs font-medium text-text-2">{label}</span>
          <input
            defaultValue={value}
            readOnly={readOnly}
            className={cn('h-9 w-full rounded-md border border-border px-3 text-text', readOnly ? 'bg-surface-2' : 'bg-surface')}
          />
        </label>
      ))}
      <div className="flex gap-2 sm:col-span-2">
        <Button size="sm" variant="primary" type="submit">
          Save
        </Button>
        <Button size="sm" type="button">
          Cancel
        </Button>
      </div>
    </form>
  )
}

export function ArchitectureTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const contexts = [
    { name: 'Accounts', rules: 38, services: ['account-service'], endpoints: 9 },
    { name: 'Cards', rules: 27, services: ['card-service'], endpoints: 7 },
    { name: 'Authorizations', rules: 44, services: ['authorization-service'], endpoints: 5 },
    { name: 'Billing', rules: 39, services: ['billing-service', 'statement-batch'], endpoints: 6 },
  ]
  const adrs = [
    ['ADR-001', 'Hexagonal architecture inside every service', 'accepted'],
    ['ADR-002', 'CICS pseudo-conversational state → stateless REST with a session token', 'accepted'],
    ['ADR-003', 'VSAM ACCTDAT/CARDDAT → PostgreSQL with NUMERIC(11,2)', 'proposed'],
    ['ADR-004', 'Strangler fig: route Account view first through the API gateway', 'proposed'],
  ]
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title={t('architecture.contexts')} subtitle={`${project.target.architecture} · ${project.target.backend} · ${project.target.database}`} />
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
            {contexts.map((c) => (
              <tr key={c.name}>
                <Td className="font-medium text-text">{c.name}</Td>
                <Td className="tabular">{c.rules}</Td>
                <Td className="font-mono text-xs">{c.services.join(', ')}</Td>
                <Td className="tabular">{c.endpoints}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('architecture.adrs')} />
          <CardBody className="space-y-2">
            {adrs.map(([id, title, state]) => (
              <div key={id} className="flex items-start gap-3 text-sm">
                <span className="font-mono text-xs text-muted">{id}</span>
                <span className="flex-1 text-text">{title}</span>
                <Badge tone={state === 'accepted' ? 'good' : 'info'}>{t(`architecture.adrState.${state}`)}</Badge>
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('architecture.contract')} subtitle="account-service · openapi.yaml" />
          <CardBody>
            <Code>{`paths:
  /accounts/{accountId}:
    get:
      operationId: getAccount
      x-rules: [RULE-005]
      responses:
        '200': { $ref: '#/components/schemas/Account' }
    patch:
      operationId: updateAccount
      x-rules: [RULE-001, RULE-006]
components:
  schemas:
    Account:
      properties:
        creditLimit: { type: string, format: decimal, x-neutral: 'decimal(11,2,signed)' }`}</Code>
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader title={t('architecture.fitness')} />
        <CardBody className="grid gap-2 text-sm sm:grid-cols-2">
          {['fitnessDomain', 'fitnessAdapters', 'fitnessNaming', 'fitnessRuleIds'].map((f) => (
            <div key={f} className="flex items-center gap-2 text-text-2">
              <Check size={14} className="text-good" /> {t(`architecture.${f}`)}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}

const tree = [
  { path: 'account-service/', dir: true, depth: 0 },
  { path: 'domain/', dir: true, depth: 1 },
  { path: 'Account.java', dir: false, depth: 2 },
  { path: 'CreditLimitPolicy.java', dir: false, depth: 2 },
  { path: 'application/', dir: true, depth: 1 },
  { path: 'UpdateAccountUseCase.java', dir: false, depth: 2 },
  { path: 'adapters/', dir: true, depth: 1 },
  { path: 'AccountController.java', dir: false, depth: 2 },
  { path: 'AccountJpaRepository.java', dir: false, depth: 2 },
  { path: 'test/', dir: true, depth: 1 },
  { path: 'CreditLimitPolicyTest.java', dir: false, depth: 2 },
]

export function CodeTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const [file, setFile] = useState('CreditLimitPolicy.java')
  const generation = project.phases.find((p) => p.key === 'generation')
  return (
    <div className="space-y-4">
    {generation?.status === 'pending' && <Notice tone="info">{t('code.notYet')}</Notice>}
    <Card>
      <CardHeader
        title={t('code.title')}
        subtitle={t('code.subtitle')}
        action={
          <div className="flex gap-2">
            <Button size="sm">
              <Download size={14} /> {t('code.download')}
            </Button>
            <Button size="sm" variant="primary">
              <GitPullRequest size={14} /> {t('code.push')}
            </Button>
          </div>
        }
      />
      <div className="grid md:grid-cols-[240px_1fr]">
        <ul className="border-b border-border p-3 text-sm md:border-r md:border-b-0">
          {tree.map((n) => (
            <li key={n.path}>
              <button
                disabled={n.dir}
                onClick={() => setFile(n.path)}
                className={cn('flex w-full items-center gap-1.5 rounded px-2 py-1 text-left', !n.dir && 'hover:bg-surface-2', file === n.path && 'bg-surface-2 font-medium')}
                style={{ paddingLeft: 8 + n.depth * 14 }}
              >
                {n.dir ? <Folder size={14} className="text-muted" /> : <FileCode2 size={14} className="text-muted" />}
                <span className="truncate text-text">{n.path}</span>
              </button>
            </li>
          ))}
        </ul>
        <div className="min-w-0 p-4">
          <div className="mb-2 font-mono text-xs text-muted">{file}</div>
          <Code>{`package com.andesbank.account.domain;

/**
 * RULE-001 Credit limit check on purchase.
 * Source: COCRDUPC.cbl:412-438
 */
public final class CreditLimitPolicy {

  public Decision evaluate(Money balance, Money limit, Money purchase) {
    if (balance.plus(purchase).isGreaterThan(limit)) {
      return Decision.decline(ReasonCode.OVER_LIMIT); // 51
    }
    return Decision.approve();
  }
}`}</Code>
        </div>
      </div>
    </Card>
    </div>
  )
}

export function TraceabilityTab() {
  const { t } = useTranslation()
  return (
    <div className="space-y-4">
      <Notice tone="info">{t('traceability.hint')}</Notice>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card>
          <CardHeader title={t('traceability.legacy')} subtitle="COCRDUPC.cbl:412-438" />
          <CardBody>
            <Code>
              {`       2100-CHECK-LIMIT.
           COMPUTE WS-NEW-BAL =
               ACCT-CURR-BAL + WS-TRAN-AMT
           `}
              <mark className="rounded bg-warning/30 px-0.5 text-text">{`IF WS-NEW-BAL > ACCT-CREDIT-LIMIT`}</mark>
              {`
               MOVE '51' TO WS-RESP-CODE
               SET TRAN-DECLINED TO TRUE
               GO TO 2100-EXIT
           END-IF.`}
            </Code>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('traceability.rule')} subtitle="RULE-001 · P0" />
          <CardBody className="space-y-3 text-sm">
            <p className="text-text">{rules[0].statement}</p>
            <Code className="whitespace-pre-wrap">{`Given ${rules[0].given}\nWhen ${rules[0].when}\nThen ${rules[0].then}`}</Code>
            <div className="space-y-1 text-xs">
              <TraceLink ok label={t('traceability.citationVerified')} />
              <TraceLink ok label={t('traceability.implementationVerified')} />
              <TraceLink ok={false} label={t('traceability.testNotRun')} />
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('traceability.target')} subtitle="CreditLimitPolicy.java:9-14" />
          <CardBody>
            <Code>
              {`public Decision evaluate(Money balance,
    Money limit, Money purchase) {
  `}
              <mark className="rounded bg-warning/30 px-0.5 text-text">{`if (balance.plus(purchase).isGreaterThan(limit)) {`}</mark>
              {`
    return Decision.decline(ReasonCode.OVER_LIMIT);
  }
  return Decision.approve();
}`}
            </Code>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

function TraceLink({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className={cn('flex items-center gap-1.5', ok ? 'text-good-ink' : 'text-warning-ink')}>
      {ok ? <Check size={12} /> : <X size={12} />} {label}
    </div>
  )
}
