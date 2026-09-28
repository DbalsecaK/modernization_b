import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bot, Image, Loader2, Paperclip, Send, UserRound } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Badge, Button, Card, CardHeader } from '@/components/ui/primitives'

// Chat with the UX/UI designer agent to request prototype changes (spec 7.4). Each accepted request produces
// a new prototype version; the history stays linked to the screen specification.

type Message = { id: number; from: 'user' | 'agent'; text: string; version?: number; attachment?: string }

export function PrototypeChat({ screen }: { screen: string }) {
  const { t } = useTranslation()
  const [version, setVersion] = useState(2)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [attachment, setAttachment] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([
    { id: 1, from: 'user', text: 'Move the credit limit next to the current balance.' },
    { id: 2, from: 'agent', text: 'Done. Limits and balances are now grouped in one "Balances" section.', version: 2 },
  ])
  const list = useRef<HTMLDivElement>(null)

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [messages, busy])

  const suggestions = [t('protoChat.suggest.fields'), t('protoChat.suggest.mobile'), t('protoChat.suggest.errors'), t('protoChat.suggest.brand')]

  function send(value: string) {
    const request = value.trim()
    if (!request || busy) return
    const next = version + 1
    setMessages((m) => [...m, { id: Date.now(), from: 'user', text: request, attachment: attachment ?? undefined }])
    setText('')
    setAttachment(null)
    setBusy(true)
    window.setTimeout(() => {
      setMessages((m) => [...m, { id: Date.now() + 1, from: 'agent', text: t('protoChat.reply', { request, version: next }), version: next }])
      setVersion(next)
      setBusy(false)
    }, 1400)
  }

  return (
    <Card className="flex h-[480px] flex-col">
      <CardHeader title={t('protoChat.title')} subtitle={t('protoChat.subtitle', { screen })} action={<Badge tone="info">v{version}</Badge>} />
      <div ref={list} className="flex-1 space-y-3 overflow-y-auto px-5 py-4">
        {messages.map((m) => (
          <div key={m.id} className={cn('flex gap-2', m.from === 'user' && 'flex-row-reverse')}>
            <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full', m.from === 'agent' ? 'bg-brand/10 text-brand dark:bg-accent/15 dark:text-accent' : 'bg-surface-2 text-muted')}>
              {m.from === 'agent' ? <Bot size={14} /> : <UserRound size={14} />}
            </span>
            <div className={cn('max-w-[80%] rounded-lg px-3 py-2 text-sm', m.from === 'agent' ? 'bg-surface-2 text-text' : 'bg-series-1/10 text-text')}>
              {m.text}
              {m.attachment && (
                <div className="mt-1 flex items-center gap-1 text-xs text-muted">
                  <Image size={12} /> {m.attachment}
                </div>
              )}
              {m.version && <div className="mt-1 text-xs text-muted">{t('protoChat.newVersion', { version: m.version })}</div>}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-xs text-muted">
            <Loader2 size={14} className="animate-spin" /> {t('protoChat.working')}
          </div>
        )}
      </div>
      <div className="space-y-2 border-t border-border px-4 py-3">
        <div className="flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy} className="rounded-full border border-border px-2.5 py-1 text-xs text-text-2 hover:bg-surface-2 disabled:opacity-50">
              {s}
            </button>
          ))}
        </div>
        {attachment && <div className="text-xs text-muted">{t('protoChat.attached', { name: attachment })}</div>}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
        >
          <label className="flex cursor-pointer items-center rounded-md border border-border px-2.5 text-muted hover:bg-surface-2" title={t('protoChat.attach')}>
            <Paperclip size={16} />
            <input type="file" accept="image/*" className="sr-only" onChange={(e) => setAttachment(e.target.files?.[0]?.name ?? null)} aria-label={t('protoChat.attach')} />
          </label>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={t('protoChat.placeholder')}
            aria-label={t('protoChat.placeholder')}
            className="h-10 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text placeholder:text-muted focus:outline-none"
          />
          <Button type="submit" variant="primary" disabled={!text.trim() || busy} aria-label={t('protoChat.send')}>
            <Send size={16} />
          </Button>
        </form>
      </div>
    </Card>
  )
}
