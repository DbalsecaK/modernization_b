// Design of the M0b Keycloak theme (Keycloakify, D-27): not routed in M0, where Keycloak shows its own pages.
import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { MailCheck } from 'lucide-react'
import { Button, Field, Input } from '@/components/ui/primitives'
import { AuthLayout } from './AuthLayout'

export function ForgotPasswordPage() {
  const { t } = useTranslation()
  const [sent, setSent] = useState(false)
  return (
    <AuthLayout title={t('auth.forgot.title')} subtitle={t('auth.forgot.subtitle')}>
      {sent ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-md bg-surface-2 p-4 text-sm text-text-2">
            <MailCheck size={18} className="mt-0.5 shrink-0 text-good" />
            {/* Same message whether or not the account exists, to avoid account enumeration. */}
            {t('auth.forgot.sent')}
          </div>
          <Link to="/login" className="text-sm font-medium text-info hover:underline">
            {t('auth.backToSignIn')}
          </Link>
        </div>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            setSent(true)
          }}
        >
          <Field label={t('auth.workEmail')} hint={t('auth.forgot.ssoHint')}>
            <Input type="email" autoComplete="username" required autoFocus />
          </Field>
          <Button type="submit" variant="primary" className="w-full">
            {t('auth.forgot.send')}
          </Button>
          <Link to="/login" className="block text-center text-sm font-medium text-info hover:underline">
            {t('auth.backToSignIn')}
          </Link>
        </form>
      )}
    </AuthLayout>
  )
}
