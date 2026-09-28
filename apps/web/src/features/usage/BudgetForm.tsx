import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSaveBudget, type Budget } from '@/api/ai'
import { useProjects } from '@/api/admin'
import { Button, Field, Input, Select, Toggle } from '@/components/ui/primitives'
import { Drawer, toast } from '@/components/ui/overlay'
import { errorMessage } from '@/features/admin/AdminForms'
import { Notice } from '@/features/projects/NewProjectWizard'

/** A budget for the whole customer or one project, monthly or for the whole life of the project. */
export function BudgetForm({ open, onClose, initial }: { open: boolean; onClose: () => void; initial?: Budget }) {
  const { t } = useTranslation()
  const projects = useProjects()
  const save = useSaveBudget()
  const [projectId, setProjectId] = useState(initial?.projectId ?? '')
  const [period, setPeriod] = useState<Budget['period']>(initial?.period ?? 'monthly')
  const [amount, setAmount] = useState(initial ? String(Number(initial.amountUsd)) : '')
  const [alertPct, setAlertPct] = useState(String(initial?.alertPct ?? 80))
  const [hardStop, setHardStop] = useState(initial?.hardStop ?? true)
  const valid = Number(amount) > 0 && Number(alertPct) >= 1 && Number(alertPct) <= 99

  async function submit() {
    try {
      await save.mutateAsync({
        id: initial?.id ?? null,
        body: {
          projectId: projectId || null,
          period,
          amountUsd: amount,
          alertPct: Number(alertPct),
          hardStop,
        },
      })
      toast(t('usage.budgetSaved'))
      onClose()
    } catch (error) {
      toast(t('aiForms.saveFailed', { message: errorMessage(error) }))
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={initial ? t('usage.editBudget') : t('usage.newBudget')}
      description={t('usage.budgetsHint')}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={!valid || save.isPending} onClick={submit}>
            {t('common.save')}
          </Button>
        </>
      }
    >
      <Field label={t('usage.scope')}>
        <Select value={projectId} disabled={!!initial} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">{t('ai.wholeTenant')}</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t('usage.period')}>
          <Select value={period} onChange={(e) => setPeriod(e.target.value as Budget['period'])}>
            <option value="monthly">{t('usage.periods.monthly')}</option>
            <option value="total">{t('usage.periods.total')}</option>
          </Select>
        </Field>
        <Field label={t('usage.amount')}>
          <Input
            type="number"
            min="0.01"
            step="0.01"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </Field>
        <Field label={t('usage.alertAt')} hint={t('usage.alertAtHint')}>
          <Input type="number" min="1" max="99" value={alertPct} onChange={(e) => setAlertPct(e.target.value)} />
        </Field>
      </div>
      <Toggle checked={hardStop} onChange={setHardStop} label={t('usage.hardStop')} />
      <Notice tone="info">{t('usage.hardStopHint')}</Notice>
    </Drawer>
  )
}
