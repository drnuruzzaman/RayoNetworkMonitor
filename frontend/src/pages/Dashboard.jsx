import { Link, useNavigate } from 'react-router-dom'
import { Bell, Clock, Globe, PauseCircle, Radar, Wifi } from 'lucide-react'
import { api, useApi } from '../api'
import DeviceIcon from '../components/DeviceIcon'
import ScreenTime from '../components/ScreenTime'
import PauseButton from '../components/PauseButton'
import { SetupCheckBanner } from '../components/SetupCheck'
import { Button, Callout, Card, EmptyState, ErrorState, Loading, PageHeader, StatCard, StatusDot, useToast } from '../components/ui'
import { duration, number, timeAgo } from '../lib/format'

const LEVEL_DOT = { error: 'bg-red-500', warning: 'bg-amber-500', success: 'bg-emerald-500', info: 'bg-brand-500' }

export default function Dashboard() {
  const toast = useToast()
  const nav = useNavigate()
  const { data, error, loading, reload } = useApi('/dashboard', { refresh: 15000 })
  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  const { counts, usage, online, alerts, adguard, queries, scan } = data

  const scanNow = async () => {
    try { const r = await api('/system/scan', { method: 'POST' }); toast(`Scan finished: ${r.found ?? 0} devices online`); reload() } catch (e) { toast(e.message, 'error') }
  }

  return (
    <>
      <PageHeader
        title="Overview"
        description={scan?.last_run ? `Last network scan ${timeAgo(scan.last_run)}` : 'Waiting for the first network scan…'}
        actions={<Button variant="secondary" icon={Radar} onClick={scanNow}>Scan now</Button>}
      />

      {!adguard.enabled && (
        <Callout tone="info" className="mb-6" title="Turn on activity tracking"
          action={<Link to="/settings/adguard"><Button size="sm">Set up</Button></Link>}>
          You can see which devices are connected. Connect AdGuard Home to also see which apps they use and pause their internet.
        </Callout>
      )}
      {adguard.enabled && <SetupCheckBanner />}
      {adguard.enabled && adguard.ok === false && (
        <Callout tone="error" className="mb-6" title="Can't reach AdGuard Home" action={<Link to="/system"><Button size="sm" variant="secondary">Details</Button></Link>}>
          {adguard.error}
        </Callout>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="In use now" value={`${counts.in_use ?? 0}`} hint={`${counts.online} connected · ${counts.total} known${counts.new_24h ? ` · ${counts.new_24h} new today` : ''}`} icon={Wifi} tone="green" />
        <StatCard label="Screen time today" value={duration(usage.total_seconds)} hint="Time devices were actually in use" icon={Clock} />
        <StatCard label="Lookups today" value={number(queries.total)} hint={`${number(queries.blocked)} blocked`} icon={Globe} tone="violet" />
        <StatCard label="Paused devices" value={counts.paused} hint={counts.paused ? 'Internet currently blocked' : 'Everyone is online'} icon={PauseCircle} tone={counts.paused ? 'red' : 'amber'} />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2"><ScreenTime /></div>
        <Card title="Recent alerts" actions={<Link to="/alerts" className="link text-sm">View all</Link>} bodyClass="">
          {alerts.length === 0 ? <EmptyState icon={Bell} title="All quiet" /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {alerts.map((a) => (
                <li key={a.id} className="flex gap-3 px-5 py-3">
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${LEVEL_DOT[a.level] || LEVEL_DOT.info}`} />
                  <div className="min-w-0">
                    <p className="truncate text-sm">{a.title}</p>
                    <p className="text-xs text-slate-500">{timeAgo(a.ts)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-6">
        <Card title="Connected now" subtitle={`${online.length} device${online.length === 1 ? '' : 's'}${counts.in_use != null ? `, ${counts.in_use} in use` : ''}`}
          actions={<Link to="/devices" className="link text-sm">All devices</Link>} bodyClass="">
          {online.length === 0 ? <EmptyState icon={Wifi} title="No devices online" description="Run a scan, or wait for the next automatic one." /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {online.map((d) => (
                <li key={d.id} className="flex cursor-pointer items-center gap-4 px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => nav(`/devices/${d.id}`)}>
                  <DeviceIcon type={d.type} online paused={d.paused} inUse={d.in_use} />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 truncate text-sm font-medium">{d.display_name}{d.owner && <span className="text-xs font-normal text-slate-400">{d.owner}</span>}</p>
                    <p className="truncate text-xs text-slate-500">
                      {d.top?.length ? d.top.map((t) => `${t.service} ${duration(t.seconds)}`).join(' · ') : <span className="font-mono">{d.ip}</span>}
                    </p>
                  </div>
                  <span className="hidden sm:block"><StatusDot online paused={d.paused} inUse={d.in_use} /></span>
                  <span className="hidden w-14 text-right text-sm tabular-nums text-slate-500 md:block">{d.today_seconds ? duration(d.today_seconds) : ''}</span>
                  <PauseButton device={d} onChange={reload} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  )
}
