import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Building2, KeyRound, Loader2 } from 'lucide-react'
import { discoverRealm, signIn, startMfaChallenge } from '@/lib/session'
import { Button, Field, Input } from '@/components/ui/primitives'
import { AuthLayout } from './AuthLayout'

const ssoProviders = ['Microsoft Entra ID', 'Okta', 'Google Workspace'] as const

export function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as { redirect?: string }
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [step, setStep] = useState<'email' | 'credentials'>('email')
  const [redirecting, setRedirecting] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [companySso, setCompanySso] = useState(false)
  const realm = step === 'credentials' ? discoverRealm(email) : null

  const goTo = () => void navigate({ to: search.redirect ?? '/' })

  // SSO: the browser is sent to the identity provider; MFA is enforced there.
  function startSso(provider: string) {
    setRedirecting(provider)
    window.setTimeout(() => {
      signIn({ email: email || 'david.balseca@nexti.example', method: 'sso', provider })
      goTo()
    }, 900)
  }

  function onContinue(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!/^\S+@\S+\.\S+$/.test(email)) {
      setError(t('auth.errors.invalidEmail'))
      return
    }
    setStep('credentials')
  }

  function onPassword(e: FormEvent) {
    e.preventDefault()
    if (password.length < 8) {
      setError(t('auth.errors.invalidCredentials'))
      return
    }
    startMfaChallenge(email, search.redirect)
    void navigate({ to: '/login/mfa' })
  }

  if (redirecting) {
    return (
      <AuthLayout title={t('auth.redirectingTitle')} subtitle={t('auth.redirectingBody', { provider: redirecting })}>
        <div className="flex items-center gap-3 text-sm text-text-2">
          <Loader2 className="animate-spin" size={18} /> {t('auth.redirecting')}
        </div>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout title={t('auth.signInTitle')} subtitle={t('auth.signInSubtitle')}>
      {step === 'email' && (
        <form onSubmit={onContinue} className="space-y-4" noValidate>
          <Field label={t('auth.workEmail')}>
            <Input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
              autoFocus
            />
          </Field>
          {error && (
            <p className="text-sm text-critical-ink" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" className="w-full">
            {t('common.continue')}
          </Button>
          <p className="text-xs text-muted">{t('auth.realmHint')}</p>
        </form>
      )}

      {step === 'credentials' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-md bg-surface-2 px-3 py-2 text-sm">
            <span className="truncate text-text">{email}</span>
            <button
              className="text-xs font-medium text-info hover:underline"
              onClick={() => {
                setStep('email')
                setPassword('')
                setError(null)
              }}
            >
              {t('common.change')}
            </button>
          </div>

          {realm && (
            <div className="space-y-2">
              <Button variant="primary" className="w-full" onClick={() => startSso(realm.provider)}>
                <Building2 size={16} /> {t('auth.continueWith', { provider: realm.provider })}
              </Button>
              {realm.enforced && <p className="text-xs text-muted">{t('auth.ssoEnforced')}</p>}
            </div>
          )}

          {!realm?.enforced && (
            <>
              {realm && <Divider label={t('auth.orUsePassword')} />}
              <form onSubmit={onPassword} className="space-y-4" noValidate>
                <Field label={t('auth.password')}>
                  <Input
                    type="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoFocus={!realm}
                  />
                </Field>
                {error && (
                  <p className="text-sm text-critical-ink" role="alert">
                    {error}
                  </p>
                )}
                <div className="flex justify-end">
                  <Link to="/forgot-password" className="text-sm font-medium text-info hover:underline">
                    {t('auth.forgotPassword')}
                  </Link>
                </div>
                <Button type="submit" variant={realm ? 'secondary' : 'primary'} className="w-full">
                  <KeyRound size={16} /> {t('auth.signIn')}
                </Button>
              </form>
            </>
          )}
        </div>
      )}

      {!realm && (
        <>
          <Divider label={t('auth.orSso')} />
          <div className="space-y-2">
            {ssoProviders.map((provider) => (
              <Button key={provider} className="w-full" onClick={() => startSso(provider)}>
                {t('auth.continueWith', { provider })}
              </Button>
            ))}
            {!companySso ? (
              <Button variant="ghost" className="w-full" onClick={() => setCompanySso(true)}>
                {t('auth.otherSso')}
              </Button>
            ) : (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  startSso(t('auth.companySso'))
                }}
              >
                <Input
                  placeholder={t('auth.companyDomainPlaceholder')}
                  aria-label={t('auth.companyDomain')}
                  autoFocus
                />
                <Button type="submit">{t('common.continue')}</Button>
              </form>
            )}
          </div>
        </>
      )}

      <p className="mt-8 text-center text-xs text-muted">
        {t('auth.invitedQuestion')}{' '}
        <Link to="/accept-invite" className="font-medium text-info hover:underline">
          {t('auth.acceptInvite')}
        </Link>
      </p>
    </AuthLayout>
  )
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="my-6 flex items-center gap-3 text-xs text-muted">
      <span className="h-px flex-1 bg-border" />
      {label}
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}
