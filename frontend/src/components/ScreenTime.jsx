import { useState } from 'react'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useApi } from '../api'
import { serverToday } from '../lib/servertime'
import AppUsageModal from './AppUsage'
import { Card, Segmented, Spinner, cx } from './ui'
import { categoryColor, duration } from '../lib/format'

const pad2 = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}` // local date, not UTC
function shift(dateStr, days) {
  const d = new Date(`${dateStr}T12:00:00`)
  d.setDate(d.getDate() + days)
  return iso(d)
}

function StackTip({ active, payload, label, period }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const items = payload.filter((p) => p.value > 0).sort((a, b) => b.value - a.value)
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="mb-1 font-medium">{period === 'day' ? `${label}:00` : row.date} · {duration(row.seconds)}</p>
      {items.map((p) => (
        <p key={p.dataKey} className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
          <span className="h-2 w-2 rounded-full" style={{ background: p.fill }} />{p.dataKey} {duration(p.value)}
        </p>
      ))}
    </div>
  )
}

/** Apple-style Screen Time: Week/Day, bars stacked by category, average and change, top categories, most used apps. */
export default function ScreenTime({ deviceId }) {
  const [period, setPeriod] = useState('day')
  const [date, setDate] = useState(serverToday())
  const [openApp, setOpenApp] = useState(null) // app whose usage popup is open
  const q = `/usage/screentime?period=${period}&date=${date}${deviceId ? `&device_id=${deviceId}` : ''}`
  const { data, loading } = useApi(q)

  const cats = (data?.categories || []).map((c) => c.category)
  const shown = cats.slice(0, 5)
  const rows = (data?.buckets || []).map((b) => {
    const r = { label: b.label, date: b.date, seconds: b.seconds }
    let other = 0
    for (const [c, v] of Object.entries(b.categories)) {
      if (shown.includes(c)) r[c] = v / 60
      else other += v
    }
    if (other) r['More'] = (r['More'] || 0) + other / 60
    return r
  })
  const keys = [...shown, ...(rows.some((r) => r.More) ? ['More'] : [])]
  const headline = period === 'week' ? data?.average_seconds : data?.total_seconds
  // Week: compare daily averages (this week may be partial). Day: compare with the day before.
  const prevBase = data ? (period === 'week' ? data.previous_seconds / 7 : data.previous_seconds) : 0
  const change = data && prevBase > 0 ? Math.round((headline - prevBase) / prevBase * 100) : null
  const avgMin = period === 'week' && data ? data.average_seconds / 60 : null
  const maxApp = Math.max(1, ...(data?.apps || []).map((a) => a.seconds))

  return (
    <Card title="Screen time" subtitle={deviceId ? 'Time someone was actually using this device' : 'All devices, only while someone was actually using them'}
      actions={<Segmented value={period} onChange={(p) => { setPeriod(p); setDate(serverToday()) }} options={[{ value: 'week', label: 'Week' }, { value: 'day', label: 'Day' }]} />}>
      {!data ? <div className="flex items-center gap-2 py-10 text-sm text-slate-500"><Spinner />Loading…</div> : (
        <>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm text-slate-500">{period === 'week' ? 'Daily average' : data.label}</p>
              <p className="text-3xl font-semibold tracking-tight">{duration(headline)}</p>
              {change !== null && (
                <p className={cx('mt-1 flex items-center gap-1 text-xs', change > 0 ? 'text-orange-600' : 'text-emerald-600')}>
                  {change > 0 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
                  {Math.abs(change)}% from {period === 'week' ? 'last week' : 'the day before'}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1">
              <button className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => setDate(shift(date, period === 'week' ? -7 : -1))} aria-label="Previous"><ChevronLeft className="h-4 w-4" /></button>
              <span className="min-w-[8rem] text-center text-sm font-medium">{data.label}</span>
              <button className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800" disabled={data.is_current}
                onClick={() => setDate(shift(date, period === 'week' ? 7 : 1))} aria-label="Next"><ChevronRight className="h-4 w-4" /></button>
            </div>
          </div>

          <div className={cx('mt-4', loading && 'opacity-60')}>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={rows} margin={{ top: 8, right: 4, left: -18, bottom: 0 }}
                onClick={(e) => { if (period === 'week' && e?.activePayload?.[0]) { setPeriod('day'); setDate(e.activePayload[0].payload.date) } }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} interval={period === 'day' ? 5 : 0} />
                <YAxis tickLine={false} axisLine={false} allowDecimals={false} width={52}
                  tickFormatter={(v) => (v >= 60 ? `${+(v / 60).toFixed(v % 60 ? 1 : 0)}h` : `${Math.round(v)}m`)} />
                <Tooltip content={<StackTip period={period} />} cursor={{ fill: 'rgba(59,102,245,0.06)' }} />
                {avgMin > 0 && <ReferenceLine y={avgMin} stroke="#10b981" strokeDasharray="4 4" label={{ value: 'avg', position: 'right', fill: '#10b981', fontSize: 11 }} />}
                {keys.map((k, i) => (
                  <Bar key={k} dataKey={k} stackId="a" fill={k === 'More' ? '#cbd5e1' : categoryColor(k)} maxBarSize={period === 'day' ? 14 : 34}
                    radius={i === keys.length - 1 ? [4, 4, 0, 0] : 0} cursor={period === 'week' ? 'pointer' : undefined} />
                ))}
              </BarChart>
            </ResponsiveContainer>
            {period === 'week' && <p className="text-center text-xs text-slate-400">Click a day to see it hour by hour</p>}
          </div>

          {data.categories.length > 0 && (
            <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-slate-100 pt-4 dark:border-slate-800 sm:grid-cols-3">
              {data.categories.slice(0, 6).map((c) => (
                <div key={c.category}>
                  <p className="text-xs font-medium" style={{ color: categoryColor(c.category) }}>{c.category}</p>
                  <p className="text-sm font-semibold">{duration(c.seconds)}</p>
                </div>
              ))}
            </div>
          )}

          <div className="mt-5 border-t border-slate-100 pt-4 dark:border-slate-800">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Most used <span className="font-normal normal-case tracking-normal text-slate-400">· click an app for details</span></p>
            {data.apps.length === 0 ? <p className="text-sm text-slate-500">No app use in this period.</p> : (
              <ul className="space-y-3">
                {data.apps.slice(0, 10).map((a) => (
                  <li key={a.service}>
                    <button type="button" onClick={() => setOpenApp(a)} title={`See when ${a.service} was used${deviceId ? ' and set a time limit' : ''}`}
                      className="-mx-2 block w-[calc(100%+1rem)] rounded-lg px-2 py-1 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50">
                      <div className="mb-1 flex items-center justify-between text-sm">
                        <span className="flex items-center gap-2 font-medium"><span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(a.category) }} />{a.service}</span>
                        <span className="tabular-nums text-slate-500">{duration(a.seconds)}</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                        <div className="h-full rounded-full" style={{ width: `${Math.max(2, (a.seconds / maxApp) * 100)}%`, background: categoryColor(a.category) }} />
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
      {openApp && <AppUsageModal app={openApp} deviceId={deviceId} initialPeriod={period} initialDate={date} onClose={() => setOpenApp(null)} />}
    </Card>
  )
}
