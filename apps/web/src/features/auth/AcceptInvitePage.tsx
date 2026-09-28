import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Check, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { startMfaChallenge } from '@/lib/session'
import { Button, Field, Input } from '@/components/ui/primitives'
import { AuthLayout } from './AuthLayout'

// Password policy shown to the user; the server enforces the tenant's configured policy.
const policy = [
  { key: 'length', test: (p: string) => p.length >= 12 },
  { key: 'upper', test: (p: string) => /[A-Z]/.test(p) },
  { key: 'lower', test: (p: string) => /[a-z]/.test(p) },
  { key: 'number', test: (p: string) => /\d/.test(p) },
  { key: 'symbol', test: (p: string) => /[^A-Za-z0-9]/.test(p) },
] as const

export function AcceptInvitePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const valid = policy.every((rule) => rule.test(password)) && password === confirm

  return (
    <AuthLayout title={t('auth.invite.title')} subtitle={t('auth.invite.subtitle', { tenant: 'Andes Bank', role: t('roles.auditor') })}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (!valid) return
          startMfaChallenge('jmena@andesbank.example')
          void navigate({ to: '/login/mfa' })
        }}
      >
        <Field label={t('auth.invite.name')}>
          <Input defaultValue="Jorge Mena" autoComplete="name" />
        </Field>
        <Field label={t('auth.invite.newPassword')}>
          <Input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
          {policy.map((rule) => {
            const ok = rule.test(password)
            return (
              <li key={rule.key} className={cn('flex items-center gap-1.5', ok ? 'text-good-ink' : 'text-muted')}>
                {ok ? <Check size={12} /> : <X size={12} />} {t(`auth.policy.${rule.key}`)}
              </li>
            )
          })}
        </ul>
        <Field label={t('auth.invite.confirmPassword')}>
          <Input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <p className="text-xs text-muted">{t('auth.invite.mfaNext')}</p>
        <Button type="submit" variant="primary" className="w-full" disabled={!valid}>
          {t('auth.invite.activate')}
        </Button>
      </form>
    </AuthLayout>
  )
}
