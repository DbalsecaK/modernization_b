import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/cn'
import { screenData, type ScreenField, type ScreenRow } from '@/api/screens'
import { Badge, Card, CardBody, CardHeader, EmptyState, Table, Td, Th } from '@/components/ui/primitives'

/** The fields a person fills or reads; literals are the screen's fixed text. */
const dataFields = (fields: ScreenField[]) => fields.filter((f) => f.kind !== 'literal')

/** The field's type: numeric or secret by its attributes, else text. */
function fieldType(f: ScreenField): 'numeric' | 'secret' | 'text' {
  const attributes = f.attributes ?? []
  if (attributes.includes('NUM')) return 'numeric'
  if (attributes.includes('DRK')) return 'secret'
  return 'text'
}

// The screens of the specification (spec 4.1 "Pantalla", 18.3): the same screen specs the UI design tab draws, read
// as a spec: each data field with its type, length, whether it is required and editable, the actions and where they
// lead. Same look as the prototype's ScreensView.
export function ScreensView({ projectId, screens }: { projectId: string; screens: ScreenRow[] }) {
  const { t } = useTranslation()
  const all = screens.map((row) => ({ row, data: screenData(row) })).sort((a, b) => a.data.id.localeCompare(b.data.id))
  const [selected, setSelected] = useState<string | null>(null)
  const current = all.find((s) => s.data.id === selected) ?? all[0]
  if (!current) {
    return <EmptyState title={t('spec.noScreens')} description={t('spec.noScreensHint')} />
  }
  const { data } = current
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,3fr)]">
      <Card>
        <ul className="divide-y divide-border" aria-label={t('spec.views.screens')}>
          {all.map(({ row, data: s }) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => setSelected(s.id)}
                aria-current={current.data.id === s.id ? 'true' : undefined}
                className={cn(
                  'w-full px-4 py-3 text-left hover:bg-surface-2',
                  current.data.id === s.id && 'bg-surface-2',
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted">{s.id}</span>
                  <Badge className="ml-auto">{row.status}</Badge>
                </div>
                <div className="mt-1 text-sm font-medium text-text">{s.name}</div>
                {s.map && <div className="text-xs text-muted">{[s.mapset, s.map].filter(Boolean).join(' · ')}</div>}
              </button>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHeader
          title={data.name}
          subtitle={
            data.map ? t('spec.screenSource', { source: [data.mapset, data.map].filter(Boolean).join('/') }) : data.id
          }
          action={
            <Link
              to="/projects/$projectId"
              params={{ projectId }}
              search={{ tab: 'uiDesign' }}
              className="text-sm text-brand underline-offset-2 hover:underline"
            >
              {t('spec.openInUiDesign')}
            </Link>
          }
        />
        <Table>
          <thead>
            <tr>
              <Th>{t('spec.field')}</Th>
              <Th>{t('spec.type')}</Th>
              <Th>{t('spec.length')}</Th>
              <Th>{t('spec.required')}</Th>
              <Th>{t('spec.editable')}</Th>
            </tr>
          </thead>
          <tbody>
            {dataFields(data.fields).map((f) => (
              <tr key={f.name}>
                <Td>
                  <div className="text-text">{f.label ?? f.name}</div>
                  <div className="font-mono text-xs text-muted">{f.name}</div>
                </Td>
                <Td className="text-xs">
                  {t(`spec.fieldTypes.${fieldType(f)}`)}
                  {f.format && <span className="ml-1 font-mono text-muted">{f.format}</span>}
                </Td>
                <Td className="tabular">{f.length}</Td>
                <Td>{f.required ? t('common.yes') : t('common.no')}</Td>
                <Td>{f.kind === 'input' ? t('spec.editableYes') : t('spec.readOnly')}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <div>
            <div className="text-xs font-medium text-muted uppercase">{t('spec.actions')}</div>
            <ul className="mt-1 space-y-1 text-sm text-text-2">
              {(data.actions ?? []).map((a) => (
                <li key={a.key}>
                  <span className="font-mono text-xs">{a.key}</span> {a.label}
                  {a.target && <span className="text-xs text-muted"> → {a.target}</span>}
                </li>
              ))}
              {(data.actions ?? []).length === 0 && <li className="text-muted">—</li>}
            </ul>
          </div>
          <div>
            <div className="text-xs font-medium text-muted uppercase">{t('spec.navigation')}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {(data.navigation_out ?? []).map((n) => (
                <Badge key={n}>{n}</Badge>
              ))}
              {(data.navigation_out ?? []).length === 0 && <span className="text-sm text-muted">—</span>}
            </div>
          </div>
        </CardBody>
      </Card>
    </div>
  )
}
