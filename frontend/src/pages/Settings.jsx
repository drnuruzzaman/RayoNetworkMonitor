import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Bell, BookOpen, Database, Factory, KeyRound, Network, PlugZap, RotateCw, Save, ShieldCheck, SlidersHorizontal } from 'lucide-react'
import { api, useApi } from '../api'
import { AdGuardInstallGuide, DnsGuide } from '../components/Guides'
import { Button, Callout, Card, ErrorState, Field, Loading, PageHeader, Select, Tabs, Toggle, useToast } from '../components/ui'
import { dateTime, number } from '../lib/format'

const GROUPS = [
  { value: 'general', label: 'General', icon: SlidersHorizontal, title: 'Dashboard access' },
  { value: 'network', label: 'Network scanning', icon: Network, title: 'Device discovery' },
  { value: 'adguard', label: 'AdGuard Home', icon: ShieldCheck, title: 'AdGuard Home connection' },
  { value: 'usage', label: 'Usage & history', icon: Database, title: 'Usage tracking & data retention' },
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
    </>
  )
}
