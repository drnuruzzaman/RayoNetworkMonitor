import { useState } from 'react'
import { CheckCircle2, PlugZap } from 'lucide-react'
import { api } from '../api'
import { Button, Callout, Field, useToast } from './ui'

/** Connection form for AdGuard Home: test, then save and turn it on. */
export default function AdGuardConnect({ initial = {}, hasPassword, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({ adguard_url: initial.adguard_url || 'http://127.0.0.1:3000', adguard_username: initial.adguard_username || '', adguard_password: '' })
  const [test, setTest] = useState(null)
  const [busy, setBusy] = useState('')
  const set = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setTest(null) }

  const runTest = async () => {
    setBusy('test')
    try {
      setTest(await api('/settings/adguard/test', { method: 'POST', body: { url: form.adguard_url, username: form.adguard_username, password: form.adguard_password } }))
    } finally { setBusy('') }
  }

  const save = async () => {
    setBusy('save')
    try {
      await api('/settings', { method: 'PUT', body: { ...form, adguard_enabled: true } })
      toast('AdGuard Home connected')
      onSaved?.()
    } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }

  return (
    <div className="space-y-4">
      <Field label="AdGuard Home address" help="Where AdGuard's admin page opens.">
        <input className="input" value={form.adguard_url} onChange={set('adguard_url')} placeholder="http://127.0.0.1:3000" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Username"><input className="input" value={form.adguard_username} onChange={set('adguard_username')} autoComplete="off" /></Field>
        <Field label="Password" help={hasPassword ? 'Leave blank to keep the saved password.' : undefined}>
          <input className="input" type="password" value={form.adguard_password} onChange={set('adguard_password')} autoComplete="new-password" />
        </Field>
      </div>
      {test && (test.ok
        ? <Callout tone="success" title={`Connected to AdGuard Home ${test.version || ''}`}>DNS is listening on {(test.dns_addresses || []).join(', ') || 'this PC'}.</Callout>
        : <Callout tone="error" title="Couldn't connect">{test.error}</Callout>)}
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" icon={PlugZap} loading={busy === 'test'} onClick={runTest}>Test connection</Button>
        <Button icon={CheckCircle2} loading={busy === 'save'} disabled={!test?.ok} onClick={save}>Save &amp; turn on</Button>
      </div>
    </div>
  )
}
