import { useState } from 'react'
import { BedDouble, BookOpen, CalendarClock, Check, Pencil, Plus, Trash2, Utensils } from 'lucide-react'
import { api, useApi } from '../api'
import DeviceIcon from '../components/DeviceIcon'
import { ServicePicker } from '../components/Pickers'
import { Badge, Button, Callout, Card, ConfirmModal, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, Segmented, Toggle, cx, useToast } from '../components/ui'
import { DAYS } from '../lib/format'

const TEMPLATES = [
  { icon: BedDouble, name: 'Bedtime', action: 'pause_internet', days: [0, 1, 2, 3, 4, 5, 6], start: '21:00', end: '07:00' },
  { icon: BookOpen, name: 'School-night homework', action: 'block_services', services: ['youtube', 'tiktok', 'roblox', 'instagram'], days: [0, 1, 2, 3], start: '16:00', end: '18:00' },
  { icon: Utensils, name: 'Dinner time', action: 'pause_internet', days: [0, 1, 2, 3, 4, 5, 6], start: '18:00', end: '19:00' },
]

const EMPTY = { name: '', device_ids: [], action: 'pause_internet', services: [], days: [0, 1, 2, 3, 4], start: '21:00', end: '07:00', enabled: true }

export function RuleModal({ rule, onClose, onSaved }) {
  const toast = useToast()
  const { data } = useApi('/devices')
  const [form, setForm] = useState({ ...EMPTY, ...rule })
  const [busy, setBusy] = useState(false)
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v?.target ? v.target.value : v }))
  const toggleIn = (k, v) => setForm((f) => ({ ...f, [k]: f[k].includes(v) ? f[k].filter((x) => x !== v) : [...f[k], v] }))

  const save = async () => {
    setBusy(true)
    try {
      const body = { ...form, name: form.name || (form.action === 'pause_internet' ? 'Internet pause' : 'App block') }
      await api(rule.id ? `/rules/${rule.id}` : '/rules', { method: rule.id ? 'PUT' : 'POST', body })
      toast('Schedule saved')
      onSaved?.()
      onClose()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  const devices = (data?.devices || []).filter((d) => !d.is_self)
  const overnight = form.start > form.end

  return (
    <Modal open onClose={onClose} size="lg" title={rule.id ? 'Edit schedule' : 'New schedule'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save}>Save schedule</Button></>}>
      <div className="space-y-5">
        <Field label="Name"><input className="input" value={form.name} onChange={set('name')} placeholder="e.g. Bedtime" /></Field>
        <div>
          <span className="label">What should happen?</span>
          <Segmented value={form.action} onChange={set('action')} options={[{ value: 'pause_internet', label: 'Pause internet' }, { value: 'block_services', label: 'Block certain apps' }]} />
        </div>
        {form.action === 'block_services' && <div><span className="label">Apps to block</span><ServicePicker value={form.services} onChange={set('services')} /></div>}
        <div>
          <span className="label">Devices</span>
          <div className="grid max-h-52 gap-2 overflow-y-auto sm:grid-cols-2">
            {devices.map((d) => (
              <button type="button" key={d.id} onClick={() => toggleIn('device_ids', d.id)}
                className={cx('flex items-center gap-3 rounded-lg border px-3 py-2 text-left text-sm transition',
                  form.device_ids.includes(d.id) ? 'border-brand-500 bg-brand-50 ring-1 ring-brand-500 dark:bg-brand-950/40' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800')}>
                <DeviceIcon type={d.type} online={d.is_online} size="sm" />
                <span className="min-w-0 flex-1 truncate">{d.display_name}{d.owner && <span className="block text-xs text-slate-500">{d.owner}</span>}</span>
                <span className={cx('flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
                  form.device_ids.includes(d.id) ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-300 dark:border-slate-600')}>
                  {form.device_ids.includes(d.id) && <Check className="h-3 w-3" />}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div>
          <span className="label">Days</span>
          <div className="flex flex-wrap gap-2">
            {DAYS.map((d, i) => (
              <button type="button" key={d} onClick={() => toggleIn('days', i)}
                className={cx('h-10 w-12 rounded-lg border text-sm font-medium transition', form.days.includes(i) ? 'border-brand-600 bg-brand-600 text-white' : 'border-slate-200 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800')}>{d}</button>
            ))}
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="From"><input type="time" className="input" value={form.start} onChange={set('start')} /></Field>
          <Field label="Until" help={overnight ? 'Runs overnight into the next morning.' : form.start === form.end ? 'Same start and end means all day.' : undefined}>
            <input type="time" className="input" value={form.end} onChange={set('end')} />
          </Field>
        </div>
        <Toggle checked={form.enabled} onChange={set('enabled')} label="Schedule is on" />
      </div>
    </Modal>
  )
}

export default function Schedules() {
  const toast = useToast()
  const { data, error, loading, reload } = useApi('/rules', { refresh: 30000 })
  const devs = useApi('/devices')
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  const names = Object.fromEntries((devs.data?.devices || []).map((d) => [d.id, d.display_name]))

  const toggle = async (r) => {
    try { await api(`/rules/${r.id}`, { method: 'PUT', body: { ...r, enabled: !r.enabled } }); reload() } catch (e) { toast(e.message, 'error') }
  }

  return (
    <>
      <PageHeader title="Schedules" description="Pause the internet or block apps automatically at set times."
        actions={<Button icon={Plus} onClick={() => setEditing({})}>New schedule</Button>} />
      {!data.adguard_enabled && <Callout tone="warning" className="mb-6" title="Schedules need AdGuard Home">You can create schedules now. They start working once AdGuard Home is connected in Settings.</Callout>}

      {data.rules.length === 0 ? (
        <Card>
          <EmptyState icon={CalendarClock} title="No schedules yet" description="Start from a template or create your own." />
          <div className="mx-auto grid max-w-3xl gap-3 pb-4 sm:grid-cols-3">
            {TEMPLATES.map((t) => (
              <button key={t.name} onClick={() => setEditing({ ...t, icon: undefined })}
                className="rounded-xl border border-slate-200 p-4 text-left transition hover:border-brand-300 hover:bg-brand-50/50 dark:border-slate-700 dark:hover:border-brand-700 dark:hover:bg-brand-950/30">
                <t.icon className="mb-2 h-5 w-5 text-brand-600" />
                <p className="text-sm font-semibold">{t.name}</p>
                <p className="text-xs text-slate-500">{t.action === 'pause_internet' ? 'Pause internet' : 'Block distracting apps'} · {t.start}–{t.end}</p>
              </button>
            ))}
          </div>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {data.rules.map((r) => (
            <div key={r.id} className={cx('card p-5', r.active && 'ring-2 ring-red-400/60')}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="flex items-center gap-2 font-semibold">{r.name}{r.active && <Badge color="red" dot>Active now</Badge>}</p>
                  <p className="mt-1 text-sm text-slate-500">{r.action === 'pause_internet' ? 'Pauses internet' : `Blocks ${r.services.join(', ')}`}</p>
                </div>
                <Toggle checked={r.enabled} onChange={() => toggle(r)} />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
                <span className="rounded-md bg-slate-100 px-2 py-1 font-medium tabular-nums dark:bg-slate-800">{r.start} – {r.end}</span>
                <span className="text-slate-500">{r.days.length === 7 ? 'Every day' : r.days.map((d) => DAYS[d]).join(', ')}</span>
              </div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {r.device_ids.map((id) => <Badge key={id} color="blue">{names[id] || `Device ${id}`}</Badge>)}
              </div>
              <div className="mt-4 flex justify-end gap-2 border-t border-slate-100 pt-3 dark:border-slate-800">
                <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(r)}>Edit</Button>
                <Button size="sm" variant="ghost" icon={Trash2} className="text-red-600" onClick={() => setDeleting(r)}>Delete</Button>
              </div>
            </div>
          ))}
        </div>
      )}
      {editing && <RuleModal rule={editing} onClose={() => setEditing(null)} onSaved={reload} />}
      <ConfirmModal open={!!deleting} onClose={() => setDeleting(null)} danger title="Delete schedule?" confirmLabel="Delete"
        message={`"${deleting?.name}" will stop running straight away.`}
        onConfirm={async () => { await api(`/rules/${deleting.id}`, { method: 'DELETE' }); setDeleting(null); reload() }} />
    </>
  )
}
