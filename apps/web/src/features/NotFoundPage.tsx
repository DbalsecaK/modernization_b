import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { EmptyState } from '@/components/ui/primitives'

export function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <div className="p-10">
      <EmptyState
        title={t('notFound.title')}
        description={t('notFound.body')}
        action={
          <Link to="/" className="text-sm font-medium text-info hover:underline">
            {t('notFound.home')}
          </Link>
        }
      />
    </div>
  )
}
