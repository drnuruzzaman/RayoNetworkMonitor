import { useState } from 'react'
import { Lock, Wifi } from 'lucide-react'
import { api } from '../api'
import { Button, Field } from '../components/ui'

export function AuthShell({ children, title, subtitle, wide }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-50 via-white to-brand-50 px-4 py-10 dark:from-slate-950 dark:via-slate-950 dark:to-brand-950/40">
      <div className={wide ? 'w-full max-w-3xl' : 'w-full max-w-md'}>
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 text-white shadow-lg shadow-brand-600/30"><Wifi className="h-6 w-6" /></span>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
        </div>
        {children}
      </div>
    </div>
  )
}

export default function Login({ onDone }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await api('/auth/login', { method: 'POST', body: { password } })
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Welcome back" subtitle="Sign in to manage your home network">
      <form onSubmit={submit} className="card space-y-5 p-6">
        <Field label="Admin password" error={error}>
          <input type="password" className="input" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </Field>
        <Button type="submit" className="w-full" size="lg" loading={busy} icon={Lock}>Sign in</Button>
      </form>
    </AuthShell>
  )
}
