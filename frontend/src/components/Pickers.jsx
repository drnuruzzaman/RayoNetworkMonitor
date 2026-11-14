import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { api, useApi } from '../api'
import SearchSelect from './SearchSelect'
import { Button, Callout, Field, Modal, Select, Spinner, useToast } from './ui'

const svcIcon = (s) => (s.icon_svg
  ? <img alt="" className="h-4 w-4 dark:invert" src={`data:image/svg+xml;base64,${s.icon_svg}`} />
  : <span className="h-4 w-4" />)

/** Blocked apps as removable tags, plus a search box: click it to see AdGuard's app list, pick one to block. */
export function ServicePicker({ value, onChange }) {
  const { data, loading } = useApi('/adguard/services')
  const byId = useMemo(() => Object.fromEntries((data?.services || []).map((s) => [s.id, s])), [data])
  const options = useMemo(() => (data?.services || []).slice().sort((a, b) => a.name.localeCompare(b.name))
    .map((s) => ({ value: s.id, label: s.name, icon: svcIcon(s) })), [data])
  if (loading) return <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner />Loading apps…</div>
  if (data?.error) return <Callout tone="warning">{data.error}</Callout>
  return (
    <div className="space-y-3">
      {value.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {value.map((id) => (
            <span key={id} className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 py-1 pl-2.5 pr-1 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
              {byId[id] ? svcIcon(byId[id]) : null}{byId[id]?.name || id}
              <button type="button" onClick={() => onChange(value.filter((v) => v !== id))} aria-label={`Unblock ${byId[id]?.name || id}`}
                className="rounded p-0.5 text-red-500 hover:bg-red-100 dark:hover:bg-red-900/50"><X className="h-3.5 w-3.5" /></button>
            </span>
          ))}
        </div>
      ) : <p className="text-sm text-slate-500">No apps blocked.</p>}
      <SearchSelect options={options} exclude={value} placeholder="Search apps to block… (click to see the list)"
        onSelect={(id) => onChange([...value, id])} />
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
