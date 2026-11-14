import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, HelpCircle, RefreshCw, Stethoscope, XCircle } from 'lucide-react'
import { api, useApi } from '../api'
import { Badge, Button, Card, Spinner, cx } from './ui'
import { timeAgo } from '../lib/format'

const ICON = {
  ok: [CheckCircle2, 'text-emerald-500'],
  warn: [AlertTriangle, 'text-amber-500'],
  error: [XCircle, 'text-red-500'],
  unknown: [HelpCircle, 'text-slate-400'],
}

function useDiagnostics() {
  const q = useApi('/system/diagnostics')
  const [busy, setBusy] = useState(false)
  const recheck = async () => {
    setBusy(true)
    try { q.setData(await api('/system/diagnostics?refresh=true')) } finally { setBusy(false) }
  }
  return { ...q, busy, recheck }
}

function CheckRow({ c, compact }) {
  const [Icon, cls] = ICON[c.status] || ICON.unknown
  return (
    <li className="flex gap-3 px-5 py-3.5">
      <Icon className={cx('mt-0.5 h-5 w-5 shrink-0', cls)} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{c.title}</p>
        {!compact && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{c.detail}</p>}
        {c.fix && c.status !== 'ok' && (
          <p className="mt-1.5 text-sm text-slate-700 dark:text-slate-300"><span className="font-medium">Fix: </span>{c.fix}
            {c.link && <> <Link to={c.link} className="link">Open guide</Link></>}</p>
        )}
      </div>
    </li>
  )
}

/** Full checklist for the System page. */
export function SetupCheckCard() {
  const { data, loading, busy, recheck } = useDiagnostics()
  return (
    <Card bodyClass=""
      title={<span className="flex items-center gap-2"><Stethoscope className="h-4 w-4" />Setup check</span>}
      subtitle={data ? `Checked ${timeAgo(data.checked)}` : 'Looks for anything stopping devices from being tracked'}
      actions={<>
        {data && (data.problems ? <Badge color="amber">{data.problems} to fix</Badge> : <Badge color="green" dot>All good</Badge>)}
        <Button size="sm" variant="secondary" icon={RefreshCw} loading={busy} onClick={recheck}>Re-check</Button>
      </>}>
      {loading && !data ? <div className="flex items-center gap-2 px-5 py-6 text-sm text-slate-500"><Spinner />Checking your setup… (takes a few seconds)</div> : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">{data?.checks.map((c) => <CheckRow key={c.id} c={c} />)}</ul>
      )}
    </Card>
  )
}

/** Compact banner for the Overview page. Only shows when something needs fixing. */
export function SetupCheckBanner() {
  const { data, busy, recheck } = useDiagnostics()
  const problems = (data?.checks || []).filter((c) => c.status === 'error' || c.status === 'warn')
  if (!problems.length) return null
  const worst = problems.some((c) => c.status === 'error')
  return (
    <div className={cx('card mb-6 overflow-hidden border-l-4', worst ? 'border-l-red-500' : 'border-l-amber-500')}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <Stethoscope className="h-4 w-4" />{problems.length === 1 ? '1 thing' : `${problems.length} things`} to fix before every device is tracked
        </p>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" icon={RefreshCw} loading={busy} onClick={recheck}>Re-check</Button>
          <Link to="/system"><Button size="sm" variant="secondary">All checks</Button></Link>
        </div>
      </div>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">{problems.map((c) => <CheckRow key={c.id} c={c} compact />)}</ul>
    </div>
  )
}
