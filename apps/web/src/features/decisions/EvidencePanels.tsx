import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronRight, FileCode2, GitCompare, Sparkles, TerminalSquare } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/primitives'
import {
  diffHunks,
  errorLines,
  groupEvidence,
  lineDiff,
  type Analysis,
  type EvidenceItem,
  type FileEvidence,
} from './model'

// The evidence of a decision card (ADR-0045): collapsible panels with the diagnostic, the code of the last attempt
// (the lines the diagnostic names highlighted), what changed against the version before, and the analysis with
// its proposed answers and their confidence. Native <details> keeps it accessible without extra state.
export function EvidencePanels({ evidence }: { evidence: EvidenceItem[] }) {
  const { t } = useTranslation()
  const grouped = useMemo(() => groupEvidence(evidence), [evidence])
  if (!grouped.diagnostic && grouped.files.length === 0 && !grouped.analysis && grouped.other.length === 0) {
    return null
  }
  return (
    <div className="space-y-2">
      {grouped.analysis && <AnalysisPanel analysis={grouped.analysis} />}
      {grouped.diagnostic && (
        <Panel icon={<TerminalSquare size={14} />} title={t('decisions.evidence.diagnostic')} open>
          <pre className="max-h-72 overflow-auto rounded-md bg-surface-2 p-3 font-mono text-xs whitespace-pre-wrap text-text">
            {grouped.diagnostic}
          </pre>
        </Panel>
      )}
      {grouped.files.map((file) => (
        <FilePanels key={file.path} file={file} diagnostic={grouped.diagnostic} />
      ))}
      {grouped.other.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {grouped.other.map((o, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2 py-1 font-mono text-xs text-text-2"
            >
              <FileCode2 size={12} /> {o.reference}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function Panel({
  icon,
  title,
  badge,
  open,
  children,
}: {
  icon: React.ReactNode
  title: string
  badge?: React.ReactNode
  open?: boolean
  children: React.ReactNode
}) {
  return (
    <details className="group rounded-md border border-border" open={open}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium text-text hover:bg-surface-2">
        <ChevronRight size={14} className="transition-transform group-open:rotate-90" />
        {icon}
        <span>{title}</span>
        {badge && <span className="ml-auto">{badge}</span>}
      </summary>
      <div className="border-t border-border p-3">{children}</div>
    </details>
  )
}

function FilePanels({ file, diagnostic }: { file: FileEvidence; diagnostic?: string }) {
  const { t } = useTranslation()
  const marked = useMemo(() => errorLines(diagnostic, file.path), [diagnostic, file.path])
  const hunks = useMemo(
    () => (file.before !== undefined ? diffHunks(lineDiff(file.before, file.after)) : []),
    [file.before, file.after],
  )
  const changed = hunks.reduce((n, h) => n + h.filter((l) => l.kind !== 'same').length, 0)
  const lines = file.after.split('\n')
  const name = file.path.split('/').pop() ?? file.path
  return (
    <>
      <Panel
        icon={<FileCode2 size={14} />}
        title={t('decisions.evidence.code', { file: name, attempt: file.attempt })}
        badge={
          marked.size > 0 ? (
            <Badge tone="critical">{t('decisions.evidence.errorLines', { count: marked.size })}</Badge>
          ) : null
        }
        open={marked.size > 0}
      >
        <p className="mb-2 font-mono text-xs text-muted">{file.path}</p>
        <pre className="max-h-96 overflow-auto rounded-md bg-surface-2 font-mono text-xs text-text">
          {lines.map((line, index) => (
            <div
              key={index}
              className={cn('flex gap-3 px-3', marked.has(index + 1) && 'bg-critical/15')}
              data-line={index + 1}
            >
              <span className="w-12 shrink-0 select-none text-right text-muted">{index + 1}</span>
              <span className="whitespace-pre">{line}</span>
            </div>
          ))}
        </pre>
      </Panel>
      {file.before !== undefined && (
        <Panel
          icon={<GitCompare size={14} />}
          title={t('decisions.evidence.diff', { file: name })}
          badge={
            <Badge>
              {changed > 0
                ? t('decisions.evidence.linesChanged', { count: changed })
                : t('decisions.evidence.noChange')}
            </Badge>
          }
        >
          {hunks.length === 0 ? (
            <p className="text-sm text-muted">{t('decisions.evidence.noChange')}</p>
          ) : (
            <pre className="max-h-96 overflow-auto rounded-md bg-surface-2 font-mono text-xs text-text">
              {hunks.map((hunk, h) => (
                <div key={h} className={cn(h > 0 && 'mt-2 border-t border-dashed border-border pt-2')}>
                  {hunk.map((line, i) => (
                    <div
                      key={i}
                      className={cn(
                        'flex gap-3 px-3',
                        line.kind === 'add' && 'bg-good/15',
                        line.kind === 'del' && 'bg-critical/15',
                      )}
                    >
                      <span className="w-10 shrink-0 select-none text-right text-muted">{line.before ?? ''}</span>
                      <span className="w-10 shrink-0 select-none text-right text-muted">{line.after ?? ''}</span>
                      <span className="w-3 shrink-0 select-none">
                        {line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ' '}
                      </span>
                      <span className="whitespace-pre">{line.text}</span>
                    </div>
                  ))}
                </div>
              ))}
            </pre>
          )}
        </Panel>
      )}
    </>
  )
}

function AnalysisPanel({ analysis }: { analysis: Analysis }) {
  const { t } = useTranslation()
  const best = Math.max(...analysis.options.map((o) => o.confidence ?? 0), 0)
  return (
    <Panel icon={<Sparkles size={14} className="text-accent-ink" />} title={t('decisions.evidence.analysis')} open>
      <div className="space-y-3 text-sm">
        {analysis.cause && (
          <p className="text-text">
            <span className="font-medium">{t('decisions.evidence.cause')}: </span>
            {analysis.cause}
          </p>
        )}
        {analysis.change && (
          <p className="text-text-2">
            <span className="font-medium text-text">{t('decisions.evidence.change')}: </span>
            {analysis.change}
          </p>
        )}
        {analysis.options.length > 0 && (
          <ul className="space-y-2">
            {analysis.options.map((o) => {
              const confidence = o.confidence ?? 0
              return (
                <li key={o.key} className={cn('rounded-md p-2', confidence === best ? 'bg-accent/10' : 'bg-surface-2')}>
                  <div className="flex items-center gap-2">
                    {confidence === best && <span aria-hidden>★</span>}
                    <span className="font-medium text-text">{o.label}</span>
                    {o.confidence !== undefined && (
                      <Badge className="ml-auto">
                        {t('questions.confidence', { value: Math.round(confidence * 100) })}
                      </Badge>
                    )}
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-border">
                    <div className="h-full bg-accent" style={{ width: `${Math.round(confidence * 100)}%` }} />
                  </div>
                  {o.rationale && <p className="mt-1 text-text-2">{o.rationale}</p>}
                  {o.instruction && (
                    <p className="mt-1 text-xs text-text-2">
                      <span className="font-medium">{t('decisions.evidence.instruction')}: </span>
                      {o.instruction}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </Panel>
  )
}
