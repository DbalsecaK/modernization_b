import { useTranslation } from 'react-i18next'
import { useMissingInputs } from '@/api/graph'
import { Notice } from '../NewProjectWizard'

/**
 * What the code includes and the project's inputs do not carry (a COPY with no copybook), above every tab: the person
 * sees what to ask the customer for before a run stops on it (2026-10-19: a CICS project lacked seven copybooks and
 * nothing on screen said so).
 */
export function MissingInputsBanner({ projectId, onOpenInputs }: { projectId: string; onOpenInputs: () => void }) {
  const { t } = useTranslation()
  const { data } = useMissingInputs(projectId)
  if (!data || data.length === 0) return null
  return (
    <div className="mb-4">
      <Notice tone="warning">
        <p className="font-semibold">{t('project.missingInputs.title', { count: data.length })}</p>
        <p className="mt-1">{t('project.missingInputs.why')}</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {data.map((item) => (
            <li key={item.name}>
              <span className="font-mono font-semibold">{item.name}</span>{' '}
              {t('project.missingInputs.usedBy', {
                where: item.usedBy
                  .map((use) =>
                    use.line ? `${use.unit} (${t('project.missingInputs.line', { line: use.line })})` : use.unit,
                  )
                  .join(', '),
              })}
            </li>
          ))}
        </ul>
        <button type="button" className="mt-2 font-semibold underline" onClick={onOpenInputs}>
          {t('project.missingInputs.action')}
        </button>
      </Notice>
    </div>
  )
}
