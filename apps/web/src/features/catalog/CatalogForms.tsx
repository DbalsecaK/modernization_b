import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload } from 'lucide-react'
import { agents as allAgents, profiles, skills as allSkills } from '@/mocks/data'
import type { AgentDefinition, AgentGroup, SkillDefinition, SkillType } from '@/mocks/types'
import { Button, Field, Input, Select } from '@/components/ui/primitives'
import { CheckboxGroup, Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'
import { agentName } from './AgentCard'

const PHASES = [
  'inventory',
  'domains',
  'classification',
  'ruleExtraction',
  'ui',
  'design',
  'characterization',
  'generation',
  'verification',
  'hardening',
  'delivery',
  'ingestion',
  'normalization',
  'consolidation',
  'validation',
] as const
const CAPABILITIES = ['toolCalling', 'vision', 'structuredOutput', 'longContext', 'reasoning'] as const
const TOOLS = ['readGraph', 'readCode', 'readInputs', 'readWorkspace', 'writeWorkspace', 'sandbox'] as const

const slug = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')

export function AgentForm({
  open,
  onClose,
  onSave,
}: {
  open: boolean
  onClose: () => void
  onSave: (a: AgentDefinition) => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [nameEs, setNameEs] = useState('')
  const [group, setGroup] = useState<AgentGroup>('build')
  const [description, setDescription] = useState('')
  const [descriptionEs, setDescriptionEs] = useState('')
  const [phases, setPhases] = useState<string[]>(['generation'])
  const [capabilities, setCapabilities] = useState<string[]>(['toolCalling'])
  const [tools, setTools] = useState<string[]>(['readWorkspace'])
  const [profile, setProfile] = useState(profiles[0].id)
  const [prompt, setPrompt] = useState('')
  const valid = name.trim() && description.trim() && phases.length > 0 && prompt.trim()
  const writes = tools.includes('writeWorkspace') || tools.includes('sandbox')

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('catalogForms.newAgentTitle')}
      description={t('catalogForms.newAgentHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            onClick={() => {
              onSave({
                id: slug(name),
                name,
                nameEs: nameEs || undefined,
                group,
                description,
                descriptionEs: descriptionEs || undefined,
                phases,
                capabilities,
                tools,
                mandatory: false,
                level: 'experimental',
                version: '0.1.0',
                defaultProfile: profile,
                relativeCost: 2,
              })
              toast(t('catalogForms.agentSubmitted', { name }))
              onClose()
            }}
          >
            {t('catalogForms.submitForEvaluation')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('catalogForms.nameEn')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Mainframe batch analyst" />
        </Field>
        <Field label={t('catalogForms.nameEs')} hint={t('catalogForms.optionalTranslation')}>
          <Input value={nameEs} onChange={(e) => setNameEs(e.target.value)} placeholder="Analista de batch mainframe" />
        </Field>
      </div>
      <Field label={t('catalog.group')}>
        <Select value={group} onChange={(e) => setGroup(e.target.value as AgentGroup)}>
          {(['analysis', 'design', 'build', 'quality'] as const).map((g) => (
            <option key={g} value={g}>
              {t(`agentGroups.${g}`)}
            </option>
          ))}
        </Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('catalogForms.descriptionEn')} hint={t('catalogForms.descriptionHint')}>
          <Textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} />
        </Field>
        <Field label={t('catalogForms.descriptionEs')} hint={t('catalogForms.optionalTranslation')}>
          <Textarea value={descriptionEs} onChange={(e) => setDescriptionEs(e.target.value)} maxLength={200} />
        </Field>
      </div>
      <Field label={t('catalogForms.phases')}>
        <CheckboxGroup
          columns={3}
          options={PHASES.map((p) => ({ id: p, label: t(`phases.${p}`) }))}
          value={phases}
          onChange={setPhases}
        />
      </Field>
      <Field label={t('catalogForms.capabilities')} hint={t('catalogForms.capabilitiesHint')}>
        <CheckboxGroup
          columns={3}
          options={CAPABILITIES.map((c) => ({ id: c, label: t(`capabilities.${c}`) }))}
          value={capabilities}
          onChange={setCapabilities}
        />
      </Field>
      <Field label={t('catalogForms.tools')} hint={t('catalogForms.toolsHint')}>
        <CheckboxGroup
          columns={3}
          options={TOOLS.map((x) => ({ id: x, label: t(`tools.${x}`) }))}
          value={tools}
          onChange={setTools}
        />
      </Field>
      {writes && <Notice tone="warning">{t('catalogForms.writeWarning')}</Notice>}
      <Field label={t('catalogForms.defaultProfile')}>
        <Select value={profile} onChange={(e) => setProfile(e.target.value)}>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} — {p.providerParameter}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t('catalogForms.systemPrompt')} hint={t('catalogForms.systemPromptHint')}>
        <Textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="min-h-40 font-mono text-xs"
          placeholder="You are a mainframe batch analyst. Read JCL and COBOL…"
        />
      </Field>
      <Notice tone="info">{t('catalogForms.evaluationNotice')}</Notice>
    </Drawer>
  )
}

export function SkillForm({
  open,
  onClose,
  onSave,
}: {
  open: boolean
  onClose: () => void
  onSave: (s: SkillDefinition) => void
}) {
  const { t, i18n } = useTranslation()
  const [name, setName] = useState('')
  const [type, setType] = useState<SkillType>('customer')
  const [description, setDescription] = useState('')
  const [appliesTo, setAppliesTo] = useState<string[]>([])
  const [tags, setTags] = useState('*')
  const [conflicts, setConflicts] = useState<string[]>([])
  const [file, setFile] = useState<string | null>(null)
  const [scope, setScope] = useState<'tenant' | 'global'>('tenant')
  const valid = name.trim() && description.trim() && appliesTo.length > 0 && file

  return (
    <Drawer
      open={open}
      onClose={onClose}
      wide
      title={t('catalogForms.newSkillTitle')}
      description={t('catalogForms.newSkillHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!valid}
            onClick={() => {
              onSave({
                id: slug(name),
                name,
                type,
                description,
                appliesTo,
                tags: tags
                  .split(',')
                  .map((x) => x.trim())
                  .filter(Boolean),
                conflictsWith: conflicts,
                version: '0.1.0',
                evalScore: null,
                status: 'evaluating',
              })
              toast(t('catalogForms.skillSubmitted', { name }))
              onClose()
            }}
          >
            {t('catalogForms.submitForEvaluation')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('catalogForms.skillName')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Andes Bank error codes" />
        </Field>
        <Field label={t('catalog.type')}>
          <Select value={type} onChange={(e) => setType(e.target.value as SkillType)}>
            {(['source', 'target', 'conversion', 'crossCutting', 'customer'] as const).map((s) => (
              <option key={s} value={s}>
                {t(`skillTypes.${s}`)}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label={t('catalogForms.descriptionEn')} hint={t('catalogForms.skillDescriptionHint')}>
        <Textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} />
      </Field>
      <Field label={t('catalog.appliesTo')}>
        <CheckboxGroup
          columns={3}
          options={allAgents.map((a) => ({ id: a.id, label: agentName(a, i18n.language) }))}
          value={appliesTo}
          onChange={setAppliesTo}
        />
      </Field>
      <Field label={t('catalogForms.tags')} hint={t('catalogForms.tagsHint')}>
        <Input value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
      <Field label={t('catalogForms.conflicts')}>
        <Select
          value=""
          onChange={(e) =>
            e.target.value && !conflicts.includes(e.target.value) && setConflicts([...conflicts, e.target.value])
          }
        >
          <option value="">{t('catalogForms.addConflict')}</option>
          {allSkills.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </Select>
        {conflicts.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {conflicts.map((c) => (
              <button
                key={c}
                onClick={() => setConflicts(conflicts.filter((x) => x !== c))}
                className="rounded-full bg-critical/10 px-2 py-0.5 text-xs text-critical-ink"
              >
                {allSkills.find((s) => s.id === c)?.name} ×
              </button>
            ))}
          </div>
        )}
      </Field>
      <Field label={t('catalogForms.package')} hint={t('catalogForms.packageHint')}>
        <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-border px-4 py-6 text-sm text-text-2 hover:bg-surface-2">
          <Upload size={16} />
          {file ?? t('catalogForms.choosePackage')}
          <input
            type="file"
            accept=".md,.zip"
            className="sr-only"
            onChange={(e) => setFile(e.target.files?.[0]?.name ?? null)}
          />
        </label>
      </Field>
      <Field label={t('catalogForms.scope')}>
        <Select value={scope} onChange={(e) => setScope(e.target.value as 'tenant' | 'global')}>
          <option value="tenant">{t('catalogForms.scopeTenant')}</option>
          <option value="global">{t('catalogForms.scopeGlobal')}</option>
        </Select>
      </Field>
      <Notice tone="info">{t('catalogForms.evaluationNotice')}</Notice>
    </Drawer>
  )
}
