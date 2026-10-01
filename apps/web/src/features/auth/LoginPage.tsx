import { useEffect, useState } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { FlaskConical, KeyRound, Loader2 } from 'lucide-react'
import { devSignIn, fetchDevUsers, startSignIn, useMe } from '@/api/session'
import { Button, Field, Input } from '@/components/ui/primitives'
import { AuthLayout } from './AuthLayout'

// Sign-in (D-27, ADR-0022): the work e-mail first; the BFF sends the person to their organization's identity provider
// (home-realm discovery) or to Keycloak's page, which asks for the password and, when the tenant requires it, a second
// factor. The session comes back as a cookie. In development and test only, dev-auth lists the seeded users.
export function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const me = useMe()
  const search = useSearch({ strict: false }) as { redirect?: string; error?: string }
  const returnTo = safePath(search.redirect)
  const [pending, setPending] = useState<string | null>(null)
  const [email, setEmail] = useState('')
  const validEmail = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email.trim())
  const devUsers = useQuery({ queryKey: ['dev-users'], queryFn: fetchDevUsers })

  useEffect(() => {
    if (me) void navigate({ href: returnTo })
  }, [me, navigate, returnTo])

  const messages: Record<string, string> = {
    no_platform_access: t('auth.errors.noPlatformAccess'),
    sso_required: t('auth.ssoEnforced'),
    mfa_required: t('auth.errors.mfaRequired'),
  }
  const error = search.error ? (messages[search.error] ?? t('auth.errors.signInFailed')) : null

  return (
    <AuthLayout title={t('auth.signInTitle')} subtitle={t('auth.signInSubtitle')}>
      <div className="space-y-4">
        {error && (
          <p
            role="alert"
            className="rounded-md border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical"
          >
            {error}
          </p>
        )}
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (!validEmail) return
            setPending('keycloak')
            startSignIn(returnTo, email)
          }}
        >
          <Field label={t('auth.workEmail')} hint={t('auth.realmHint')}>
            <Input
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@company.com"
            />
          </Field>
          <Button
            type="submit"
            variant="primary"
            className="w-full justify-center"
            disabled={pending !== null || !validEmail}
          >
            {pending === 'keycloak' ? <Loader2 className="animate-spin" size={16} /> : <KeyRound size={16} />}
            {t('common.continue')}
          </Button>
        </form>

        {devUsers.data && devUsers.data.length > 0 && (
          <section className="rounded-lg border border-dashed border-warning/60 p-3" aria-labelledby="dev-auth-title">
            <h2 id="dev-auth-title" className="flex items-center gap-2 text-sm font-semibold text-warning-ink">
              <FlaskConical size={16} /> {t('auth.devAuthTitle')}
            </h2>
            <p className="mt-1 text-xs text-muted">{t('auth.devAuthHint')}</p>
            <ul className="mt-2 space-y-1">
              {devUsers.data.map((u) => (
                <li key={u.id}>
                  <button
                    className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm hover:bg-surface-2 disabled:opacity-60"
                    disabled={pending !== null}
                    onClick={async () => {
                      setPending(u.id)
                      try {
                        await devSignIn(client, u.id)
                        await navigate({ href: returnTo })
                      } finally {
                        setPending(null)
                      }
                    }}
                  >
                    <span>
                      <span className="font-medium text-text">{u.displayName}</span>{' '}
                      <span className="text-muted">{u.email}</span>
                    </span>
                    {pending === u.id && <Loader2 className="animate-spin" size={14} />}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </AuthLayout>
  )
}

// Only same-origin paths (the BFF checks it too).
function safePath(value: string | undefined): string {
  if (!value) return '/'
  try {
    const url = new URL(value, window.location.origin)
    return url.origin === window.location.origin ? url.pathname + url.search : '/'
  } catch {
    return '/'
  }
}
