import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, KeyRound, Network, Radar, Router, ShieldCheck } from 'lucide-react'
import { api } from '../api'
import AdGuardConnect from '../components/AdGuardConnect'
import DeviceIcon from '../components/DeviceIcon'
import { AdGuardInstallGuide, DnsGuide } from '../components/Guides'
import { Button, Callout, Field, Select, Spinner, cx, useToast } from '../components/ui'
import { AuthShell } from './Login'

const STEPS = [
  { key: 'password', label: 'Admin password', icon: KeyRound },
  { key: 'network', label: 'Your network', icon: Network },
  { key: 'adguard', label: 'Activity tracking', icon: ShieldCheck },
  { key: 'dns', label: 'Connect devices', icon: Router },
]

function Stepper({ index }) {
  return (
    <ol className="mb-6 grid grid-cols-4 gap-2">
      {STEPS.map((s, i) => (
        <li key={s.key} className="flex flex-col items-center gap-1.5 text-center">
          <span className={cx('flex h-9 w-9 items-center justify-center rounded-full border-2 transition',
            i < index ? 'border-brand-600 bg-brand-600 text-white' : i === index ? 'border-brand-600 bg-white text-brand-600 dark:bg-slate-900' : 'border-slate-200 bg-white text-slate-400 dark:border-slate-700 dark:bg-slate-900')}>
            {i < index ? <Check className="h-4 w-4" /> : <s.icon className="h-4 w-4" />}
          </span>
          <span className={cx('hidden text-xs font-medium sm:block', i <= index ? 'text-slate-800 dark:text-slate-200' : 'text-slate-400')}>{s.label}</span>
        </li>
      ))}
    </ol>
  )
}

function PasswordStep({ status, onNext }) {
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (!status?.is_local) {
    return <Callout tone="warning" title="Finish setup on the PC">For security, the first admin password has to be created on the PC running HomeNet. Open <b>http://localhost:8090</b> there.</Callout>
  }
  const submit = async (e) => {
    e.preventDefault()
    if (pw.length < 8) return setError('Use at least 8 characters.')
    if (pw !== pw2) return setError("The passwords don't match.")
    setBusy(true)
    try { await api('/setup/password', { method: 'POST', body: { password: pw } }); onNext() } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-slate-600 dark:text-slate-400">This password protects the dashboard. Anyone who has it can pause devices and change settings, so keep it to the grown-ups.</p>
      <Field label="Create a password"><input className="input" type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></Field>
      <Field label="Confirm password" error={error}><input className="input" type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></Field>
      <div className="flex justify-end"><Button type="submit" loading={busy} icon={ArrowRight}>Continue</Button></div>
    </form>
  )
}

function NetworkStep({ onNext, onBack }) {
  const toast = useToast()
  const [ifaces, setIfaces] = useState(null)
  const [choice, setChoice] = useState('auto')
  const [scan, setScan] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/system/interfaces').then((d) => setIfaces(d.interfaces)).catch((e) => toast(e.message, 'error')) }, [toast])
  const chosen = choice === 'auto' ? ifaces?.[0] : ifaces?.find((i) => i.alias === choice)

  const runScan = async () => {
    setBusy(true)
    try {
      await api('/settings', { method: 'PUT', body: { scan_interface: choice } })
      await api('/system/scan', { method: 'POST' })
      setScan((await api('/devices')).devices)
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">
      {!ifaces ? <div className="flex items-center gap-2 text-sm text-slate-500"><Spinner />Looking at your network adapters…</div> : (
        <>
          <Field label="Network adapter" help="The connection this PC uses for your home Wi-Fi or Ethernet.">
            <Select value={choice} onChange={setChoice} options={[{ value: 'auto', label: `Automatic (${ifaces[0]?.alias || 'none found'})` }, ...ifaces.map((i) => ({ value: i.alias, label: `${i.alias}: ${i.ip}` }))]} />
          </Field>
          {chosen && (
            <div className="grid grid-cols-3 gap-3 rounded-lg bg-slate-50 p-4 text-sm dark:bg-slate-800/50">
              <div><p className="text-xs text-slate-500">This PC</p><p className="font-mono font-medium">{chosen.ip}</p></div>
              <div><p className="text-xs text-slate-500">Router</p><p className="font-mono font-medium">{chosen.gateway || '—'}</p></div>
              <div><p className="text-xs text-slate-500">Range</p><p className="font-mono font-medium">{chosen.network}</p></div>
            </div>
          )}
          <Button variant="secondary" icon={Radar} loading={busy} onClick={runScan}>{scan ? 'Scan again' : 'Scan my network now'}</Button>
          {scan && (
            <div>
              <p className="mb-2 text-sm font-medium">Found {scan.length} device{scan.length === 1 ? '' : 's'}</p>
              <ul className="max-h-56 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                {scan.map((d) => (
                  <li key={d.id} className="flex items-center gap-3 px-3 py-2">
                    <DeviceIcon type={d.type} online={d.is_online} size="sm" />
                    <span className="flex-1 truncate text-sm">{d.display_name}{d.is_self && <span className="ml-2 text-xs text-slate-400">(this PC)</span>}</span>
                    <span className="font-mono text-xs text-slate-500">{d.ip}</span>
                  </li>
                ))}
              </ul>
              <p className="help mt-2">Phones that are asleep may not show up yet. They'll appear as they wake up.</p>
            </div>
          )}
        </>
      )}
      <div className="flex justify-between">
        <Button variant="ghost" icon={ArrowLeft} onClick={onBack} disabled>Back</Button>
        <Button icon={ArrowRight} onClick={onNext} disabled={!ifaces?.length}>Continue</Button>
      </div>
    </div>
  )
}

function AdGuardStep({ onNext, onBack }) {
  const [connected, setConnected] = useState(false)
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600 dark:text-slate-400">
        To see <b>which apps and websites</b> each device uses (and to pause or block them), HomeNet works with <b>AdGuard Home</b>, a free DNS server that runs on this PC.
      </p>
      <AdGuardInstallGuide />
      <div className="border-t border-slate-200 pt-5 dark:border-slate-800">
        <AdGuardConnect onSaved={() => setConnected(true)} />
      </div>
      <div className="flex justify-between">
        <Button variant="ghost" icon={ArrowLeft} onClick={onBack}>Back</Button>
        <Button variant={connected ? 'primary' : 'secondary'} icon={ArrowRight} onClick={onNext}>{connected ? 'Continue' : 'Skip for now'}</Button>
      </div>
    </div>
  )
}

function DnsStep({ onBack, onFinish }) {
  const [iface, setIface] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/system/status').then((s) => setIface(s.status.scan.interface)).catch(() => {}) }, [])
  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-600 dark:text-slate-400">Last step: tell your devices to use this PC for DNS, so their activity flows through AdGuard Home.</p>
      <DnsGuide pcIp={iface?.ip} gateway={iface?.gateway} />
      <div className="flex justify-between">
        <Button variant="ghost" icon={ArrowLeft} onClick={onBack}>Back</Button>
        <Button icon={Check} loading={busy} onClick={async () => { setBusy(true); await api('/setup/complete', { method: 'POST' }); onFinish() }}>Finish setup</Button>
      </div>
    </div>
  )
}

export default function Setup({ status, passwordSet, onDone }) {
  const [step, setStep] = useState(passwordSet ? 1 : 0)
  const s = STEPS[step]
  return (
    <AuthShell title="Set up HomeNet" subtitle="A few quick steps and you'll see everything on your network" wide={step >= 1}>
      <div className="mx-auto w-full" style={{ maxWidth: step >= 2 ? 760 : 560 }}>
        <Stepper index={step} />
        <div className="card p-6">
          <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold"><s.icon className="h-5 w-5 text-brand-600" />{s.label}</h2>
          {step === 0 && <PasswordStep status={status} onNext={() => setStep(1)} />}
          {step === 1 && <NetworkStep onNext={() => setStep(2)} onBack={() => {}} />}
          {step === 2 && <AdGuardStep onNext={() => setStep(3)} onBack={() => setStep(1)} />}
          {step === 3 && <DnsStep onBack={() => setStep(2)} onFinish={onDone} />}
        </div>
      </div>
    </AuthShell>
  )
}
