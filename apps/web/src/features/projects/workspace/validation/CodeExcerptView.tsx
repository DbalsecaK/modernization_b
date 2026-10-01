import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/cn'
import type { CodeExcerpt } from '@/api/validation'
import { Card, CardHeader } from '@/components/ui/primitives'
import { excerptLines, excerptRange } from './model'

// A code excerpt with its real line numbers and the lines of the rule highlighted (same look as the prototype's
// CodeLines). The highlight is also said in text, never by color alone, and the scrollable
// block can be reached with the keyboard.
export function CodeExcerptView({ title, excerpt }: { title: string; excerpt: CodeExcerpt }) {
  const { t } = useTranslation()
  const range = excerptRange(excerpt)
  const lines = excerptLines(excerpt)
  const width = String(lines.at(-1)?.number ?? 1).length
  return (
    <Card className="min-w-0">
      <CardHeader
        title={title}
        subtitle={
          <span className="break-all font-mono text-xs">
            {range}
            {excerpt.highlighted.length > 0 && (
              <> · {t('traceability.highlightedLines', { count: excerpt.highlighted.length })}</>
            )}
          </span>
        }
      />
      <pre
        tabIndex={0}
        aria-label={t('traceability.codeOf', { title, range })}
        className="max-h-96 overflow-auto bg-surface-2 py-2 font-mono text-xs leading-relaxed focus:outline-2 focus:outline-brand"
      >
        {lines.map((line) => (
          <div
            key={line.number}
            className={cn(
              'flex min-w-max gap-3 border-l-2 px-3',
              line.highlighted ? 'border-warning bg-warning/25' : 'border-transparent',
            )}
          >
            <span
              className={cn(
                'shrink-0 text-right select-none',
                line.highlighted ? 'font-semibold text-text' : 'text-muted',
              )}
              style={{ width: `${width}ch` }}
            >
              {line.number}
            </span>
            {line.highlighted && <span className="sr-only">{t('traceability.highlighted')}</span>}
            <span className="whitespace-pre text-text">{line.text}</span>
          </div>
        ))}
      </pre>
      {excerpt.truncated && <p className="px-5 py-2 text-xs text-muted">{t('traceability.truncated')}</p>}
    </Card>
  )
}
