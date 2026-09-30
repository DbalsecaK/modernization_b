import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Bot, Check, Loader2, Send, UserRound, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { ApiError } from '@/api/client'
import { useAskChange, useChat, useDecideProposal, type ChatMessage } from '@/api/screens'
import { Badge, Button, Card, CardHeader } from '@/components/ui/primitives'

// Chat with the UX/UI designer agent to request prototype changes (spec 7.4, D-24), connected to the API: each
// request is enqueued for the worker; a change within the screen spec comes back as a new prototype version, one
// that adds fields the spec does not have comes back as a proposal a person accepts or rejects here. The chat never
// approves C2.

export function PrototypeChat({
  projectId,
  screen,
  title,
  version,
  canEdit,
}: {
  projectId: string
  screen: string
  title: string
  version: number | null
  canEdit: boolean
}) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const chat = useChat(projectId, screen)
  const ask = useAskChange(projectId, screen)
  const decide = useDecideProposal(projectId, screen)
  const messages = chat.data ?? []
  const busy = messages.some((m) => m.status === 'pending') || ask.isPending
  const list = useRef<HTMLDivElement>(null)

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [messages.length, busy])

  const suggestions = [
    t('protoChat.suggest.fields'),
    t('protoChat.suggest.mobile'),
    t('protoChat.suggest.errors'),
    t('protoChat.suggest.brand'),
  ]

  function send(value: string) {
    const request = value.trim()
    if (request.length < 3 || busy || !canEdit) return
    ask.mutate(request, { onSuccess: () => setText('') })
  }

  const error = ask.error ?? decide.error

  return (
    <Card className="flex h-[480px] flex-col">
      <CardHeader
        title={t('protoChat.title')}
        subtitle={t('protoChat.subtitle', { screen: title })}
        action={version ? <Badge tone="info">v{version}</Badge> : undefined}
      />
      <div ref={list} className="flex-1 space-y-3 overflow-y-auto px-5 py-4" aria-live="polite">
        {messages.length === 0 && !chat.isLoading && <p className="text-sm text-muted">{t('protoChat.empty')}</p>}
        {messages.map((m) => (
          <Message
            key={m.id}
            message={m}
            canEdit={canEdit}
            deciding={decide.isPending}
            onDecide={(accept) => decide.mutate({ id: m.id, accept })}
          />
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-muted" role="status">
            <Loader2 size={14} className="animate-spin" /> {t('protoChat.working')}
          </div>
        )}
      </div>
      <div className="space-y-2 border-t border-border px-4 py-3">
        {error && (
          <p className="text-xs text-critical" role="alert">
            {error instanceof ApiError ? error.message : t('protoChat.failed')}
          </p>
        )}
        {canEdit ? (
          <>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  disabled={busy}
                  className="rounded-full border border-border px-2.5 py-1 text-xs text-text-2 hover:bg-surface-2 disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                send(text)
              }}
            >
              <input
                value={text}
                maxLength={2000}
                onChange={(e) => setText(e.target.value)}
                placeholder={t('protoChat.placeholder')}
                aria-label={t('protoChat.placeholder')}
                className="h-10 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-muted focus:outline-none"
              />
              <Button
                type="submit"
                variant="primary"
                disabled={text.trim().length < 3 || busy}
                aria-label={t('protoChat.send')}
              >
                <Send size={16} />
              </Button>
            </form>
          </>
        ) : (
          <p className="text-xs text-muted">{t('protoChat.readOnly')}</p>
        )}
      </div>
    </Card>
  )
}

function Message({
  message: m,
  canEdit,
  deciding,
  onDecide,
}: {
  message: ChatMessage
  canEdit: boolean
  deciding: boolean
  onDecide: (accept: boolean) => void
}) {
  const { t } = useTranslation()
  const agent = m.role === 'agent'
  return (
    <div className={cn('flex gap-2', !agent && 'flex-row-reverse')}>
      <span
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          agent ? 'bg-brand/10 text-brand dark:bg-accent/15 dark:text-accent' : 'bg-surface-2 text-muted',
        )}
      >
        {agent ? <Bot size={14} /> : <UserRound size={14} />}
      </span>
      <div
        className={cn(
          'max-w-[80%] rounded-lg px-3 py-2 text-sm',
          agent ? 'bg-surface-2 text-text' : 'bg-series-1/10 text-text',
          m.status === 'failed' && agent && 'border border-critical/40',
        )}
      >
        {!agent && m.author && <div className="mb-0.5 text-xs font-medium text-text-2">{m.author}</div>}
        {m.status === 'failed' && agent && <AlertTriangle size={12} className="mr-1 inline text-critical" />}
        {m.body}
        {m.prototypeVersion && (
          <div className="mt-1 text-xs text-muted">{t('protoChat.newVersion', { version: m.prototypeVersion })}</div>
        )}
        {m.status === 'proposal' && (
          <div className="mt-2 space-y-2">
            <div className="flex flex-wrap gap-1">
              {m.proposalFields.map((f) => (
                <Badge key={f} tone="warning">
                  {f}
                </Badge>
              ))}
            </div>
            {canEdit && (
              <div className="flex gap-2">
                <Button size="sm" variant="primary" disabled={deciding} onClick={() => onDecide(true)}>
                  <Check size={14} /> {t('protoChat.accept')}
                </Button>
                <Button size="sm" disabled={deciding} onClick={() => onDecide(false)}>
                  <X size={14} /> {t('protoChat.reject')}
                </Button>
              </div>
            )}
          </div>
        )}
        {m.status === 'rejected' && <div className="mt-1 text-xs text-muted">{t('protoChat.rejected')}</div>}
      </div>
    </div>
  )
}
