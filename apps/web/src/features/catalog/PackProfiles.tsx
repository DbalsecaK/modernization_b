import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'
import { ApiError } from '@/api/client'
import type { Catalog } from '@/api/projects'
import { useCreatePackProfile, useDeletePackProfile, usePackProfiles } from '@/api/packProfiles'
import { Button, Card, CardBody, CardHeader, Field, Input, Select, Table, Td, Th } from '@/components/ui/primitives'
import { Drawer, Textarea, toast } from '@/components/ui/overlay'
import { Notice } from '@/features/projects/NewProjectWizard'

// Pack profiles (ADR-0040): how the tenant wants the generated code shaped, as data the agents are told and the
// design must respect; the pack, its image and its certification stay the platform's.
function message(error: unknown): string {
  return error instanceof ApiError ? error.message : String(error)
}

export function PackProfiles({ catalog }: { catalog: Catalog }) {
  const { t } = useTranslation()
  const profiles = usePackProfiles()
  const remove = useDeletePackProfile()
  const [open, setOpen] = useState(false)
  const [opened, setOpened] = useState(0)
  const backends = catalog.targets.filter((o) => o.axis === 'backend')
  return (
    <Card>
      <CardHeader
        title={t('catalog.packProfiles.title')}
        subtitle={t('catalog.packProfiles.hint')}
        action={
          <Button
            size="sm"
            variant="primary"
            onClick={() => {
              setOpened((n) => n + 1)
              setOpen(true)
            }}
          >
            {t('catalog.packProfiles.create')}
          </Button>
        }
      />
      <ProfileDrawer key={opened} open={open} onClose={() => setOpen(false)} backends={backends} />
      {(profiles.data ?? []).length === 0 ? (
        <CardBody>
          <p className="text-sm text-muted">{t('catalog.packProfiles.empty')}</p>
        </CardBody>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>{t('catalog.packProfiles.name')}</Th>
              <Th>{t('catalog.packProfiles.backend')}</Th>
              <Th>{t('catalog.packProfiles.packageRoot')}</Th>
              <Th className="text-right" />
            </tr>
          </thead>
          <tbody>
            {(profiles.data ?? []).map((p) => (
              <tr key={p.id}>
                <Td className="text-text">
                  {p.name}
                  <div className="font-mono text-xs text-muted">{p.key}</div>
                </Td>
                <Td>{backends.find((b) => b.key === p.backend)?.name ?? t('catalog.packProfiles.anyBackend')}</Td>
                <Td className="font-mono text-xs">{p.packageRoot ?? '—'}</Td>
                <Td className="text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`${t('catalog.packProfiles.delete')} ${p.name}`}
                    disabled={remove.isPending}
                    onClick={() => {
                      if (window.confirm(t('catalog.packProfiles.confirmDelete', { name: p.name })))
                        remove.mutate(p.id, { onError: (e) => toast(message(e)) })
                    }}
                  >
                    <Trash2 size={14} />
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function ProfileDrawer({
  open,
  onClose,
  backends,
}: {
  open: boolean
  onClose: () => void
  backends: Catalog['targets']
}) {
  const { t } = useTranslation()
  const create = useCreatePackProfile()
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [backend, setBackend] = useState('')
  const [packageRoot, setPackageRoot] = useState('')
  const [conventions, setConventions] = useState('')
  const valid = name.trim().length > 0 && /^[a-z][a-z0-9-]{1,40}$/.test(key)
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={t('catalog.packProfiles.create')}
      description={t('catalog.packProfiles.drawerHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="primary"
            disabled={!valid || create.isPending}
            onClick={async () => {
              try {
                await create.mutateAsync({
                  key,
                  name: name.trim(),
                  backend: backend || null,
                  packageRoot: packageRoot.trim() || null,
                  conventions,
                })
                toast(t('catalog.packProfiles.saved', { name: name.trim() }))
                onClose()
              } catch (e) {
                toast(message(e))
              }
            }}
          >
            {t('common.save')}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('catalog.packProfiles.name')}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Bank standard" />
        </Field>
        <Field label={t('catalog.packProfiles.key')} hint={t('catalog.packProfiles.keyHint')}>
          <Input value={key} onChange={(e) => setKey(e.target.value)} placeholder="bank-standard" />
        </Field>
        <Field label={t('catalog.packProfiles.backend')}>
          <Select value={backend} onChange={(e) => setBackend(e.target.value)}>
            <option value="">{t('catalog.packProfiles.anyBackend')}</option>
            {backends.map((b) => (
              <option key={b.key} value={b.key}>
                {b.name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('catalog.packProfiles.packageRoot')} hint={t('catalog.packProfiles.packageRootHint')}>
          <Input value={packageRoot} onChange={(e) => setPackageRoot(e.target.value)} placeholder="com.andesbank" />
        </Field>
      </div>
      <Field label={t('catalog.packProfiles.conventions')} hint={t('catalog.packProfiles.conventionsHint')}>
        <Textarea value={conventions} onChange={(e) => setConventions(e.target.value)} rows={6} />
      </Field>
      <Notice tone="info">{t('catalog.packProfiles.notice')}</Notice>
    </Drawer>
  )
}
