import { useTranslation } from 'react-i18next'
import { Fingerprint, KeyRound, Laptop, Smartphone } from 'lucide-react'
import { useTab } from '@/lib/useTab'
import { useMe } from '@/api/session'
import { setLanguage } from '@/i18n'
import { formatDateTime } from '@/lib/format'
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Input,
  PageHeader,
  Select,
  Tabs,
} from '@/components/ui/primitives'

const TABS = ['profile', 'security', 'sessions'] as const

export function AccountPage() {
  const { t, i18n } = useTranslation()
  const me = useMe()
  const [tab, setTab] = useTab(TABS, 'profile')
  // Credentials and profile live in Keycloak (SSO accounts in their provider from M0b).
  const isSso = false

  return (
    <>
      <PageHeader title={t('account.title')} description={t('account.description')} />
      <Tabs tabs={TABS.map((id) => ({ id, label: t(`account.tabs.${id}`) }))} value={tab} onChange={setTab} />

      {tab === 'profile' && (
        <Card className="max-w-2xl">
          <CardHeader title={t('account.profile')} />
          <CardBody className="space-y-4">
            <Field label={t('account.name')}>
              <Input defaultValue={me?.user.displayName} readOnly />
            </Field>
            <Field label={t('account.email')} hint={isSso ? t('account.managedBySso') : undefined}>
              <Input defaultValue={me?.user.email} disabled={isSso} readOnly />
            </Field>
            <Field label={t('account.language')} hint={t('account.languageHint')}>
              <Select value={i18n.language} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')}>
                <option value="en">English</option>
                <option value="es">Español</option>
              </Select>
            </Field>
            <Button variant="primary">{t('common.save')}</Button>
          </CardBody>
        </Card>
      )}

      {tab === 'security' && (
        <div className="grid max-w-4xl gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader
              title={t('account.password')}
              subtitle={
                isSso
                  ? t('account.passwordSso')
                  : t('account.passwordChanged', { date: formatDateTime('2026-07-02T10:00:00Z') })
              }
            />
            <CardBody className="space-y-4">
              <Field label={t('account.currentPassword')}>
                <Input type="password" disabled={isSso} />
              </Field>
              <Field label={t('account.newPassword')}>
                <Input type="password" disabled={isSso} />
              </Field>
              <Button disabled={isSso}>
                <KeyRound size={16} /> {t('account.changePassword')}
              </Button>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t('account.mfa')} subtitle={t('account.mfaRequired')} />
            <CardBody className="space-y-3">
              <MfaMethod
                Icon={Smartphone}
                name={t('account.authenticatorApp')}
                detail="Microsoft Authenticator"
                active
              />
              <MfaMethod Icon={Fingerprint} name={t('account.passkey')} detail="MacBook Pro — Touch ID" active />
              <MfaMethod
                Icon={KeyRound}
                name={t('account.recoveryCodes')}
                detail={t('account.recoveryRemaining', { count: 8 })}
                active
              />
              <div className="flex flex-wrap gap-2 pt-2">
                <Button size="sm">{t('account.addPasskey')}</Button>
                <Button size="sm" variant="ghost">
                  {t('account.regenerateCodes')}
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {tab === 'sessions' && (
        <Card className="max-w-3xl">
          <CardHeader
            title={t('account.activeSessions')}
            subtitle={t('account.sessionPolicy')}
            action={
              <Button size="sm" variant="danger">
                {t('account.signOutOthers')}
              </Button>
            }
          />
          <CardBody className="space-y-3">
            {[
              { device: 'Chrome · macOS', where: 'Quito, EC', time: '2026-09-28T09:40:00Z', current: true },
              { device: 'Edge · Windows 11', where: 'Guayaquil, EC', time: '2026-09-27T17:10:00Z', current: false },
            ].map((s) => (
              <div key={s.device} className="flex items-center gap-3 rounded-md border border-border p-3">
                <Laptop size={18} className="text-muted" />
                <div className="flex-1 text-sm">
                  <div className="text-text">{s.device}</div>
                  <div className="text-xs text-muted">
                    {s.where} · {formatDateTime(s.time)}
                  </div>
                </div>
                {s.current ? (
                  <Badge tone="good">{t('account.thisDevice')}</Badge>
                ) : (
                  <Button size="sm" variant="ghost">
                    {t('account.revoke')}
                  </Button>
                )}
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </>
  )
}

function MfaMethod({
  Icon,
  name,
  detail,
  active,
}: {
  Icon: typeof Smartphone
  name: string
  detail: string
  active: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center gap-3 rounded-md border border-border p-3">
      <Icon size={18} className="text-muted" />
      <div className="flex-1 text-sm">
        <div className="text-text">{name}</div>
        <div className="text-xs text-muted">{detail}</div>
      </div>
      {active && <Badge tone="good">{t('common.active')}</Badge>}
    </div>
  )
}
