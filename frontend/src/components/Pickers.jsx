import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { api, useApi } from '../api'
import { Button, Callout, Field, Modal, Select, Spinner, cx, useToast } from './ui'

/** Grid of AdGuard's blockable services (YouTube, TikTok, Roblox…) with checkboxes. */
export function ServicePicker({ value, onChange }) {
  const { data, loading } = useApi('/adguard/services')
  const [q, setQ] = useState('')
  const selected = new Set(value)
  const list = useMemo(() => (data?.services || []).filter((s) => !q || s.name.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (selected.has(b.id) - selected.has(a.id)) || a.name.localeCompare(b.name)), [data, q]) // eslint-disable-line
  if (loading) return <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner />Loading apps…</div>
  if (data?.error) return <Callout tone="warning">{data.error}</Callout>
  const toggle = (id) => onChange(selected.has(id) ? value.filter((v) => v !== id) : [...value, id])
  return (
    <div>
      <div className="relative mb-3">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input className="input pl-9" placeholder="Search apps…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="grid max-h-80 grid-cols-2 gap-2 overflow-y-auto pr-1 sm:grid-cols-3">
        {list.map((s) => (
          <button type="button" key={s.id} onClick={() => toggle(s.id)}
            className={cx('flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition',
              selected.has(s.id) ? 'border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200' : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800')}>
            {s.icon_svg ? <img alt="" className="h-4 w-4 dark:invert" src={`data:image/svg+xml;base64,${s.icon_svg}`} /> : <span className="h-4 w-4" />}
            <span className="truncate">{s.name}</span>
          </button>
        ))}
      </div>
      <p className="help mt-2">{value.length} selected. Red means blocked.</p>
    </div>
  )
}

/** Add a domain to an app in the catalog, so it counts towards that app's time. */
export function AssignDomainModal({ domain, onClose, onDone }) {
  const toast = useToast()
  const { data } = useApi(domain ? '/services' : null)
  const [sid, setSid] = useState('')
  const [suffix, setSuffix] = useState('')
  const [busy, setBusy] = useState(false)
  const suggestions = useMemo(() => {
    if (!domain) return []
    const parts = domain.split('.')
    const out = []
    for (let i = 0; i < parts.length - 1; i++) out.push(parts.slice(i).join('.'))
    return out
  }, [domain])
  if (!domain) return null
  const pattern = suffix || suggestions[Math.max(0, suggestions.length - 2)] || domain
  const save = async () => {
    setBusy(true)
    try {
      await api(`/services/${sid}/domains`, { method: 'POST', body: { domain: pattern } })
      toast(`${pattern} now counts as ${data.services.find((s) => String(s.id) === String(sid))?.name}`)
      onDone?.()
      onClose()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Modal open onClose={onClose} title="Assign to an app" description={domain}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!sid} loading={busy} onClick={save}>Assign</Button></>}>
      <div className="space-y-4">
        <Field label="App">
          <Select value={sid} onChange={setSid} options={[{ value: '', label: 'Choose an app…' }, ...(data?.services || []).map((s) => ({ value: String(s.id), label: `${s.name} (${s.category})` }))]} />
        </Field>
        <Field label="Match" help="Choosing the shorter address also covers its sub-addresses.">
          <Select value={pattern} onChange={setSuffix} options={suggestions.map((s) => ({ value: s, label: s }))} />
        </Field>
        <p className="help">Need a new app? Add it under <b>Apps &amp; categories</b>.</p>
      </div>
    </Modal>
  )
}
