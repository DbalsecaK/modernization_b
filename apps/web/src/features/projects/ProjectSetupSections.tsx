import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileText, Image, Link2, Plus, Upload, X } from 'lucide-react'
import { Button, Field, Input, Select, Toggle } from '@/components/ui/primitives'
import { Notice } from './NewProjectWizard'

// Sections of the "Source" step of the new-project wizard: documents, UI references (screenshots, Figma and
// prototype links) and the work-tracking project. The files are uploaded right after the project is created and go
// through the server's validation (type, size, zip safety, malware, secrets); everything can be extended later from
// the project's Inputs tab.

export interface UiReferences {
  screens: { file: File; url: string }[]
  figma: string[]
  prototypes: string[]
}

export const EMPTY_UI_REFERENCES: UiReferences = { screens: [], figma: [], prototypes: [] }

// A first check in the browser; the server validates again and decides (figma.com/file|design|proto, https).
export const FIGMA_LINK = /^https:\/\/(www\.)?figma\.com\/(file|design|proto)\/[A-Za-z0-9]{10,}/
const HTTPS_LINK = /^https:\/\/[^\s/@]+\.[^\s/@]+(\/\S*)?$/

function FileChips({ files, onRemove }: { files: File[]; onRemove: (f: File) => void }) {
  const { t } = useTranslation()
  if (files.length === 0) return null
  return (
    <ul className="mt-2 flex flex-wrap gap-2">
      {files.map((f) => (
        <li
          key={`${f.name}-${f.size}-${f.lastModified}`}
          className="flex items-center gap-1 rounded bg-surface-2 px-2 py-1 font-mono text-xs text-text"
        >
          {f.name}
          <button
            type="button"
            onClick={() => onRemove(f)}
            aria-label={t('setup.removeFile', { name: f.name })}
            className="text-muted hover:text-critical"
          >
            <X size={12} />
          </button>
        </li>
      ))}
    </ul>
  )
}

export function DocumentsSection({ value, onChange }: { value: File[]; onChange: (v: File[]) => void }) {
  const { t } = useTranslation()
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-text">{t('setup.documents')}</div>
      <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border px-6 py-6 text-center hover:bg-surface-2">
        <FileText size={20} className="text-muted" />
        <span className="text-sm text-text">{t('setup.dropDocuments')}</span>
        <span className="text-xs text-muted">{t('inputForms.acceptedDocs')}</span>
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.md,.txt"
          className="sr-only"
          aria-label={t('setup.documents')}
          onChange={(e) => onChange([...value, ...Array.from(e.target.files ?? [])])}
        />
      </label>
      <FileChips files={value} onRemove={(f) => onChange(value.filter((x) => x !== f))} />
    </div>
  )
}

export function ArchiveSection({ value, onChange }: { value: File | null; onChange: (v: File | null) => void }) {
  const { t } = useTranslation()
  return (
    <div>
      <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border px-6 py-6 text-center hover:bg-surface-2">
        <Upload size={20} className="text-muted" />
        <span className="text-sm text-text">{t('setup.dropArchive')}</span>
        <span className="text-xs text-muted">{t('setup.archiveHint')}</span>
        <input
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          aria-label={t('wizard.uploadZip')}
          onChange={(e) => onChange(e.target.files?.[0] ?? null)}
        />
      </label>
      <FileChips files={value ? [value] : []} onRemove={() => onChange(null)} />
    </div>
  )
}

export interface GitInput {
  url: string
  branch: string
  token: string
}

export function GitSection({ value, onChange }: { value: GitInput; onChange: (v: GitInput) => void }) {
  const { t } = useTranslation()
  const invalid = value.url.trim() !== '' && !HTTPS_LINK.test(value.url.trim())
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <Field label={t('setup.gitUrl')} hint={invalid ? t('setup.gitUrlInvalid') : t('setup.gitUrlHint')}>
          <Input
            value={value.url}
            onChange={(e) => onChange({ ...value, url: e.target.value })}
            placeholder="https://git.bank.example/cards/card-system.git"
          />
        </Field>
      </div>
      <Field label={t('setup.gitBranch')}>
        <Input value={value.branch} onChange={(e) => onChange({ ...value, branch: e.target.value })} />
      </Field>
      <Field label={t('setup.gitToken')} hint={t('setup.gitTokenHint')}>
        <Input
          type="password"
          autoComplete="off"
          value={value.token}
          onChange={(e) => onChange({ ...value, token: e.target.value })}
        />
      </Field>
    </div>
  )
}

export function UiReferencesSection({ value, onChange }: { value: UiReferences; onChange: (v: UiReferences) => void }) {
  const { t } = useTranslation()
  const [figma, setFigma] = useState('')
  const [proto, setProto] = useState('')
  const figmaValid = FIGMA_LINK.test(figma.trim())
  const protoValid = HTTPS_LINK.test(proto.trim())

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
            accept="image/png,image/jpeg,image/webp"
            multiple
            className="sr-only"
            aria-label={t('setup.screens')}
            onChange={(e) =>
              onChange({
                ...value,
                screens: [
                  ...value.screens,
                  ...Array.from(e.target.files ?? []).map((file) => ({ file, url: URL.createObjectURL(file) })),
                ],
              })
            }
          />
        </label>
        {value.screens.length > 0 && (
          <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-5">
            {value.screens.map((s) => (
              <figure key={s.url} className="relative overflow-hidden rounded-md border border-border">
                <img src={s.url} alt={s.file.name} className="aspect-video w-full object-cover" />
                <figcaption className="truncate px-1.5 py-1 text-[10px] text-muted">{s.file.name}</figcaption>
                <button
                  type="button"
                  onClick={() => onChange({ ...value, screens: value.screens.filter((x) => x.url !== s.url) })}
                  className="absolute top-1 right-1 rounded-full bg-surface/90 p-0.5 text-muted hover:text-critical"
                  aria-label={t('setup.removeFile', { name: s.file.name })}
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
        placeholder="https://www.figma.com/design/AbC123DeF4/Onboarding"
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
        placeholder="https://prototype.example.com/app"
        hint={t('inputForms.prototypeHint')}
        input={proto}
        setInput={setProto}
        valid={protoValid}
        items={value.prototypes}
        onAdd={() => (onChange({ ...value, prototypes: [...value.prototypes, proto.trim()] }), setProto(''))}
        onRemove={(l) => onChange({ ...value, prototypes: value.prototypes.filter((x) => x !== l) })}
      />
      {value.screens.length === 0 && value.figma.length === 0 && value.prototypes.length === 0 && (
        <Notice tone="info">{t('setup.noUiRefs')}</Notice>
      )}
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
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          onKeyDown={(e) => e.key === 'Enter' && valid && (e.preventDefault(), onAdd())}
        />
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
              <button
                type="button"
                onClick={() => onRemove(l)}
                aria-label={t('common.remove')}
                className="text-muted hover:text-critical"
              >
                <X size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </Field>
  )
}

/** Linking Jira or Azure DevOps arrives with M7b; the section stays visible so the flow is complete. */
export function WorkTrackingSection() {
  const { t } = useTranslation()
  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div>
        <div className="text-sm font-semibold text-text">{t('setup.trackingTitle')}</div>
        <p className="mt-0.5 text-xs text-muted">{t('setup.trackingHint')}</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('setup.integration')}>
          <Select value="none" disabled>
            <option value="none">{t('setup.noIntegration')}</option>
          </Select>
        </Field>
      </div>
      <Toggle checked={false} disabled onChange={() => undefined} label={t('setup.autoCreate')} />
      <Notice tone="info">{t('setup.trackingLater')}</Notice>
    </div>
  )
}
