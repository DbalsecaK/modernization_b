import { useMemo, useState } from 'react'
import { Link, useSearch } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { Download, FileCode2, Folder, GitPullRequest, Loader2, Lock } from 'lucide-react'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import { ApiError } from '@/api/client'
import { CODE_DOWNLOAD, codeDownloadUrl, useCodeFile, useCodeTree } from '@/api/code'
import { CODE_PUSH, usePushCode } from '@/api/delivery'
import type { ProjectDetail } from '@/api/projects'
import { CODE_VIEW } from '@/api/validation'
import { Badge, Button, Card, CardHeader, EmptyState } from '@/components/ui/primitives'
import { toast } from '@/components/ui/overlay'
import { ReleasesCard } from './delivery/DeliveryCards'
import { buildTree, formatSize, initialFile } from './code/model'
import { CodeExcerptView } from './validation/CodeExcerptView'

// Code tab (spec 18.3), connected to the API: the file browser of the newest generation, backend and frontend, with
// the rules each file implements, and the zip of the project. Seeing code needs code.view, the zip code.download and
// the push to a new branch of the customer's repository code.push (M9a, ADR-0023); the releases are listed below.
// Same look as the prototype's CodeTab.
export function ProjectCode({ project, onOpenRuns }: { project: ProjectDetail; onOpenRuns: () => void }) {
  const { t } = useTranslation()
  const canViewCode = project.permissions.includes(CODE_VIEW)
  const canDownload = project.permissions.includes(CODE_DOWNLOAD)
  const canPush = project.permissions.includes(CODE_PUSH)
  const push = usePushCode(project.id)
  const search = useSearch({ strict: false }) as { file?: string }
  const tree = useCodeTree(project.id, canViewCode)
  const rows = useMemo(() => buildTree(tree.data?.files ?? []), [tree.data])
  const [picked, setPicked] = useState<string | null>(null)
  const selected = picked ?? initialFile(rows, search.file)
  const file = useCodeFile(project.id, selected)
  const entry = rows.find((r) => r.file?.path === selected)?.file

  if (!canViewCode) {
    return (
      <EmptyState
        title={
          <span className="inline-flex items-center gap-2">
            <Lock size={16} className="text-muted" aria-hidden /> {t('code.noCodeView')}
          </span>
        }
        description={t('code.noCodeViewHint')}
      />
    )
  }
  if (tree.isLoading) {
    return (
      <p className="flex items-center gap-2 py-12 text-sm text-muted" role="status">
        <Loader2 size={16} className="animate-spin" /> {t('code.loading')}
      </p>
    )
  }
  if (tree.isError) {
    return (
      <EmptyState
        title={t('code.loadError')}
        description={tree.error instanceof ApiError ? tree.error.message : undefined}
        action={
          <Button size="sm" onClick={() => void tree.refetch()}>
            {t('spec.retry')}
          </Button>
        }
      />
    )
  }
  if (!tree.data) {
    return (
      <EmptyState
        title={t('project.later.code')}
        description={t('code.emptyHint')}
        action={
          <Button size="sm" variant="primary" onClick={onOpenRuns}>
            {t('spec.goToRuns')}
          </Button>
        }
      />
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={t('code.title')}
          subtitle={t('code.generatedAt', {
            date: formatDateTime(tree.data.generatedAt),
            count: tree.data.files.length,
          })}
          action={
            <div className="flex flex-wrap gap-2">
              {canDownload ? (
                <a
                  href={codeDownloadUrl(project.id)}
                  download
                  className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-sm font-medium text-text hover:bg-surface-2"
                >
                  <Download size={14} aria-hidden /> {t('code.download')}
                </a>
              ) : (
                <span className="self-center text-xs text-muted">{t('code.downloadNeedsPermission')}</span>
              )}
              <Button
                size="sm"
                disabled={!canPush || push.isPending}
                title={canPush ? t('code.pushHint') : t('code.pushNeedsPermission')}
                aria-describedby="code-push-hint"
                onClick={() =>
                  push.mutateAsync().then(
                    (r) => toast(t('code.pushed', { branch: r.branch ?? '' })),
                    (e) => toast(t('code.pushFailed', { message: e instanceof ApiError ? e.message : String(e) })),
                  )
                }
              >
                {push.isPending ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden />
                ) : (
                  <GitPullRequest size={14} aria-hidden />
                )}{' '}
                {t('code.push')}
              </Button>
              <span id="code-push-hint" className="sr-only">
                {canPush ? t('code.pushHint') : t('code.pushNeedsPermission')}
              </span>
            </div>
          }
        />
        <div className="grid md:grid-cols-[280px_1fr]">
          <ul
            className="max-h-[32rem] overflow-auto border-b border-border p-3 text-sm md:border-r md:border-b-0"
            aria-label={t('code.files')}
          >
            {rows.map((n) => (
              <li key={n.key}>
                {n.file ? (
                  <button
                    type="button"
                    onClick={() => setPicked(n.file!.path)}
                    aria-current={selected === n.file.path ? 'true' : undefined}
                    className={cn(
                      'flex w-full items-center gap-1.5 rounded px-2 py-1 text-left hover:bg-surface-2',
                      selected === n.file.path && 'bg-surface-2 font-medium',
                    )}
                    style={{ paddingLeft: 8 + n.depth * 14 }}
                  >
                    <FileCode2 size={14} className="shrink-0 text-muted" aria-hidden />
                    <span className="truncate text-text">{n.label}</span>
                  </button>
                ) : (
                  <span
                    className="flex items-center gap-1.5 px-2 py-1 text-muted"
                    style={{ paddingLeft: 8 + n.depth * 14 }}
                  >
                    <Folder size={14} className="shrink-0" aria-hidden />
                    <span className="truncate">{n.label}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
          <div className="min-w-0 space-y-3 p-4">
            {entry && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                <Badge>{entry.layer}</Badge>
                <span>{formatSize(entry.sizeBytes)}</span>
                {entry.rules.length > 0 && <span>· {t('code.implements')}</span>}
                {entry.rules.map((rule) => (
                  <Link
                    key={rule}
                    to="/projects/$projectId"
                    params={{ projectId: project.id }}
                    search={{ tab: 'traceability', rule }}
                    className="font-mono text-brand underline-offset-2 hover:underline"
                  >
                    {rule}
                  </Link>
                ))}
              </div>
            )}
            {file.isLoading && (
              <p className="flex items-center gap-2 text-sm text-muted" role="status">
                <Loader2 size={16} className="animate-spin" /> {t('code.loadingFile')}
              </p>
            )}
            {file.isError && <p className="text-sm text-critical-ink">{t('code.fileError')}</p>}
            {file.data && (
              <CodeExcerptView
                title={file.data.path}
                excerpt={{
                  path: file.data.path,
                  firstLine: 1,
                  lines: file.data.content.split('\n'),
                  highlighted: [],
                  truncated: file.data.truncated,
                }}
              />
            )}
          </div>
        </div>
      </Card>
      <ReleasesCard projectId={project.id} />
    </div>
  )
}
