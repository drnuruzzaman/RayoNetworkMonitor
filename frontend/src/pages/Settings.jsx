import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Bell, BookOpen, Database, Download, Factory, KeyRound, Network, PlugZap, RotateCcw, RotateCw, Save, ShieldCheck, SlidersHorizontal, Sparkles, Upload } from 'lucide-react'
import { api, useApi } from '../api'
import { AdGuardInstallGuide, DnsGuide } from '../components/Guides'
import { Button, Callout, Card, ConfirmModal, ErrorState, Field, Loading, PageHeader, Select, Tabs, Toggle, useToast } from '../components/ui'
import { dateTime, number } from '../lib/format'

const GROUPS = [
  { value: 'general', label: 'General', icon: SlidersHorizontal, title: 'Dashboard access' },
  { value: 'network', label: 'Network scanning', icon: Network, title: 'Device discovery' },
  { value: 'adguard', label: 'AdGuard Home', icon: ShieldCheck, title: 'AdGuard Home connection' },
  { value: 'usage', label: 'Usage & history', icon: Database, title: 'Usage tracking & data retention' },
  { value: 'detection', label: 'App detection', icon: Sparkles, title: 'Automatic app detection' },
  { value: 'alerts', label: 'Alerts', icon: Bell, title: 'Alerts' },
  { value: 'vendor', label: 'Manufacturers', icon: Factory, title: 'Manufacturer lookup' },
  { value: 'security', label: 'Password', icon: KeyRound },
  { value: 'guide', label: 'Setup guide', icon: BookOpen },
]

export function SettingField({ spec, value, onChange, interfaces }) {
  if (spec.type === 'bool') return <Toggle checked={!!value} onChange={onChange} label={spec.label} description={spec.help} />
  let input
  if (spec.type === 'select') input = <Select value={value} onChange={onChange} options={spec.options} />
  else if (spec.type === 'interface') {
    input = <Select value={value} onChange={onChange} options={[{ value: 'auto', label: 'Automatic' }, ...(interfaces || []).map((i) => ({ value: i.alias, label: `${i.alias}: ${i.ip} (${i.network})` }))]} />
  } else {
    input = (
      <input className="input" type={spec.type === 'int' ? 'number' : spec.type === 'password' ? 'password' : 'text'} min={spec.min} max={spec.max}
        value={value ?? ''} onChange={(e) => onChange(spec.type === 'int' ? e.target.value : e.target.value)}
        placeholder={spec.type === 'password' && spec.has_value ? '•••••••• (saved, leave blank to keep)' : undefined} autoComplete="off" />
    )
  }
  return <Field label={<>{spec.label}{spec.restart && <span className="ml-2 text-xs font-normal text-amber-600">needs restart</span>}</>} help={spec.help}>{input}</Field>
}

function RestartBanner({ bind }) {
  const [busy, setBusy] = useState(false)
  const restart = async () => {
    setBusy(true)
    try {
      const r = await api('/system/restart', { method: 'POST' })
      const host = r.host === '127.0.0.1' ? 'localhost' : window.location.hostname
      setTimeout(() => { window.location.href = `${window.location.protocol}//${host}:${r.port}/settings` }, 3500)
    } catch (e) { setBusy(false); alert(e.message) }
  }
  return (
    <Callout tone="warning" className="mb-6" title="Restart needed" action={<Button size="sm" icon={RotateCw} loading={busy} onClick={restart}>Restart now</Button>}>
      Some changes apply after HomeNet restarts.{bind?.host === '127.0.0.1' && ' After restarting you can only open the dashboard on this PC.'}
    </Callout>
  )
}

function PasswordCard() {
  const toast = useToast()
  const [f, setF] = useState({ current: '', new: '', confirm: '' })
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    if (f.new !== f.confirm) return toast("New passwords don't match", 'error')
    setBusy(true)
    try { await api('/settings/password', { method: 'POST', body: { current: f.current, new: f.new } }); toast('Password changed'); setF({ current: '', new: '', confirm: '' }) } catch (err) { toast(err.message, 'error') } finally { setBusy(false) }
  }
  return (
    <Card title="Change admin password" subtitle="Signs out everyone else.">
      <form onSubmit={submit} className="max-w-md space-y-4">
        <Field label="Current password"><input className="input" type="password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></Field>
        <Field label="New password" help="At least 8 characters."><input className="input" type="password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} autoComplete="new-password" /></Field>
        <Field label="Confirm new password"><input className="input" type="password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} autoComplete="new-password" /></Field>
        <Button type="submit" loading={busy}>Change password</Button>
      </form>
    </Card>
  )
}

/** AdGuard tab: HomeNet's VPN list under AdGuard's Filters → DNS blocklists (AdGuard's Blocked services can't be extended). */
function VpnBlocklistCard() {
  const toast = useToast()
  const nav = useNavigate()
  const { data, reload, setData } = useApi('/adguard/vpn-blocklist')
  const [busy, setBusy] = useState('')
  const run = async (key, fn, msg) => {
    setBusy(key)
    try { setData(await fn()); if (msg) toast(msg) } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }
  if (!data) return null
  const toggle = (on) => run('toggle', () => api('/adguard/vpn-blocklist', { method: 'PUT', body: { enabled: on } }),
    on ? 'VPN blocklist is on in AdGuard Home for every device' : 'VPN blocklist switched off in AdGuard Home')
  return (
    <Card className="mt-6" title="Block VPN services (whole network)"
      subtitle={`Appears in AdGuard Home under Filters → DNS blocklists as "${data.name}".`}>
      <div className="max-w-2xl space-y-4">
        {data.error && <Callout tone="warning">{data.error}</Callout>}
        <Toggle checked={data.enabled} onChange={toggle} disabled={!!data.error || busy === 'toggle'}
          label="Block VPN and proxy apps for every device"
          description={`Blocks the ${data.entries} addresses of the apps in the "${data.category}" category of Apps & categories. Add or edit VPN apps there; AdGuard picks up changes within the hour.`} />
        <p className="text-sm text-slate-600 dark:text-slate-300">
          {data.installed
            ? <>In AdGuard: {data.enabled ? 'on' : 'off'}{data.rules_count != null ? `, ${number(data.rules_count)} rules` : ''}{data.last_updated ? `, updated ${dateTime(data.last_updated)}` : ''}.</>
            : 'Not added to AdGuard yet. Switching it on adds it.'}
        </p>
        <Callout tone="info">
          AdGuard's own Filters → Blocked services list is built into AdGuard and can't be extended, so this uses a DNS blocklist instead.
          To block VPNs on one device only, pick them under that device's Controls → Always block these apps.
          Blocking by address stops most VPN apps signing in and finding servers; one that's already connected, or connects straight to an IP address, can get round it.
        </Callout>
        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-5 dark:border-slate-800">
          <Button variant="secondary" icon={RotateCw} disabled={!data.enabled} loading={busy === 'refresh'}
            onClick={() => run('refresh', () => api('/adguard/vpn-blocklist/refresh', { method: 'POST' }), 'AdGuard re-downloaded the VPN list')}>Update now</Button>
          <Button variant="secondary" onClick={() => nav('/apps')}>Edit VPN apps</Button>
          {data.installed && <Button variant="ghost" className="text-red-600" loading={busy === 'remove'}
            onClick={() => run('remove', () => api('/adguard/vpn-blocklist', { method: 'DELETE' }), 'Removed from AdGuard Home')}>Remove from AdGuard</Button>}
          <Button variant="ghost" onClick={reload}>Recheck</Button>
        </div>
      </div>
    </Card>
  )
}

const fmt = (v) => (typeof v === 'boolean' ? (v ? 'On' : 'Off') : v === '' || v == null ? '(empty)' : String(v))

/** General tab: save the current settings as your own defaults, reset to them, or move them via a file. */
function DefaultsCard({ onApplied }) {
  const toast = useToast()
  const { data, reload, setData } = useApi('/settings/defaults')
  const [busy, setBusy] = useState('')
  const [confirm, setConfirm] = useState(null) // 'apply' | 'clear'
  const fileRef = useRef(null)
  if (!data) return null
  const run = async (key, fn) => { setBusy(key); try { await fn() } catch (e) { toast(e.message, 'error') } finally { setBusy('') } }

  const save = () => run('save', async () => { setData(await api('/settings/defaults/save', { method: 'POST' })); toast('Current settings saved as your defaults') })
  const exportFile = () => run('export', async () => {
    const doc = await api('/settings/defaults/export')
    const url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `homenet-settings-${new Date().toISOString().slice(0, 10)}.json` })
    a.click(); URL.revokeObjectURL(url)
  })
  const importFile = (e) => {
    const f = e.target.files?.[0]; e.target.value = ''
    if (!f) return
    run('import', async () => {
      let doc
      try { doc = JSON.parse(await f.text()) } catch { throw new Error("That file isn't valid JSON.") }
      const r = await api('/settings/defaults/import', { method: 'POST', body: doc })
      setData(r)
      toast(`Imported ${r.imported} settings${r.imported_apps ? ` and ${r.imported_apps} apps` : ''} as your defaults${r.skipped.length ? ` (${r.skipped.length} skipped)` : ''}. Use "Reset to defaults" to apply them.`)
    })
  }
  const apply = async () => {
    const r = await api('/settings/defaults/apply', { method: 'POST' })
    setData(r); setConfirm(null); onApplied(r)
    const a = r.apps_changed
    const nApps = a ? a.add.length + a.update.length + a.remove.length : 0
    const parts = [r.changed.length && `${r.changed.length} setting${r.changed.length === 1 ? '' : 's'}`, nApps && `${nApps} app${nApps === 1 ? '' : 's'}`].filter(Boolean)
    toast(parts.length ? `Reset ${parts.join(' and ')}` : 'Already at defaults')
  }
  const clear = async () => { setData(await api('/settings/defaults', { method: 'DELETE' })); setConfirm(null); toast('Your saved defaults were removed. Built-in defaults apply again.') }

  const own = !!data.saved
  const ad = data.apps?.diff
  const appChanges = ad ? ad.add.length + ad.update.length + ad.remove.length : 0
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`
  return (
    <Card className="mt-6" title="Default settings"
      subtitle={own ? `Your own defaults: ${data.count} settings${data.apps ? ` and ${data.apps.count} apps` : ''}, saved ${dateTime(data.saved)}.` : 'Using HomeNet\'s built-in defaults.'}>
      <div className="max-w-2xl space-y-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">
          Save how HomeNet is set up now, including every app in Apps &amp; categories, as the defaults. "Reset to defaults" then brings
          everything back to this, and a new setup that has the saved file in its data folder starts from it. Export downloads settings and
          apps as a file you can import on another PC. The AdGuard password is never included.
        </p>
        <ul className="space-y-1 text-sm">
          <li>{data.differs.length === 0 ? 'All settings match the defaults.' : `${plural(data.differs.length, 'setting')} differ from the ${own ? 'saved' : 'built-in'} defaults.`}</li>
          <li className="text-slate-600 dark:text-slate-300">
            {!data.apps ? 'Apps & categories: not part of the defaults yet (save or import to include them).'
              : appChanges === 0 ? 'Apps & categories match the defaults.'
              : `Apps & categories: ${[ad.add.length && `${ad.add.length} to add back`, ad.update.length && `${ad.update.length} changed`, ad.remove.length && `${ad.remove.length} new since saved`].filter(Boolean).join(', ')}.`}
          </li>
        </ul>
        <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-5 dark:border-slate-800">
          <Button icon={Save} loading={busy === 'save'} onClick={save}>Save current as defaults</Button>
          <Button variant="secondary" icon={RotateCcw} disabled={!data.differs.length && !appChanges} onClick={() => setConfirm('apply')}>Reset to defaults</Button>
          <Button variant="secondary" icon={Download} loading={busy === 'export'} onClick={exportFile}>Export</Button>
          <Button variant="secondary" icon={Upload} loading={busy === 'import'} onClick={() => fileRef.current?.click()}>Import</Button>
          {own && <Button variant="ghost" className="text-red-600" onClick={() => setConfirm('clear')}>Use built-in defaults</Button>}
          <input ref={fileRef} type="file" accept="application/json,.json" className="hidden" onChange={importFile} />
        </div>
      </div>
      <ConfirmModal open={confirm === 'apply'} onClose={() => setConfirm(null)} title="Reset to defaults?" confirmLabel="Reset" danger
        message={<span className="block max-h-80 space-y-3 overflow-y-auto">
          {data.differs.length > 0 && <>
            <span className="block">These settings change to the {own ? 'saved' : 'built-in'} defaults:</span>
            <span className="block space-y-1">
              {data.differs.map((d) => (
                <span key={d.key} className="block text-xs">
                  <b>{d.label}</b>: {fmt(d.current)} → {fmt(d.default)}{d.restart && ' (after restart)'}
                </span>
              ))}
            </span>
          </>}
          {appChanges > 0 && <>
            <span className="block">Apps &amp; categories go back to the saved list:</span>
            {[['Added back', ad.add], ['Restored to saved version', ad.update], ['Removed (with their history)', ad.remove]].map(([label, names]) => names.length > 0 && (
              <span key={label} className="block text-xs"><b>{label} ({names.length}):</b> {names.join(', ')}</span>
            ))}
          </>}
        </span>}
        onConfirm={apply} />
      <ConfirmModal open={confirm === 'clear'} onClose={() => setConfirm(null)} title="Use built-in defaults?" confirmLabel="Remove saved defaults" danger
        message="Your saved defaults are removed and HomeNet's built-in ones are used for future resets. Your current settings don't change."
        onConfirm={clear} />
    </Card>
  )
}

export default function Settings() {
  const { tab: tabParam } = useParams()
  const nav = useNavigate()
  const toast = useToast()
  const tab = GROUPS.some((g) => g.value === tabParam) ? tabParam : 'general'
  const { data, error, loading, reload, setData } = useApi('/settings')
  const sys = useApi('/system/status')
  const [interfaces, setInterfaces] = useState(null)
  const [draft, setDraft] = useState({})
  const [busy, setBusy] = useState('')
  const [restart, setRestart] = useState(false)
  const [test, setTest] = useState(null)

  useEffect(() => { if (tab === 'network' && !interfaces) api('/system/interfaces').then((d) => setInterfaces(d.interfaces)).catch(() => setInterfaces([])) }, [tab, interfaces])
  useEffect(() => { setDraft({}); setTest(null) }, [tab])

  const specs = useMemo(() => (data?.settings || []).filter((s) => s.group === tab), [data, tab])
  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  const valueOf = (s) => (s.key in draft ? draft[s.key] : s.value)
  const dirty = Object.keys(draft).length > 0
  const group = GROUPS.find((g) => g.value === tab)

  const save = async () => {
    setBusy('save')
    try {
      const r = await api('/settings', { method: 'PUT', body: draft })
      setData({ settings: r.settings })
      setDraft({})
      if (r.restart_required) setRestart(true)
      toast(r.changed.length ? 'Settings saved' : 'Nothing changed')
    } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }

  const runTest = async () => {
    setBusy('test')
    try {
      setTest(await api('/settings/adguard/test', { method: 'POST', body: { url: valueOf(specs.find((s) => s.key === 'adguard_url')), username: valueOf(specs.find((s) => s.key === 'adguard_username')), password: draft.adguard_password || '' } }))
    } finally { setBusy('') }
  }

  const updateOui = async () => {
    setBusy('oui')
    try { const r = await api('/system/oui-update', { method: 'POST' }); toast(`Downloaded ${number(r.entries)} manufacturers`); sys.reload() } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }

  const iface = sys.data?.status?.scan?.interface

  return (
    <>
      <PageHeader title="Settings" description="Everything HomeNet does can be changed here. Changes apply straight away unless marked." />
      {restart && <RestartBanner bind={sys.data?.bind} />}
      <Tabs tabs={GROUPS} value={tab} onChange={(v) => nav(`/settings/${v}`)} />

      {tab === 'security' && <PasswordCard />}
      {tab === 'guide' && (
        <div className="space-y-6">
          <Card title="1. Install AdGuard Home" subtitle="Needed for app activity, pausing and blocking"><AdGuardInstallGuide /></Card>
          <Card title="2. Point your devices at this PC" subtitle="So their internet lookups go through AdGuard Home"><DnsGuide pcIp={iface?.ip} gateway={iface?.gateway} /></Card>
        </div>
      )}

      {group?.title && (
        <Card title={group.title}>
          <div className="max-w-2xl space-y-6">
            {tab === 'adguard' && (
              <Callout tone="info">New to AdGuard Home? See the <button className="link" onClick={() => nav('/settings/guide')}>setup guide</button> for installation steps.</Callout>
            )}
            {specs.map((s) => (
              <SettingField key={s.key} spec={s} value={valueOf(s)} interfaces={interfaces}
                onChange={(v) => { setDraft((d) => ({ ...d, [s.key]: v })); setTest(null) }} />
            ))}
            {tab === 'adguard' && test && (test.ok
              ? <Callout tone="success" title={`Connected to AdGuard Home ${test.version || ''}`}>Protection is {test.protection_enabled ? 'on' : 'off'}.</Callout>
              : <Callout tone="error" title="Couldn't connect">{test.error}</Callout>)}
            {tab === 'vendor' && (
              <div className="rounded-lg bg-slate-50 p-4 text-sm dark:bg-slate-800/50">
                <p>{sys.data?.oui_entries ? <>{number(sys.data.oui_entries)} manufacturers loaded{sys.data.oui_updated ? `, updated ${dateTime(sys.data.oui_updated)}` : ''}.</> : 'No manufacturer list downloaded yet.'}</p>
                <p className="help">Phones that use a private address don't reveal their maker.</p>
                <Button className="mt-3" variant="secondary" size="sm" loading={busy === 'oui'} onClick={updateOui}>Download / update now</Button>
              </div>
            )}
            <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-5 dark:border-slate-800">
              <Button icon={Save} disabled={!dirty} loading={busy === 'save'} onClick={save}>Save changes</Button>
              {dirty && <Button variant="secondary" onClick={() => setDraft({})}>Discard</Button>}
              {tab === 'adguard' && <Button variant="secondary" icon={PlugZap} loading={busy === 'test'} onClick={runTest}>Test connection</Button>}
            </div>
          </div>
        </Card>
      )}
      {tab === 'adguard' && <VpnBlocklistCard />}
      {tab === 'general' && (
        <DefaultsCard onApplied={(r) => { setData({ settings: r.settings }); setDraft({}); if (r.restart_required) setRestart(true) }} />
      )}
    </>
  )
}
