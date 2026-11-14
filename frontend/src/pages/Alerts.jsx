import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Bell, CheckCheck, CheckCircle2, Info, Trash2, XCircle } from 'lucide-react'
import { api, useApi } from '../api'
import { Button, Card, ConfirmModal, EmptyState, ErrorState, Loading, PageHeader, cx } from '../components/ui'
import { dateTime, timeAgo } from '../lib/format'

const ICON = {
  error: [XCircle, 'text-red-500 bg-red-50 dark:bg-red-950/50'],
  warning: [AlertTriangle, 'text-amber-500 bg-amber-50 dark:bg-amber-950/50'],
  success: [CheckCircle2, 'text-emerald-500 bg-emerald-50 dark:bg-emerald-950/50'],
  info: [Info, 'text-brand-500 bg-brand-50 dark:bg-brand-950/50'],
}

export default function Alerts() {
  const { data, error, loading, reload } = useApi('/alerts', { refresh: 30000 })
  const [clear, setClear] = useState(false)
  useEffect(() => {
    if (data?.unread) {
      const t = setTimeout(() => api('/alerts/read-all', { method: 'POST' }), 1500)
      return () => clearTimeout(t)
    }
  }, [data?.unread])
  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />

  return (
    <>
      <PageHeader title="Alerts" description="New devices, pauses and system events. Choose which alerts you get in Settings."
        actions={<>
          <Button variant="secondary" icon={CheckCheck} onClick={async () => { await api('/alerts/read-all', { method: 'POST' }); reload() }}>Mark all read</Button>
          <Button variant="danger-soft" icon={Trash2} onClick={() => setClear(true)} disabled={!data.alerts.length}>Clear</Button>
        </>} />
      <Card bodyClass="">
        {data.alerts.length === 0 ? <EmptyState icon={Bell} title="No alerts" description="You'll see new devices and important events here." /> : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.alerts.map((a) => {
              const [Icon, cls] = ICON[a.level] || ICON.info
              return (
                <li key={a.id} className={cx('flex gap-4 px-5 py-4', !a.read && 'bg-brand-50/40 dark:bg-brand-950/20')}>
                  <span className={cx('flex h-9 w-9 shrink-0 items-center justify-center rounded-full', cls)}><Icon className="h-4 w-4" /></span>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{a.title}</p>
                    {a.message && <p className="mt-0.5 text-sm text-slate-500">{a.message}</p>}
                    <p className="mt-1 text-xs text-slate-400" title={dateTime(a.ts)}>{timeAgo(a.ts)}
                      {a.device_id && <> · <Link className="link" to={`/devices/${a.device_id}`}>View device</Link></>}</p>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
      <ConfirmModal open={clear} onClose={() => setClear(false)} danger title="Clear all alerts?" confirmLabel="Clear"
        message="This removes every alert from the list." onConfirm={async () => { await api('/alerts', { method: 'DELETE' }); setClear(false); reload() }} />
    </>
  )
}
