// Design of the M0b Keycloak theme (Keycloakify, D-27): not routed in M0, where Keycloak shows its own pages.
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Fingerprint } from 'lucide-react'
import { clearChallenge, pendingChallenge, signIn } from '@/lib/session'
import { Button, Field, Input } from '@/components/ui/primitives'
import { AuthLayout } from './AuthLayout'
import { Divider } from './AuthLayout'

export function MfaPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const challenge = pendingChallenge()
  const [mode, setMode] = useState<'totp' | 'recovery'>('totp')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (!challenge) {
    return (
      <AuthLayout title={t('auth.mfa.expiredTitle')} subtitle={t('auth.mfa.expiredBody')}>
        <Link to="/login" className="text-sm font-medium text-info hover:underline">
          {t('auth.backToSignIn')}
        </Link>
      </AuthLayout>
    )
  }

  function complete() {
    signIn({ email: challenge!.email, method: 'password' })
    const to = challenge!.redirect ?? '/'
    clearChallenge()
    void navigate({ to })
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const valid = mode === 'totp' ? /^\d{6}$/.test(code) : /^[A-Z0-9]{4}-[A-Z0-9]{4}$/i.test(code)
    if (!valid) {
      setError(t(mode === 'totp' ? 'auth.mfa.invalidCode' : 'auth.mfa.invalidRecovery'))
      return
    }
    complete()
  }

  return (
    <AuthLayout
      title={t('auth.mfa.title')}
      subtitle={t(mode === 'totp' ? 'auth.mfa.subtitleTotp' : 'auth.mfa.subtitleRecovery')}
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <Field label={t(mode === 'totp' ? 'auth.mfa.code' : 'auth.mfa.recoveryCode')}>
          <Input
            inputMode={mode === 'totp' ? 'numeric' : 'text'}
            autoComplete="one-time-code"
            maxLength={mode === 'totp' ? 6 : 9}
            value={code}
            onChange={(e) => setCode(e.target.value.trim())}
            placeholder={mode === 'totp' ? '123456' : 'ABCD-1234'}
            className="text-center font-mono text-lg tracking-[0.4em]"
            autoFocus
          />
        </Field>
        {error && (
          <p className="text-sm text-critical-ink" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" className="w-full">
          {t('auth.mfa.verify')}
        </Button>
      </form>
      <Divider label={t('auth.mfa.otherMethods')} />
      <div className="space-y-2">
        <Button className="w-full" onClick={complete}>
          <Fingerprint size={16} /> {t('auth.mfa.usePasskey')}
        </Button>
        <Button
          variant="ghost"
          className="w-full"
          onClick={() => {
            setMode(mode === 'totp' ? 'recovery' : 'totp')
            setCode('')
            setError(null)
          }}
        >
          {t(mode === 'totp' ? 'auth.mfa.useRecovery' : 'auth.mfa.useTotp')}
        </Button>
      </div>
      <p className="mt-6 text-xs text-muted">{t('auth.mfa.lockoutNote')}</p>
    </AuthLayout>
  )
}
