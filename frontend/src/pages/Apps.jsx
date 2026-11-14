import { useMemo, useState } from 'react'
import { AppWindow, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { api, useApi } from '../api'
import { Badge, Button, Card, ConfirmModal, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, Toggle, useToast } from '../components/ui'
import { categoryColor } from '../lib/format'

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
            <datalist id="cats">{categories.map((c) => <option key={c} value={c} />)}</datalist>
          </Field>
        </div>
        <Field label="Web addresses" help="One per line. Each one also covers its sub-addresses, so youtube.com covers www.youtube.com and m.youtube.com.">
          <textarea className="input font-mono text-xs" rows={7} value={form.domains} onChange={set('domains')} placeholder={'example.com\ncdn.example.net'} />
        </Field>
        <Toggle checked={form.track_time} onChange={set('track_time')} label="Count as screen time" description="Turn off for background services like system updates." />
      </div>
    </Modal>
  )
}

export default function Apps() {
  const { data, error, loading, reload } = useApi('/services')
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const groups = useMemo(() => {
    const g = {}
    for (const s of data?.services || []) {
      if (q && !`${s.name} ${s.category} ${s.domains.join(' ')}`.toLowerCase().includes(q.toLowerCase())) continue
      ;(g[s.category] ||= []).push(s)
    }
    return Object.entries(g).sort(([a], [b]) => a.localeCompare(b))
  }, [data, q])

  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />

  return (
    <>
      <PageHeader title="Apps & categories" description="How internet lookups are turned into apps and screen time. Add your own apps or fix ones that look wrong."
        actions={<Button icon={Plus} onClick={() => setEditing({})}>Add app</Button>} />
      <div className="relative mb-6 max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input className="input pl-9" placeholder="Search apps or addresses…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {groups.length === 0 ? <Card><EmptyState icon={AppWindow} title="No apps found" /></Card> : (
        <div className="space-y-6">
          {groups.map(([cat, items]) => (
            <Card key={cat} bodyClass="" title={<span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(cat) }} />{cat}</span>} subtitle={`${items.length} app${items.length === 1 ? '' : 's'}`}>
              <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.map((s) => (
                  <li key={s.id} className="flex items-center gap-4 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="flex items-center gap-2 text-sm font-medium">{s.name}{!s.track_time && <Badge>Background</Badge>}</p>
                      <p className="truncate font-mono text-xs text-slate-500">{s.domains.join(', ')}</p>
                    </div>
                    <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(s)}>Edit</Button>
                    <Button size="sm" variant="ghost" icon={Trash2} className="text-red-600" onClick={() => setDeleting(s)} aria-label="Delete" />
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
      {editing && <ServiceModal service={editing} categories={data.categories} onClose={() => setEditing(null)} onSaved={reload} />}
      <ConfirmModal open={!!deleting} onClose={() => setDeleting(null)} danger title={`Delete ${deleting?.name}?`} confirmLabel="Delete"
        message="Its usage history will be removed, and its addresses will show as unrecognised."
        onConfirm={async () => { await api(`/services/${deleting.id}`, { method: 'DELETE' }); setDeleting(null); reload() }} />
    </>
  )
}
