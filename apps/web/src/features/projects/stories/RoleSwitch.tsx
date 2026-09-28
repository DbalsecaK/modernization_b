import { useTranslation } from 'react-i18next'
import { Select } from '@/components/ui/primitives'
import { setRole, useStories, type StoryRole } from './store'

// Prototype only: switches the acting role to show the permissions. In the platform the role comes from the
// session and OpenFGA decides (product owner edits stories, tech lead edits the plan, executive only reads).
export function RoleSwitch() {
  const { t } = useTranslation()
  const { role } = useStories()
  return (
    <div className="w-60">
      <Select className="h-8" value={role} onChange={(e) => setRole(e.target.value as StoryRole)} aria-label={t('stories.actingAs')}>
        {(['productOwner', 'techLead', 'executive'] as const).map((r) => (
          <option key={r} value={r}>
            {t('stories.actingAs')}: {t(`stories.roles.${r}`)}
          </option>
        ))}
      </Select>
    </div>
  )
}
