import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, RefreshCw, Server, Trash2 } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import {
  useDeleteLegacyExecution,
  useLegacyExecution,
  useSetLegacyExecution,
  useTestLegacyExecution,
  type LegacyExecution,
  type ProjectDetail,
} from '@/api/projects'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { useErrorText } from './ProjectInputs'

type Mode = LegacyExecution['mode']
type Kind = NonNullable<LegacyExecution['kind']>
const MODES: Mode[] = ['auto', 'traces', 'live']
const KINDS: Kind[] = ['ibmi', 'sybase']
const DEFAULT_PORT: Record<Kind, string> = { ibmi: '8476', sybase: '5000' }

/** How the project's legacy runs for the golden master (ADR-0052): by its inputs, from recorded traces (PARTLY PROVEN
 * at most) or on a live test system of the customer: an IBM i or a Sybase ASE (ADR-0055). The credentials are
 * written once and never shown again. */
export function LegacyExecutionCard({ project, canEdit }: { project: ProjectDetail; canEdit: boolean }) {
  const { t } = useTranslation()
  const current = useLegacyExecution(project.id)
  const save = useSetLegacyExecution(project.id)
  const test = useTestLegacyExecution(project.id)
  const remove = useDeleteLegacyExecution(project.id)
  const errorText = useErrorText()
  const [editing, setEditing] = useState(false)
  const [mode, setMode] = useState<Mode>('auto')
  const [kind, setKind] = useState<Kind>('ibmi')
  const [host, setHost] = useState('')
  const [port, setPort] = useState(DEFAULT_PORT.ibmi)
  const [library, setLibrary] = useState('')
  const [programs, setPrograms] = useState('')
  const [database, setDatabase] = useState('')
  const [user, setUser] = useState('')
  const [password, setPassword] = useState('')
  const setting = current.data

  function start() {
    const config = (setting?.config ?? {}) as Record<string, unknown>
    const savedKind: Kind = setting?.kind ?? 'ibmi'
    setMode(setting?.mode ?? 'auto')
    setKind(savedKind)
    setHost(String(config.host ?? ''))
    setPort(String(config.port ?? DEFAULT_PORT[savedKind]))
    setLibrary(String(config.library ?? ''))
    setPrograms(config.programs ? String(config.programs) : '')
    setDatabase(String(config.database ?? ''))
    setUser('')
    setPassword('')
    setEditing(true)
  }

  function changeKind(next: Kind) {
    setKind(next)
    setPort(DEFAULT_PORT[next])
  }

  async function submit() {
    const live = mode === 'live'
    const config =
      kind === 'ibmi'
        ? { host: host.trim(), port: Number(port), library: library.trim(), programs: programs.trim() || null }
        : { host: host.trim(), port: Number(port), database: database.trim() }
    try {
      await save.mutateAsync({
        mode,
        kind: live ? kind : null,
        config: live ? config : {},
        user: live && user ? user : null,
        password: live && user ? password : null,
        clearCredentials: !live,
      })
      setEditing(false)
      toast(t('legacyExecution.saved'))
    } catch (error) {
      toast(errorText(error))
    }
  }

  async function check() {
    try {
      await test.mutateAsync()
    } catch (error) {
      toast(errorText(error))
    }
  }

  const config = (setting?.config ?? {}) as Record<string, unknown>
  const target = kind === 'ibmi' ? library.trim() : database.trim()
  const liveReady = host.trim() && target && (setting?.hasCredentials || (user && password))
  return (
    <Card>
      <CardHeader
        title={t('legacyExecution.title')}
        subtitle={t('legacyExecution.hint')}
        action={
          canEdit &&
          !editing && (
            <Button size="sm" onClick={start}>
              <Server size={14} /> {setting ? t('common.edit') : t('legacyExecution.configure')}
            </Button>
          )
        }
      />
      <CardBody className="space-y-3">
        {editing ? (
          <>
            <Field label={t('legacyExecution.mode')} hint={t(`legacyExecution.modeHint.${mode}`)}>
              <Select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
                {MODES.map((m) => (
                  <option key={m} value={m}>
                    {t(`legacyExecution.modes.${m}`)}
                  </option>
                ))}
              </Select>
            </Field>
            {mode === 'live' && (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t('legacyExecution.kind')}>
                  <Select value={kind} onChange={(e) => changeKind(e.target.value as Kind)}>
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {t(`legacyExecution.kinds.${k}`)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <div />
                <Field
                  label={t(kind === 'ibmi' ? 'legacyExecution.host' : 'legacyExecution.sybaseHost')}
                  hint={t('legacyExecution.hostHint')}
                >
                  <Input
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    placeholder={kind === 'ibmi' ? 'ibmi.example.com' : 'ase-test.example.com'}
                  />
                </Field>
                <Field
                  label={t(kind === 'ibmi' ? 'legacyExecution.port' : 'legacyExecution.sybasePort')}
                  hint={t(kind === 'ibmi' ? 'legacyExecution.portHint' : 'legacyExecution.sybasePortHint')}
                >
                  <Input value={port} inputMode="numeric" onChange={(e) => setPort(e.target.value)} />
                </Field>
                {kind === 'ibmi' ? (
                  <>
                    <Field label={t('legacyExecution.library')} hint={t('legacyExecution.libraryHint')}>
                      <Input value={library} onChange={(e) => setLibrary(e.target.value.toUpperCase())} />
                    </Field>
                    <Field label={t('legacyExecution.programs')} hint={t('legacyExecution.programsHint')}>
                      <Input value={programs} onChange={(e) => setPrograms(e.target.value.toUpperCase())} />
                    </Field>
                  </>
                ) : (
                  <Field label={t('legacyExecution.database')} hint={t('legacyExecution.databaseHint')}>
                    <Input value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="cob_pagos" />
                  </Field>
                )}
                <Field
                  label={t('legacyExecution.user')}
                  hint={setting?.hasCredentials ? t('legacyExecution.credentialsKept') : undefined}
                >
                  <Input autoComplete="off" value={user} onChange={(e) => setUser(e.target.value)} />
                </Field>
                <Field label={t('legacyExecution.password')}>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </Field>
              </div>
            )}
            <div className="flex gap-2">
              <Button
                variant="primary"
                disabled={save.isPending || (mode === 'live' && !liveReady) || Boolean(user) !== Boolean(password)}
                onClick={() => void submit()}
              >
                {t('common.save')}
              </Button>
              <Button variant="ghost" onClick={() => setEditing(false)}>
                {t('common.cancel')}
              </Button>
            </div>
          </>
        ) : setting ? (
          <>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <Server size={16} className="text-muted" />
              <span className="text-text">{t(`legacyExecution.modes.${setting.mode}`)}</span>
              {setting.mode === 'live' && (
                <>
                  <span className="text-text-2">{t(`legacyExecution.kinds.${setting.kind ?? 'ibmi'}`)}</span>
                  <span className="font-mono text-text">
                    {String(config.host)}:{String(config.port)}
                  </span>
                  <Badge>{String(setting.kind === 'sybase' ? config.database : config.library)}</Badge>
                  {setting.hasCredentials && <Badge tone="info">{t('legacyExecution.withCredentials')}</Badge>}
                </>
              )}
              <Badge tone={setting.status === 'ok' ? 'good' : setting.status === 'failed' ? 'critical' : 'neutral'}>
                {t(`inputs.repositoryStatus.${setting.status}`)}
              </Badge>
            </div>
            {setting.mode === 'traces' && <p className="text-xs text-text-2">{t('legacyExecution.tracesCeiling')}</p>}
            {setting.lastCheckDetail && (
              <p className="text-xs text-text-2">
                {setting.lastCheckDetail}
                {setting.lastCheckedAt && ` · ${formatDateTime(setting.lastCheckedAt)}`}
              </p>
            )}
            {canEdit && (
              <div className="flex gap-2">
                {setting.mode === 'live' && (
                  <Button size="sm" disabled={test.isPending} onClick={() => void check()}>
                    {test.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}{' '}
                    {t('ai.testConnection')}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (window.confirm(t('legacyExecution.confirmRemove')))
                      void remove.mutateAsync().then(() => toast(t('legacyExecution.removed')))
                  }}
                >
                  <Trash2 size={14} /> {t('common.remove')}
                </Button>
              </div>
            )}
          </>
        ) : (
          <p className="text-sm text-muted">{t('legacyExecution.none')}</p>
        )}
      </CardBody>
    </Card>
  )
}
