import { useMemo, useState } from 'react'
import { Hourglass, Pencil, Plus, Trash2, X } from 'lucide-react'
import { api, useApi } from '../api'
import SearchSelect from './SearchSelect'
import { Badge, Button, Callout, Card, ConfirmModal, EmptyState, Field, Modal, Toggle, cx, useToast } from './ui'
import { DAYS, categoryColor, duration } from '../lib/format'

const PRESETS = [15, 30, 45, 60, 90, 120, 180]
const fmtLimit = (m) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`)

export const fmtLimitMinutes = fmtLimit

/** Add/edit a daily time limit. Pass limit={target_type:'app', target, target_name} to start with an app chosen. */
export function LimitModal({ limit, device, onClose, onSaved }) {
  const toast = useToast()
  const { data } = useApi('/services')
  const [form, setForm] = useState({
    target_type: limit.target_type || '', target: limit.target || '', target_name: limit.target_name || '',
    minutes: limit.minutes || 60, days: limit.days || [0, 1, 2, 3, 4, 5, 6], enabled: limit.enabled ?? true,
  })
  const [busy, setBusy] = useState(false)
  const options = useMemo(() => {
    const svcs = (data?.services || []).filter((s) => s.track_time && !s.hidden && s.category !== 'System')
    const cats = [...new Set(svcs.map((s) => s.category))].sort()
    return [
      ...cats.map((c) => ({ value: `category:${c}`, label: `All ${c}`, group: 'Categories', hint: `${svcs.filter((s) => s.category === c).length} apps`,
        icon: <span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(c) }} /> })),
      ...svcs.slice().sort((a, b) => a.name.localeCompare(b.name)).map((s) => ({ value: `app:${s.id}`, label: s.name, group: 'Apps', hint: s.category,
        icon: <span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(s.category) }} /> })),
    ]
  }, [data])
  const toggleDay = (d) => setForm((f) => ({ ...f, days: f.days.includes(d) ? f.days.filter((x) => x !== d) : [...f.days, d] }))
  const save = async () => {
    setBusy(true)
    try {
      const body = { device_ids: limit.device_ids || [device.id], target_type: form.target_type, target: String(form.target),
        minutes: Number(form.minutes), days: form.days, enabled: form.enabled }
      await api(limit.id ? `/limits/${limit.id}` : '/limits', { method: limit.id ? 'PUT' : 'POST', body })
      toast('Time limit saved')
      onSaved()
      onClose()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title={limit.id ? 'Edit time limit' : 'New time limit'} description="Once the daily allowance is used up, it's blocked on this device until midnight."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!form.target} onClick={save}>Save limit</Button></>}>
      <div className="space-y-5">
        <div>
          <span className="label">App or category</span>
          {form.target ? (
            <div className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-700">
              <span className="text-sm font-medium">{form.target_name} <span className="text-xs font-normal text-slate-500">({form.target_type === 'app' ? 'app' : 'whole category'})</span></span>
              <button type="button" className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => setForm({ ...form, target: '', target_type: '' })}><X className="h-4 w-4" /></button>
            </div>
          ) : (
            <SearchSelect options={options} placeholder="Click to choose an app or a whole category…"
              onSelect={(v, o) => { const [t, id] = v.split(/:(.+)/); setForm({ ...form, target_type: t, target: id, target_name: o.label.replace(/^All /, '') }) }} />
          )}
        </div>
        <div>
          <span className="label">Daily allowance</span>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((m) => (
              <button type="button" key={m} onClick={() => setForm({ ...form, minutes: m })}
                className={cx('rounded-lg border px-3 py-1.5 text-sm font-medium', Number(form.minutes) === m ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800')}>{fmtLimit(m)}</button>
            ))}
          </div>
          <Field help="Or type any number of minutes."><input type="number" min={1} max={1440} className="input mt-2 w-32" value={form.minutes} onChange={(e) => setForm({ ...form, minutes: e.target.value })} /></Field>
        </div>
        <div>
          <span className="label">Days</span>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d, i) => (
              <button type="button" key={d} onClick={() => toggleDay(i)}
                className={cx('h-10 w-12 rounded-lg border text-sm font-medium', form.days.includes(i) ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800')}>{d}</button>
            ))}
          </div>
        </div>
        <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label="Limit is on" />
      </div>
    </Modal>
  )
}

/** Daily time limits for one device: allowance, today's use, and a progress bar. */
export default function LimitsCard({ device }) {
  const toast = useToast()
  const { data, reload } = useApi(`/limits?device_id=${device.id}`, { refresh: 30000 })
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const limits = data?.limits || []
  const toggle = async (l) => {
    try {
      await api(`/limits/${l.id}`, { method: 'PUT', body: { device_ids: l.device_ids, target_type: l.target_type, target: String(l.target), minutes: l.minutes, days: l.days, enabled: !l.enabled } })
      reload()
    } catch (e) { toast(e.message, 'error') }
  }
  return (
    <Card title={<span className="flex items-center gap-2"><Hourglass className="h-4 w-4" />Time limits</span>}
      subtitle="A daily allowance for an app or category. Only time actually in use counts. Blocked until midnight once it's used up."
      actions={<Button size="sm" icon={Plus} onClick={() => setEditing({})}>Add limit</Button>} bodyClass="">
      {data && !data.adguard_enabled && <div className="p-5"><Callout tone="warning">Time limits need AdGuard Home to be connected.</Callout></div>}
      {limits.length === 0 ? (
        <EmptyState icon={Hourglass} title="No time limits" description='e.g. "YouTube 1h a day" or "All Social 30m on school days".' />
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {limits.map((l) => {
            const u = l.usage.find((x) => x.device_id === device.id) || { used_seconds: 0, reached: false }
            const pct = Math.min(100, (u.used_seconds / (l.minutes * 60)) * 100)
            return (
              <li key={l.id} className="px-5 py-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium">
                      {l.target_type === 'category' ? `All ${l.target_name}` : l.target_name}
                      <span className="text-slate-500">· {fmtLimit(l.minutes)} a day</span>
                      {u.reached && l.applies_today && <Badge color="red" dot>Limit reached, blocked</Badge>}
                      {!l.enabled && <Badge>Off</Badge>}
                      {l.enabled && !l.applies_today && <Badge>Not today</Badge>}
                    </p>
                    <p className="text-xs text-slate-500">{l.days.length === 7 ? 'Every day' : l.days.map((d) => DAYS[d]).join(', ')}</p>
                  </div>
                  <Toggle checked={l.enabled} onChange={() => toggle(l)} />
                  <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(l)}>Edit</Button>
                  <Button size="sm" variant="ghost" icon={Trash2} className="text-red-600" aria-label="Delete limit" onClick={() => setDeleting(l)} />
                </div>
                <div className="mt-2 flex items-center gap-3">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className={cx('h-full rounded-full', u.reached ? 'bg-red-500' : pct > 80 ? 'bg-orange-500' : 'bg-emerald-500')} style={{ width: `${Math.max(1, pct)}%` }} />
                  </div>
                  <span className="w-32 text-right text-xs tabular-nums text-slate-500">{duration(u.used_seconds)} of {fmtLimit(l.minutes)} today</span>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {editing && <LimitModal limit={editing} device={device} onClose={() => setEditing(null)} onSaved={reload} />}
      <ConfirmModal open={!!deleting} onClose={() => setDeleting(null)} danger title="Delete time limit?" confirmLabel="Delete"
        message="If it's currently blocking, the block is lifted within a minute."
        onConfirm={async () => { await api(`/limits/${deleting.id}`, { method: 'DELETE' }); setDeleting(null); reload() }} />
    </Card>
  )
}
