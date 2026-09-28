import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, Image, Link2, Plus, Upload, X } from 'lucide-react'
import { Button, Field, Input, Select, Toggle } from '@/components/ui/primitives'
import { Notice } from './NewProjectWizard'

// Sections of the "Source" step of the new-project wizard: documents, UI references (screenshots, Figma and
// prototype links) and the work-tracking project (Jira or Azure DevOps). Everything can be extended later from
// the project's Inputs, UI design and Backlog tabs.

export interface UiReferences {
  documents: string[]
  screens: { name: string; url: string }[]
  figma: string[]
  prototypes: string[]
}

export interface WorkTracking {
  integration: 'none' | 'jira' | 'azureDevOps'
  project: string
  autoCreate: boolean
}

export function DocumentsSection({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { t } = useTranslation()
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-text">{t('setup.documents')}</div>
      <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border px-6 py-6 text-center hover:bg-surface-2">
        <FileText size={20} className="text-muted" />
        <span className="text-sm text-text">{t('wizard.dropInputs')}</span>
        <span className="text-xs text-muted">{t('inputForms.acceptedDocs')}</span>
        <input type="file" multiple className="sr-only" onChange={(e) => onChange([...value, ...Array.from(e.target.files ?? []).map((f) => f.name)])} />
      </label>
      {value.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {value.map((d) => (
            <li key={d} className="flex items-center gap-1 rounded bg-surface-2 px-2 py-1 font-mono text-xs text-text">
              {d}
              <button onClick={() => onChange(value.filter((x) => x !== d))} aria-label={t('common.remove')} className="text-muted hover:text-critical">
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function UiReferencesSection({ value, onChange }: { value: UiReferences; onChange: (v: UiReferences) => void }) {
  const { t } = useTranslation()
  const [figma, setFigma] = useState('')
  const [proto, setProto] = useState('')
  const figmaValid = /^https:\/\/(www\.)?figma\.com\/(file|design|proto)\//.test(figma.trim())
  const protoValid = /^https:\/\/\S+/.test(proto.trim())

  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div>
        <div className="text-sm font-semibold text-text">{t('setup.uiTitle')}</div>
        <p className="mt-0.5 text-xs text-muted">{t('setup.uiHint')}</p>
      </div>

      <div>
        <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-text">
          <Image size={14} /> {t('setup.screens')}
        </div>
        <label className="flex cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed border-border px-4 py-4 text-sm text-text-2 hover:bg-surface-2">
          <Upload size={16} /> {t('inputForms.dropScreens')}
          <input
            type="file"
            accept="image/*"
            multiple
            className="sr-only"
            onChange={(e) => onChange({ ...value, screens: [...value.screens, ...Array.from(e.target.files ?? []).map((f) => ({ name: f.name, url: URL.createObjectURL(f) }))] })}
          />
        </label>
        {value.screens.length > 0 && (
          <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
            {value.screens.map((s) => (
              <figure key={s.url} className="relative overflow-hidden rounded-md border border-border">
                <img src={s.url} alt={s.name} className="aspect-video w-full object-cover" />
                <figcaption className="truncate px-1.5 py-1 text-[10px] text-muted">{s.name}</figcaption>
                <button
                  onClick={() => onChange({ ...value, screens: value.screens.filter((x) => x.url !== s.url) })}
                  className="absolute top-1 right-1 rounded-full bg-surface/90 p-0.5 text-muted hover:text-critical"
                  aria-label={t('common.remove')}
                >
                  <X size={12} />
                </button>
              </figure>
            ))}
          </div>
        )}
      </div>

      <LinkList
        label={t('setup.figmaLinks')}
        placeholder="https://www.figma.com/design/AbC123/Onboarding"
        hint={t('inputForms.figmaHint')}
        input={figma}
        setInput={setFigma}
        valid={figmaValid}
        items={value.figma}
        onAdd={() => (onChange({ ...value, figma: [...value.figma, figma.trim()] }), setFigma(''))}
        onRemove={(l) => onChange({ ...value, figma: value.figma.filter((x) => x !== l) })}
      />
      <LinkList
        label={t('setup.prototypeLinks')}
        placeholder="https://www.figma.com/proto/… · https://prototype.example.com"
        hint={t('inputForms.prototypeHint')}
        input={proto}
        setInput={setProto}
        valid={protoValid}
        items={value.prototypes}
        onAdd={() => (onChange({ ...value, prototypes: [...value.prototypes, proto.trim()] }), setProto(''))}
        onRemove={(l) => onChange({ ...value, prototypes: value.prototypes.filter((x) => x !== l) })}
      />
      {value.screens.length === 0 && value.figma.length === 0 && value.prototypes.length === 0 && <Notice tone="info">{t('setup.noUiRefs')}</Notice>}
    </div>
  )
}

function LinkList({
  label,
  placeholder,
  hint,
  input,
  setInput,
  valid,
  items,
  onAdd,
  onRemove,
}: {
  label: string
  placeholder: string
  hint: string
  input: string
  setInput: (v: string) => void
  valid: boolean
  items: string[]
  onAdd: () => void
  onRemove: (l: string) => void
}) {
  const { t } = useTranslation()
  return (
    <Field label={label} hint={input && !valid ? t('setup.invalidLink') : hint}>
      <div className="flex gap-2">
        <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder={placeholder} onKeyDown={(e) => e.key === 'Enter' && valid && (e.preventDefault(), onAdd())} />
        <Button type="button" onClick={onAdd} disabled={!valid}>
          <Plus size={14} /> {t('setup.add')}
        </Button>
      </div>
      {items.length > 0 && (
        <ul className="mt-2 space-y-1">
          {items.map((l) => (
            <li key={l} className="flex items-center gap-2 rounded bg-surface-2 px-2 py-1 text-xs">
              <Link2 size={12} className="text-muted" />
              <span className="flex-1 truncate font-mono text-text">{l}</span>
              <button type="button" onClick={() => onRemove(l)} aria-label={t('common.remove')} className="text-muted hover:text-critical">
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Field>
  )
}

export function WorkTrackingSection({ value, onChange }: { value: WorkTracking; onChange: (v: WorkTracking) => void }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div>
        <div className="text-sm font-semibold text-text">{t('setup.trackingTitle')}</div>
        <p className="mt-0.5 text-xs text-muted">{t('setup.trackingHint')}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('setup.integration')} hint={t('setup.integrationHint')}>
          <Select value={value.integration} onChange={(e) => onChange({ ...value, integration: e.target.value as WorkTracking['integration'] })}>
            <option value="none">{t('setup.noIntegration')}</option>
            <option value="jira">Jira — andesbank.atlassian.net</option>
            <option value="azureDevOps">Azure DevOps — dev.azure.com/andesbank</option>
          </Select>
        </Field>
        <Field label={value.integration === 'azureDevOps' ? t('setup.adoProject') : t('setup.jiraProject')}>
          <Input
            value={value.project}
            onChange={(e) => onChange({ ...value, project: e.target.value })}
            placeholder={value.integration === 'azureDevOps' ? 'Card Management' : 'CARDS'}
            disabled={value.integration === 'none'}
          />
        </Field>
      </div>
      <Toggle
        checked={value.autoCreate}
        disabled={value.integration === 'none'}
        onChange={(v) => onChange({ ...value, autoCreate: v })}
        label={t('setup.autoCreate')}
      />
    </div>
  )
}
