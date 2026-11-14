import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { AppWindow, Check, CheckCheck, EyeOff, GitMerge, Pencil, Plus, RefreshCw, Search, Sparkles, Trash2 } from 'lucide-react'
import { api, useApi } from '../api'
import {
  Badge, Button, Callout, Card, ConfirmModal, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, Segmented, Select, Tabs, Toggle, useToast,
} from '../components/ui'
import { categoryColor, number, timeAgo } from '../lib/format'

const SOURCE = {
  builtin: { label: 'Built-in', color: 'gray' },
  adguard: { label: 'AdGuard', color: 'green' },
  auto: { label: 'Auto-detected', color: 'violet' },
  user: { label: 'Yours', color: 'blue' },
}
const SUGGESTED_CATEGORIES = ['Video', 'Social', 'Messaging', 'Gaming', 'Music', 'Education', 'Kids', 'Finance', 'Shopping',
  'News', 'Productivity', 'AI', 'Government', 'Gambling', 'Privacy', 'Other', 'System']

function ServiceModal({ service, categories, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({ name: service.name || '', category: service.category || '', domains: (service.domains || []).join('\n'), track_time: service.track_time ?? true })
  const [busy, setBusy] = useState(false)
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v?.target ? v.target.value : v }))
  const save = async () => {
    setBusy(true)
    try {
      const body = { ...form, domains: form.domains.split(/[\s,]+/).filter(Boolean) }
      await api(service.id ? `/services/${service.id}` : '/services', { method: service.id ? 'PUT' : 'POST', body })
      toast('App saved')
      onSaved()
      onClose()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title={service.id ? `Edit ${service.name}` : 'Add an app'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save} disabled={!form.name || !form.category}>Save</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={form.name} onChange={set('name')} placeholder="e.g. Fortnite" /></Field>
          <Field label="Category">
            <input className="input" list="cats" value={form.category} onChange={set('category')} placeholder="e.g. Gaming" />
            <datalist id="cats">{[...new Set([...categories, ...SUGGESTED_CATEGORIES])].map((c) => <option key={c} value={c} />)}</datalist>
          </Field>
        </div>
        <Field label="Web addresses" help="One per line. Each also covers its sub-addresses (youtube.com covers m.youtube.com).">
          <textarea className="input font-mono text-xs" rows={7} value={form.domains} onChange={set('domains')} placeholder={'example.com\ncdn.example.net'} />
        </Field>
        <Toggle checked={form.track_time} onChange={set('track_time')} label="Count as screen time" description="Turn off for background services like system updates." />
      </div>
    </Modal>
  )
}

function ReviewRow({ s, categories, targets, onDone }) {
  const toast = useToast()
  const [name, setName] = useState(s.name)
  const [cat, setCat] = useState(s.category)
  const [mergeTo, setMergeTo] = useState('')
  const [busy, setBusy] = useState('')
  const act = async (key, fn, msg) => {
    setBusy(key)
    try { await fn(); toast(msg); onDone() } catch (e) { toast(e.message, 'error'); setBusy('') }
  }
  return (
    <li className="grid gap-3 px-5 py-4 lg:grid-cols-12 lg:items-center">
      <div className="lg:col-span-4">
        <input className="input py-1.5 font-medium" value={name} onChange={(e) => setName(e.target.value)} />
        <p className="mt-1 truncate font-mono text-xs text-slate-500" title={s.domains.join(', ')}>{s.registrable || s.domains[0]}</p>
      </div>
      <div className="text-xs text-slate-500 lg:col-span-2">
        <p>{number(s.lookups_7d)} lookups · {s.devices_7d} device{s.devices_7d === 1 ? '' : 's'}</p>
        <p>First seen {timeAgo(s.created)}</p>
      </div>
      <div className="lg:col-span-2">
        <input className="input py-1.5" list="review-cats" value={cat} onChange={(e) => setCat(e.target.value)} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 lg:col-span-4 lg:justify-end">
        <Button size="sm" icon={Check} loading={busy === 'keep'} onClick={() => act('keep', () => api(`/services/${s.id}/review`, { method: 'POST', body: { name, category: cat } }), `${name} kept`)}>Keep</Button>
        <Select className="w-36" value={mergeTo} onChange={setMergeTo} options={[{ value: '', label: 'Merge into…' }, ...targets.map((t) => ({ value: String(t.id), label: t.name }))]} />
        {mergeTo && <Button size="sm" variant="secondary" icon={GitMerge} loading={busy === 'merge'}
          onClick={() => act('merge', () => api(`/services/${s.id}/merge`, { method: 'POST', body: { into: Number(mergeTo) } }), `Merged into ${targets.find((t) => String(t.id) === mergeTo)?.name}`)}>Merge</Button>}
        <Button size="sm" variant="ghost" icon={EyeOff} loading={busy === 'bg'} title="Not a real app (e.g. a background service). Never counted as screen time."
          onClick={() => act('bg', () => api(`/services/${s.id}/review`, { method: 'POST', body: { background: true } }), `${name} marked as background`)}>Background</Button>
      </div>
    </li>
  )
}

export default function Apps() {
  const toast = useToast()
  const { data, error, loading, reload } = useApi('/services')
  const [tab, setTab] = useState(null)
  const [q, setQ] = useState('')
  const [source, setSource] = useState('all')
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [busy, setBusy] = useState('')

  const services = data?.services || []
  const review = services.filter((s) => s.source === 'auto' && !s.reviewed && !s.hidden).sort((a, b) => b.lookups_7d - a.lookups_7d)
  const targets = services.filter((s) => s.source !== 'auto' || s.reviewed).sort((a, b) => a.name.localeCompare(b.name))
  const activeTab = tab || (review.length ? 'review' : 'all')

  const groups = useMemo(() => {
    const g = {}
    for (const s of services) {
      if (source === 'background' ? !s.hidden : source !== 'all' && s.source !== source) continue
      if (q && !`${s.name} ${s.category} ${s.domains.join(' ')}`.toLowerCase().includes(q.toLowerCase())) continue
      ;(g[s.hidden ? 'Background' : s.category] ||= []).push(s)
    }
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b))
  }, [services, q, source])

  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />

  const syncAdGuard = async () => {
    setBusy('sync')
    try { const r = await api('/services/sync-adguard', { method: 'POST' }); toast(`AdGuard app list synced: ${r.added} added, ${r.updated} updated`); reload() } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }
  const acceptAll = async () => {
    setBusy('all')
    try { await api('/services/review-all', { method: 'POST' }); toast('All suggestions accepted'); reload() } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }

  return (
    <>
      <PageHeader title="Apps & categories"
        description="HomeNet detects apps automatically: AdGuard's list covers popular apps, and any other site becomes an app once it's used. Tidy up new ones here."
        actions={<>
          <Button variant="secondary" icon={RefreshCw} loading={busy === 'sync'} onClick={syncAdGuard}
            title={data.adguard_synced ? `Last synced ${timeAgo(data.adguard_synced)}` : 'Not synced yet'}>Sync AdGuard apps</Button>
          <Button icon={Plus} onClick={() => setEditing({})}>Add app</Button>
        </>} />

      {!data.auto_detect && (
        <Callout tone="info" className="mb-6" action={<Link to="/settings/detection"><Button size="sm" variant="secondary">Settings</Button></Link>}>
          Automatic detection is off, so only apps in this list are recognised.
        </Callout>
      )}

      <Tabs value={activeTab} onChange={setTab} tabs={[
        { value: 'review', label: 'New to review', icon: Sparkles, count: review.length },
        { value: 'all', label: 'All apps', icon: AppWindow, count: services.length },
      ]} />

      {activeTab === 'review' && (
        review.length === 0 ? (
          <Card><EmptyState icon={CheckCheck} title="Nothing to review" description={`New apps appear here as they're detected.${data.pending_sites ? ` ${data.pending_sites} more sites are being watched until they're used enough.` : ''}`} /></Card>
        ) : (
          <Card bodyClass="" title={`${review.length} new app${review.length === 1 ? '' : 's'} detected`}
            subtitle="Already counting. Keep them, fix the name or category, merge into an existing app, or mark as background."
            actions={<Button size="sm" variant="secondary" icon={CheckCheck} loading={busy === 'all'} onClick={acceptAll}>Accept all suggestions</Button>}>
            <datalist id="review-cats">{[...new Set([...data.categories, ...SUGGESTED_CATEGORIES])].map((c) => <option key={c} value={c} />)}</datalist>
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {review.map((s) => <ReviewRow key={s.id} s={s} categories={data.categories} targets={targets} onDone={reload} />)}
            </ul>
          </Card>
        )
      )}

      {activeTab === 'all' && (
        <>
          <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center">
            <div className="relative max-w-md flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input className="input pl-9" placeholder="Search apps or addresses…" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <Segmented value={source} onChange={setSource} options={[
              { value: 'all', label: 'All' }, { value: 'builtin', label: 'Built-in' }, { value: 'adguard', label: 'AdGuard' },
              { value: 'auto', label: 'Auto' }, { value: 'user', label: 'Yours' }, { value: 'background', label: 'Background' },
            ]} />
          </div>
          {groups.length === 0 ? <Card><EmptyState icon={AppWindow} title="No apps found" /></Card> : (
            <div className="space-y-6">
              {groups.map(([cat, items]) => (
                <Card key={cat} bodyClass="" title={<span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(cat) }} />{cat}</span>} subtitle={`${items.length} app${items.length === 1 ? '' : 's'}`}>
                  <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                    {items.map((s) => (
                      <li key={s.id} className="flex items-center gap-4 px-5 py-3">
                        <div className="min-w-0 flex-1">
                          <p className="flex flex-wrap items-center gap-2 text-sm font-medium">{s.name}
                            <Badge color={SOURCE[s.source]?.color || 'gray'}>{SOURCE[s.source]?.label || s.source}</Badge>
                            {!s.track_time && !s.hidden && <Badge>Not screen time</Badge>}
                            {s.source === 'auto' && !s.reviewed && <Badge color="amber">New</Badge>}
                          </p>
                          <p className="truncate font-mono text-xs text-slate-500">{s.domains.join(', ')}</p>
                        </div>
                        <span className="hidden text-xs tabular-nums text-slate-400 sm:block">{s.lookups_7d ? `${number(s.lookups_7d)} / 7d` : ''}</span>
                        <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(s)}>Edit</Button>
                        <Button size="sm" variant="ghost" icon={Trash2} className="text-red-600" onClick={() => setDeleting(s)} aria-label="Delete" />
                      </li>
                    ))}
                  </ul>
                </Card>
              ))}
            </div>
          )}
        </>
      )}

      {editing && <ServiceModal service={editing} categories={data.categories} onClose={() => setEditing(null)} onSaved={reload} />}
      <ConfirmModal open={!!deleting} onClose={() => setDeleting(null)} danger title={`Delete ${deleting?.name}?`} confirmLabel="Delete"
        message={deleting?.source === 'adguard' || deleting?.source === 'auto'
          ? "Its history will be removed. It may be detected again if it's still used. To stop that, mark it as Background instead."
          : 'Its usage history will be removed, and its addresses will show as unrecognised.'}
        onConfirm={async () => { await api(`/services/${deleting.id}`, { method: 'DELETE' }); setDeleting(null); reload() }} />
    </>
  )
}
