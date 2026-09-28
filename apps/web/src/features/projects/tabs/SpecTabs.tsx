import { useState } from 'react'
import { useSearch } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Check, Download, FileCode2, Folder, GitPullRequest, MessageSquare, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { codeFiles, compareItems, contracts, detectedGaps, figmaFrames, rules, screenSpecs } from '@/mocks/data'
import type { Project, Rule } from '@/mocks/types'
import { Badge, Button, Card, CardBody, CardHeader, Code, Select, Table, Td, Th } from '@/components/ui/primitives'
import { Notice } from '../NewProjectWizard'
import { toast } from '@/components/ui/overlay'
import { AddInputForm } from '../InputForms'
import { PrototypeChat } from '../PrototypeChat'
import { DecisionList } from '@/features/decisions/DecisionCard'
import { UserStoriesView } from '../stories/UserStoriesView'
import { MigrationPlanView } from '../stories/MigrationPlanView'
import { useStories } from '../stories/store'
import { updateDecisions, useDecisions } from '@/features/decisions/store'

const ruleStatusTone = { approved: 'good', inReview: 'info', question: 'warning', draft: 'neutral' } as const

const SPEC_VIEWS = ['rules', 'stories', 'plan', 'screens', 'contracts', 'questions'] as const

export function SpecificationTab({ project }: { project: Project }) {
  const { t } = useTranslation()
  const decisions = useDecisions(project.id)
  const open = decisions.filter((d) => d.status === 'open').length
  const search = useSearch({ strict: false }) as { view?: string }
  const initial = SPEC_VIEWS.find((v) => v === search.view) ?? 'rules'
  const [view, setView] = useState<(typeof SPEC_VIEWS)[number]>(initial)
  const { stories, plan } = useStories()
  const counts = {
    rules: rules.length,
    stories: stories.filter((s) => s.status !== 'discarded' && s.status !== 'merged').length,
    plan: plan.length,
    screens: screenSpecs.length,
    contracts: contracts.length,
    questions: open,
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 rounded-lg border border-border bg-surface p-1" role="tablist">
        {SPEC_VIEWS.map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={cn('rounded-md px-3 py-1.5 text-sm', view === v ? 'bg-brand text-brand-contrast' : 'text-text-2 hover:bg-surface-2')}
          >
            {t(`spec.views.${v}`)} <span className="ml-1 text-xs opacity-80">{counts[v]}</span>
          </button>
        ))}
      </div>
      {view === 'rules' && <RulesView project={project} />}
      {view === 'stories' && <UserStoriesView />}
      {view === 'plan' && <MigrationPlanView />}
      {view === 'screens' && <ScreensView />}
      {view === 'contracts' && <ContractsView />}
      {view === 'questions' && <DecisionList decisions={decisions} onChange={updateDecisions} />}
    </div>
  )
}

function ScreensView() {
  const { t } = useTranslation()
  const [selected, setSelected] = useState(screenSpecs[0].id)
  const screen = screenSpecs.find((x) => x.id === selected)!
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
      <Card>
        <ul className="divide-y divide-border">
          {screenSpecs.map((x) => (
            <li key={x.id}>
              <button onClick={() => setSelected(x.id)} className={cn('w-full px-4 py-3 text-left hover:bg-surface-2', selected === x.id && 'bg-surface-2')}>
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted">{x.id}</span>
                  <Badge tone={ruleStatusTone[x.status]} className="ml-auto">{t(`ruleStatus.${x.status}`)}</Badge>
                </div>
                <div className="mt-1 text-sm font-medium text-text">{x.name}</div>
                <div className="text-xs text-muted">{x.source}</div>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader title={screen.name} subtitle={t('spec.screenSource', { source: screen.source })} />
        <Table>
          <thead>
            <tr>
              <Th>{t('spec.field')}</Th>
              <Th>{t('spec.type')}</Th>
              <Th>{t('spec.required')}</Th>
              <Th>{t('spec.validationRule')}</Th>
              <Th>{t('spec.editable')}</Th>
            </tr>
          </thead>
          <tbody>
            {screen.fields.map((f) => (
              <tr key={f.name}>
                <Td>
                  <div className="text-text">{f.label}</div>
                  <div className="font-mono text-xs text-muted">{f.name}</div>
                </Td>
                <Td className="font-mono text-xs">{f.type}</Td>
                <Td>{f.required ? t('common.yes') : t('common.no')}</Td>
                <Td>{f.validation}</Td>
                <Td>{f.readOnly ? t('spec.readOnly') : t('spec.editableYes')}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="text-xs font-medium text-muted uppercase">{t('spec.actions')}</div>
            <ul className="mt-1 space-y-1 text-sm text-text-2">
              {screen.actions.map((a) => (
                <li key={a} className="font-mono text-xs">{a}</li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-xs font-medium text-muted uppercase">{t('spec.states')}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {(['empty', 'loading', 'error', 'success'] as const).map((st) => (
                <Badge key={st} tone={screen.states.includes(st) ? 'good' : 'warning'}>
                  {t(`spec.stateNames.${st}`)} {screen.states.includes(st) ? '✓' : '—'}
                </Badge>
              ))}
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}

function ContractsView() {
  const { t } = useTranslation()
  return (
    <Card>
      <CardHeader title={t('spec.contractsTitle')} subtitle={t('spec.contractsHint')} />
      <Table>
        <thead>
          <tr>
            <Th>Id</Th>
            <Th>{t('spec.operation')}</Th>
            <Th>{t('architecture.services')}</Th>
            <Th>{t('architecture.rules')}</Th>
            <Th>{t('inputs.status')}</Th>
          </tr>
        </thead>
        <tbody>
          {contracts.map((c) => (
            <tr key={c.id}>
              <Td className="font-mono text-xs">{c.id}</Td>
              <Td>
                <span className="mr-2 rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-text">{c.method}</span>
                <span className="font-mono text-xs text-text">{c.path}</span>
              </Td>
              <Td className="font-mono text-xs">{c.service}</Td>
              <Td className="font-mono text-xs">{c.rules.join(', ')}</Td>
              <Td>
                <Badge tone={ruleStatusTone[c.status]}>{t(`ruleStatus.${c.status}`)}</Badge>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
  )
}

function RulesView({ project }: { project: Project }) {
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
          <Button size="sm" variant="primary" onClick={() => toast(t('spec.gateApproved'))}>
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
              <Button size="sm" variant="primary" onClick={() => toast(t('spec.ruleApproved', { id: selected.id }))}>
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
  const [addSource, setAddSource] = useState<'screens' | 'figma' | 'prototype' | null>(null)
  const references = isModernization
    ? [
        { kind: 'bms', name: 'COACTUP.bms, COCRDUP.bms', detail: t('uiDesign.refs.fromInventory') },
        { kind: 'screens', name: 'current-3270-screens.png (4)', detail: t('uiDesign.refs.uploaded') },
      ]
    : [
        { kind: 'figma', name: 'onboarding.fig · v14', detail: 'figma.com/design/AbC123' },
        { kind: 'screens', name: 'current-onboarding-screens.png (6)', detail: t('uiDesign.refs.uploaded') },
        { kind: 'prototype', name: 'Onboarding clickable prototype', detail: 'figma.com/proto/AbC123' },
      ]
  return (
    <div className="space-y-6">
      <AddInputForm key={addSource ?? 'none'} open={!!addSource} onClose={() => setAddSource(null)} flow={project.flow} initialSource={addSource ?? undefined} />
      <Notice tone="info">{t(isModernization ? 'uiDesign.fromBms' : 'uiDesign.fromFigma')}</Notice>
      <Card>
        <CardHeader
          title={t('uiDesign.refs.title')}
          subtitle={t('uiDesign.refs.hint')}
          action={
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setAddSource('screens')}>
                {t('uiDesign.refs.addScreens')}
              </Button>
              <Button size="sm" onClick={() => setAddSource('figma')}>
                {t('uiDesign.refs.addFigma')}
              </Button>
              <Button size="sm" onClick={() => setAddSource('prototype')}>
                {t('uiDesign.refs.addPrototype')}
              </Button>
            </div>
          }
        />
        <CardBody className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {references.map((r) => (
            <div key={r.name} className="rounded-md border border-border p-3 text-sm">
              <Badge>{t(`uiDesign.refs.kinds.${r.kind}`)}</Badge>
              <div className="mt-1.5 truncate font-medium text-text">{r.name}</div>
              <div className="truncate text-xs text-muted">{r.detail}</div>
            </div>
          ))}
        </CardBody>
      </Card>
      <div className="grid gap-6 xl:grid-cols-2">
        {isModernization ? (
          <Card>
            <CardHeader title={t('uiDesign.legacyScreen')} subtitle="COACTUP · COACTUPC" />
            <CardBody>
              <pre className="overflow-x-auto rounded-md bg-black p-4 font-mono text-[11px] leading-5 text-[#33ff66]">{bmsScreen}</pre>
            </CardBody>
          </Card>
        ) : (
          <Card>
            <CardHeader title={t('uiDesign.figmaFrames')} subtitle="onboarding.fig · v14" />
            <CardBody className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {figmaFrames.map((f) => (
                <div key={f.id} className="rounded-md border border-border p-2">
                  <div className="flex aspect-[3/4] items-center justify-center rounded bg-surface-2 text-[10px] text-muted">
                    {f.node === '—' ? t('uiDesign.missingFrame') : `node ${f.node}`}
                  </div>
                  <div className="mt-1.5 truncate text-xs font-medium text-text">{f.name}</div>
                  <div className="flex items-center justify-between text-[10px] text-muted">
                    <span>{f.mapped}</span>
                    {f.gaps > 0 ? <Badge tone="warning">{t('uiDesign.gaps', { count: f.gaps })}</Badge> : <Badge tone="good">OK</Badge>}
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>
        )}
        <Card>
          <CardHeader title={t('uiDesign.prototype')} subtitle={t('uiDesign.prototypeHint')} action={<Badge tone="warning">{t('uiDesign.awaitingC2')}</Badge>} />
          <CardBody>
            <PrototypeForm flow={project.flow} />
          </CardBody>
        </Card>
      </div>
      {!isModernization && (
        <Card>
          <CardHeader title={t('uiDesign.gapsTitle')} subtitle={t('uiDesign.gapsHint')} />
          <Table>
            <thead>
              <tr>
                <Th>Id</Th>
                <Th>{t('uiDesign.gapKind')}</Th>
                <Th>{t('uiDesign.gapWhere')}</Th>
                <Th>{t('uiDesign.gapDetail')}</Th>
              </tr>
            </thead>
            <tbody>
              {detectedGaps.map((g) => (
                <tr key={g.id}>
                  <Td className="font-mono text-xs">{g.id}</Td>
                  <Td>
                    <Badge tone={g.kind === 'contradiction' ? 'critical' : 'warning'}>{t(`uiDesign.gapKinds.${g.kind}`)}</Badge>
                  </Td>
                  <Td className="text-text">{g.target}</Td>
                  <Td>{g.detail}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
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
              <Button size="sm" variant="primary" onClick={() => toast(t('uiDesign.approved'))}>
                {t('uiDesign.approve')}
              </Button>
              <Button size="sm">{t('uiDesign.requestChanges')}</Button>
            </div>
          </CardBody>
        </Card>
      </div>
      <PrototypeChat screen={isModernization ? 'Update account (SCR-001)' : 'Personal data (SCR-102)'} />
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
function PrototypeForm({ flow }: { flow: Project['flow'] }) {
  const fields =
    flow === 'modernization'
      ? ([
          ['Account number', '00000001234', true],
          ['Status', 'Active', false],
          ['Credit limit', '5,000.00', false],
          ['Current balance', '4,900.00', true],
          ['First name', 'María', false],
          ['Last name', 'Torres', false],
        ] as const)
      : ([
          ['First name', 'Ana', false],
          ['Last name', 'Vélez', false],
          ['National ID', '1712345678', false],
          ['Date of birth', '1994-05-12', false],
          ['Email', 'ana@example.com', false],
          ['Mobile phone', '+593 99 123 4567', false],
        ] as const)
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
          <Code>{codeFiles[file] ?? ''}</Code>
        </div>
      </div>
    </Card>
    </div>
  )
}

export function TraceabilityTab() {
  const { t } = useTranslation()
  const search = useSearch({ strict: false }) as { rule?: string }
  const [ruleId, setRuleId] = useState(compareItems.find((c) => c.ruleId === search.rule)?.ruleId ?? compareItems[0].ruleId)
  const [by, setBy] = useState<'rule' | 'program'>('rule')
  const item = compareItems.find((c) => c.ruleId === ruleId)!
  const rule = rules.find((r) => r.id === item.ruleId)
  const differing = item.outputs.filter((o) => !o.same).length

  return (
    <div className="space-y-4">
      <Notice tone="info">{t('traceability.hint')}</Notice>
      <div className="grid gap-4 xl:grid-cols-[220px_minmax(0,1fr)]">
        <Card>
          <div className="flex border-b border-border p-1 text-xs">
            {(['rule', 'program'] as const).map((b) => (
              <button key={b} onClick={() => setBy(b)} aria-pressed={by === b} className={cn('flex-1 rounded px-2 py-1', by === b ? 'bg-brand text-brand-contrast' : 'text-muted')}>
                {t(`traceability.by.${b}`)}
              </button>
            ))}
          </div>
          <ul className="p-1">
            {compareItems.map((c) => (
              <li key={c.ruleId}>
                <button onClick={() => setRuleId(c.ruleId)} className={cn('w-full rounded-md px-3 py-2 text-left hover:bg-surface-2', ruleId === c.ruleId && 'bg-surface-2')}>
                  <div className="font-mono text-xs text-text">{by === 'rule' ? c.ruleId : c.program}</div>
                  <div className="truncate text-xs text-muted">{by === 'rule' ? rules.find((r) => r.id === c.ruleId)?.name : c.ruleId}</div>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <div className="min-w-0 space-y-4">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title={t('traceability.legacy')} subtitle={item.legacyRef} />
              <CardBody>
                <CodeLines lines={item.legacy} highlight={item.legacyHighlight} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={t('traceability.target')} subtitle={item.targetRef} />
              <CardBody>
                <CodeLines lines={item.target} highlight={item.targetHighlight} />
              </CardBody>
            </Card>
          </div>
          <Card>
            <CardHeader title={t('traceability.rule')} subtitle={`${item.ruleId} · ${rule?.priority ?? ''}`} />
            <CardBody className="grid gap-4 text-sm md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <div className="space-y-3">
                <p className="text-text">{rule?.statement}</p>
                {rule && <Code className="whitespace-pre-wrap">{`Given ${rule.given}\nWhen ${rule.when}\nThen ${rule.then}`}</Code>}
              </div>
              <div className="space-y-1.5 text-xs">
                <TraceLink ok label={t('traceability.citationVerified')} />
                <TraceLink ok label={t('traceability.implementationVerified')} />
                <TraceLink ok={rule?.testStatus === 'tested'} label={t(rule?.testStatus === 'tested' ? 'traceability.testPassed' : 'traceability.testNotRun')} />
              </div>
            </CardBody>
          </Card>
          <Card>
            <CardHeader
              title={t('traceability.outputs')}
              subtitle={t('traceability.outputsHint')}
              action={differing > 0 ? <Badge tone="critical">{t('traceability.differs', { count: differing })}</Badge> : <Badge tone="good">{t('traceability.allSame')}</Badge>}
            />
            <Table>
              <thead>
                <tr>
                  <Th>{t('traceability.case')}</Th>
                  <Th>{t('traceability.input')}</Th>
                  <Th>{t('traceability.legacyOutput')}</Th>
                  <Th>{t('traceability.newOutput')}</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {item.outputs.map((o) => (
                  <tr key={o.caseId} className={cn(!o.same && 'bg-critical/5')}>
                    <Td className="font-mono text-xs">{o.caseId}</Td>
                    <Td className="text-xs">{o.input}</Td>
                    <Td className="font-mono text-xs text-text">{o.legacy}</Td>
                    <Td className={cn('font-mono text-xs', o.same ? 'text-text' : 'text-critical-ink')}>{o.next}</Td>
                    <Td>{o.same ? <Badge tone="good">{t('traceability.same')}</Badge> : <Badge tone="critical">{t('traceability.different')}</Badge>}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            {differing > 0 && (
              <CardBody>
                <Notice tone="warning">{t('traceability.differenceNote')}</Notice>
              </CardBody>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function CodeLines({ lines, highlight }: { lines: string[]; highlight: number[] }) {
  return (
    <pre className="overflow-x-auto rounded-md bg-surface-2 py-2 font-mono text-xs leading-relaxed">
      {lines.map((line, i) => (
        <div key={i} className={cn('flex gap-3 px-3', highlight.includes(i) && 'bg-warning/25')}>
          <span className="w-5 shrink-0 text-right text-muted select-none">{i + 1}</span>
          <span className="whitespace-pre text-text">{line}</span>
        </div>
      ))}
    </pre>
  )
}

function TraceLink({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className={cn('flex items-center gap-1.5', ok ? 'text-good-ink' : 'text-warning-ink')}>
      {ok ? <Check size={12} /> : <X size={12} />} {label}
    </div>
  )
}
