import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity as ActivityIcon, Globe } from 'lucide-react'
import { useApi } from '../api'
import { CategoryDonut, UsageTimeline } from '../components/Charts'
import { AssignDomainModal } from '../components/Pickers'
import AppUsageModal from '../components/AppUsage'
import { BarList, Callout, Card, EmptyState, ErrorState, Loading, PageHeader, Segmented, Select, Toggle } from '../components/ui'
import { RANGE_OPTIONS, categoryColor, clock, duration, number } from '../lib/format'

export default function Activity() {
  const nav = useNavigate()
  const [range, setRange] = useState('today')
  const [device, setDevice] = useState('')
  const [system, setSystem] = useState(false)
  const [assign, setAssign] = useState(null)
  const [openApp, setOpenApp] = useState(null) // { service_id, service, category, deviceId }
  const qs = `range=${range}${device ? `&device_id=${device}` : ''}`
  const { data, error, loading, reload } = useApi(`/usage/summary?${qs}&include_system=${system}`, { refresh: 60000 })
  const sessions = useApi(`/usage/sessions?${qs}`)
  const unmapped = useApi(`/usage/domains?${qs}&unmapped=true&limit=25`)
  const devs = useApi('/devices')

  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  const isDaily = range === '7d' || range === '30d'

  return (
    <>
      <PageHeader title="Activity" description="Estimated time spent in each app, based on each device's internet lookups." />
      <div className="mb-6 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <Segmented value={range} onChange={setRange} options={RANGE_OPTIONS} />
        <div className="flex flex-wrap items-center gap-4">
          <Select className="w-64" value={device} onChange={setDevice}
            options={[{ value: '', label: 'All devices' }, ...(devs.data?.devices || []).map((d) => ({ value: String(d.id), label: d.display_name }))]} />
          <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300"><Toggle checked={system} onChange={setSystem} />Include background traffic</label>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={`${duration(data.total_seconds)} total`} subtitle={isDaily ? 'Minutes per day' : 'Minutes per hour'}>
          <UsageTimeline data={data.timeline} bar={isDaily} height={260} />
        </Card>
        <Card title="By category">
          {data.categories.length ? <CategoryDonut data={data.categories} height={150} /> : <EmptyState icon={ActivityIcon} title="No activity" />}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title="Apps">
          {data.services.length ? (
            <BarList items={data.services.slice(0, 15).map((s) => ({ key: s.service_id, label: s.service, sub: `${s.sessions} session${s.sessions === 1 ? '' : 's'}`, value: s.seconds, category: s.category }))}
              format={duration} colorFor={(i) => categoryColor(i.category)}
              onClick={(i) => i.key && setOpenApp({ service_id: i.key, service: i.label, category: i.category, deviceId: device ? Number(device) : null })} />
          ) : <p className="text-sm text-slate-500">No app activity in this period.</p>}
        </Card>
        <Card title="Devices">
          {data.devices.length ? (
            <BarList items={data.devices.map((d) => ({ key: d.device_id, id: d.device_id, label: d.device, sub: d.top.map((t) => t.service).join(', '), value: d.seconds }))}
              format={duration} onClick={(i) => nav(`/devices/${i.id}`)} />
          ) : <p className="text-sm text-slate-500">No device activity in this period.</p>}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-3" title="Recent sessions" bodyClass="max-h-[28rem] overflow-y-auto">
          {!sessions.data?.sessions?.length ? <EmptyState icon={ActivityIcon} title="No sessions" /> : (
            <table className="min-w-full text-sm">
              <thead className="sticky top-0 bg-white dark:bg-slate-900"><tr><th className="th">App</th><th className="th">Device</th><th className="th">When</th><th className="th text-right">Time</th></tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {sessions.data.sessions.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="td"><span className="mr-2 inline-block h-2 w-2 rounded-full" style={{ background: categoryColor(s.category) }} />{s.service_id
                      ? <button type="button" className="text-left font-medium hover:underline" title={`See when ${s.service} was used`} onClick={() => setOpenApp({ service_id: s.service_id, service: s.service, category: s.category, deviceId: s.device_id })}>{s.service}</button>
                      : s.service}</td>
                    <td className="td text-slate-600 dark:text-slate-300">{s.device}</td>
                    <td className="td text-slate-500">{isDaily && new Date(s.start * 1000).toLocaleDateString([], { weekday: 'short', day: 'numeric' }) + ' '}{clock(s.start)}–{clock(s.end)}</td>
                    <td className="td text-right tabular-nums">{duration(s.seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card className="lg:col-span-2" title="Unrecognised addresses" subtitle="Assign them to an app to improve the estimates" bodyClass="max-h-[28rem] overflow-y-auto">
          {!unmapped.data?.domains?.length ? <EmptyState icon={Globe} title="Nothing to review" /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {unmapped.data.domains.map((d) => (
                <li key={d.domain} className="flex items-center gap-3 px-5 py-2">
                  <span className="min-w-0 flex-1 truncate font-mono text-xs" title={d.domain}>{d.domain}</span>
                  <span className="text-xs tabular-nums text-slate-400">{number(d.queries)}</span>
                  <button className="link text-xs" onClick={() => setAssign(d.domain)}>Assign</button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Callout tone="info" className="mt-6">
        Times are estimates. HomeNet sees which services a device looks up (e.g. youtube.com), not what's on screen. Apps that refresh in the background can add a little extra time.
      </Callout>
      {assign && <AssignDomainModal domain={assign} onClose={() => setAssign(null)} onDone={() => { unmapped.reload(); reload() }} />}
      {openApp && <AppUsageModal app={openApp} deviceId={openApp.deviceId} initialPeriod={isDaily ? 'week' : 'day'} onClose={() => setOpenApp(null)} />}
    </>
  )
}
