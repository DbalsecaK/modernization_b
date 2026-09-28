import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/cn'
import { setLanguage } from '@/i18n'
import { Logo } from '@/components/layout/AppShell'

export function AuthLayout({ title, subtitle, children }: { title: ReactNode; subtitle?: ReactNode; children: ReactNode }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="flex min-h-full">
      <section className="relative hidden w-[44%] flex-col justify-between overflow-hidden bg-[#052158] p-10 text-white lg:flex">
        <Logo className="text-3xl text-white" />
        <div>
          <h2 className="max-w-md text-3xl leading-tight font-semibold">{t('auth.heroTitle')}</h2>
          <p className="mt-4 max-w-md text-[#c9d3ea]">{t('auth.heroBody')}</p>
          <ul className="mt-8 space-y-3 text-sm text-[#c9d3ea]">
            {(['heroPoint1', 'heroPoint2', 'heroPoint3'] as const).map((key) => (
              <li key={key} className="flex items-start gap-2">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#05e194]" />
                {t(`auth.${key}`)}
              </li>
            ))}
          </ul>
        </div>
        <p className="flex items-center gap-2 text-xs text-[#c9d3ea]">
          <ShieldCheck size={14} /> {t('auth.securityNote')}
        </p>
        <div className="pointer-events-none absolute -right-24 -bottom-24 h-80 w-80 rounded-full border-[40px] border-[#05e194]/10" />
      </section>
      <section className="flex flex-1 flex-col bg-surface">
        <div className="flex justify-end gap-1 p-4 text-xs">
          {(['en', 'es'] as const).map((lng) => (
            <button
              key={lng}
              onClick={() => setLanguage(lng)}
              aria-pressed={i18n.language === lng}
              className={cn('rounded px-2 py-1 font-medium uppercase', i18n.language === lng ? 'bg-brand text-brand-contrast' : 'text-muted hover:text-text')}
            >
              {lng}
            </button>
          ))}
        </div>
        <div className="flex flex-1 items-center justify-center px-6 pb-12">
          <div className="w-full max-w-sm">
            <Logo className="mb-8 text-2xl text-brand lg:hidden dark:text-white" />
            <h1 className="text-2xl font-semibold text-text">{title}</h1>
            {subtitle && <p className="mt-1 text-sm text-text-2">{subtitle}</p>}
            <div className="mt-8">{children}</div>
          </div>
        </div>
      </section>
    </div>
  )
}
