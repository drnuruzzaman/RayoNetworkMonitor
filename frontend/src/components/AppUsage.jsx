import { useState } from 'react'
import { Ban, ChevronLeft, ChevronRight, Hourglass, Pencil, ShieldCheck } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, useApi } from '../api'
import { serverToday } from '../lib/servertime'
import { LimitModal, fmtLimitMinutes } from './Limits'
import { Button, Callout, ConfirmModal, Modal, Segmented, Spinner, cx, useToast } from './ui'
import { categoryColor, clock, duration } from '../lib/format'

const pad2 = (n) => String(n).padStart(2, '0')
const iso = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
function shift(dateStr, days) {
  const d = new Date(`${dateStr}T12:00:00`)
  d.setDate(d.getDate() + days)
  return iso(d)
}
const dayLabel = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
const axisMin = (v) => (v >= 60 ? `${+(v / 60).toFixed(v % 60 ? 1 : 0)}h` : `${Math.round(v)}m`)

function Tip({ active, payload, period, color }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium">{period === 'day' ? `${row.label}:00 – ${pad2((Number(row.label) + 1) % 24)}:00` : row.date}</p>
      <p className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300"><span className="h-2 w-2 rounded-full" style={{ background: color }} />{duration(row.seconds)}</p>
    </div>
  )
}

/**
 * Popup for one app on one device (or all devices): when it was used, hour by hour (Day) or day by day (Week),
 * the exact times it was open, and a button to add or edit its daily time limit.
 */
export default function AppUsageModal({ app, deviceId, initialPeriod = 'day', initialDate, onClose }) {
  const [period, setPeriod] = useState(initialPeriod)
  const [date, setDate] = useState(initialDate || serverToday())
  const [limitEditing, setLimitEditing] = useState(null)
  const known = app.service_id != null // older HomeNet (before restart) doesn't send app ids
  const q = known ? `/usage/screentime?period=${period}&date=${date}&service_id=${app.service_id}${deviceId ? `&device_id=${deviceId}` : ''}` : null
  const { data, loading } = useApi(q)
  const limits = useApi(deviceId ? `/limits?device_id=${deviceId}` : null)
  const color = categoryColor(app.category)

  const sid = String(app.service_id)
  const rows = (data?.buckets || []).map((b) => ({ label: b.label, date: b.date, seconds: b.apps?.[sid] || 0, minutes: (b.apps?.[sid] || 0) / 60 }))
  const total = rows.reduce((s, r) => s + r.seconds, 0)
  const daysUsed = rows.filter((r) => r.seconds > 0).length
  const busiest = rows.reduce((m, r) => (r.seconds > (m?.seconds || 0) ? r : m), null)
  const periods = data?.app?.periods || []
  const limit = (limits.data?.limits || []).find((l) => l.target_type === 'app' && String(l.target) === sid)
  const usedToday = limit?.usage?.find((u) => u.device_id === deviceId)?.used_seconds

  // Always-block this app on this device (same as Controls → Always block these apps, "Yours" apps).
  const dev = useApi(deviceId ? `/devices/${deviceId}` : null)
  const controls = dev.data?.controls
  const blocked = !!controls?.blocked_apps?.map(String).includes(sid)
  const [confirmBlock, setConfirmBlock] = useState(false)
  const toast = useToast()
  const setBlocked = async (on) => {
    const ids = new Set((controls.blocked_apps || []).map(Number))
    if (on) ids.add(Number(sid)); else ids.delete(Number(sid))
    try {
      await api(`/devices/${deviceId}/controls`, { method: 'PUT', body: { ...controls, blocked_apps: [...ids] } })
      toast(on ? `${app.service} is now blocked on this device` : `${app.service} unblocked on this device`)
      setConfirmBlock(false)
      dev.reload()
    } catch (e) { toast(e.message, 'error') }
  }
  const deviceName = dev.data?.display_name || 'this device'

  // The limit editor and the block confirmation replace this popup while open, then come back to it.
  if (confirmBlock) {
    return (
      <ConfirmModal open danger title={`Block ${app.service} on ${deviceName}?`} confirmLabel={`Block ${app.service}`}
        message={`${app.service} will be blocked on ${deviceName} all day, every day, until you unblock it. `
          + 'It applies within about 30 seconds. You can unblock it from this window or from the Controls tab.'}
        onClose={() => setConfirmBlock(false)} onConfirm={() => setBlocked(true)} />
    )
  }
  if (limitEditing) {
    return (
      <LimitModal limit={limitEditing} device={{ id: deviceId }} onClose={() => setLimitEditing(null)}
        onSaved={() => limits.reload()} />
    )
  }

  return (
    <Modal open onClose={onClose} size="lg"
      title={<span className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ background: color }} />{app.service}</span>}
      description={`${app.category} · ${deviceId ? 'time on this device' : 'all devices'}, only while someone was actually using it`}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Close</Button>
        {deviceId && known && controls && (blocked
          ? <Button variant="secondary" icon={ShieldCheck} onClick={() => setBlocked(false)}>Unblock</Button>
          : <Button variant="pink" icon={Ban} onClick={() => setConfirmBlock(true)}>Block</Button>)}
        {deviceId && known && (limit
          ? <Button icon={Pencil} onClick={() => setLimitEditing(limit)}>Edit limit ({fmtLimitMinutes(limit.minutes)}/day)</Button>
          : <Button icon={Hourglass} onClick={() => setLimitEditing({ target_type: 'app', target: sid, target_name: app.service })}>Add limit</Button>)}
      </>}>
      <div className="space-y-5">
        {blocked && (
          <Callout tone="error" title={`Blocked on ${deviceName}`}>
            {app.service} is always blocked on this device. Unblock it here or under Controls → Always block these apps.
          </Callout>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Segmented value={period} onChange={setPeriod} options={[{ value: 'day', label: 'Day' }, { value: 'week', label: 'Week' }]} />
          <div className="flex items-center gap-1">
            <button className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" onClick={() => setDate(shift(date, period === 'week' ? -7 : -1))} aria-label="Previous"><ChevronLeft className="h-4 w-4" /></button>
            <span className="min-w-[8rem] text-center text-sm font-medium">{data?.label || '…'}</span>
            <button className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 disabled:opacity-30 dark:hover:bg-slate-800" disabled={data?.is_current}
              onClick={() => setDate(shift(date, period === 'week' ? 7 : 1))} aria-label="Next"><ChevronRight className="h-4 w-4" /></button>
          </div>
        </div>

        {!known ? <p className="py-6 text-sm text-slate-500">Restart HomeNet to see app details.</p>
          : !data ? <div className="flex items-center gap-2 py-10 text-sm text-slate-500"><Spinner />Loading…</div> : (
          <>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <p className="text-xs text-slate-500">{period === 'day' ? 'Total' : 'This week'}</p>
                <p className="text-2xl font-semibold tracking-tight">{duration(total)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">{period === 'day' ? 'Busiest hour' : 'Daily average'}</p>
                <p className="text-lg font-semibold">{period === 'day'
                  ? (busiest ? `${busiest.label}:00` : '—')
                  : duration(daysUsed ? total / daysUsed : 0)}</p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Time limit</p>
                <p className="text-lg font-semibold">{limit ? `${fmtLimitMinutes(limit.minutes)}/day` : <span className="text-slate-400">None</span>}</p>
                {limit && usedToday != null && <p className="text-xs text-slate-500">{duration(usedToday)} used today</p>}
              </div>
            </div>

            <div className={cx(loading && 'opacity-60')}>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={rows} margin={{ top: 8, right: 4, left: -18, bottom: 0 }}
                  onClick={(e) => { if (period === 'week' && e?.activePayload?.[0]) { setPeriod('day'); setDate(e.activePayload[0].payload.date) } }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} interval={period === 'day' ? 5 : 0} />
                  <YAxis tickLine={false} axisLine={false} allowDecimals={false} width={52} tickFormatter={axisMin} />
                  <Tooltip content={<Tip period={period} color={color} />} cursor={{ fill: 'rgba(59,102,245,0.06)' }} />
                  <Bar dataKey="minutes" fill={color} radius={[4, 4, 0, 0]} maxBarSize={period === 'day' ? 14 : 34}
                    cursor={period === 'week' ? 'pointer' : undefined} />
                </BarChart>
              </ResponsiveContainer>
              {period === 'week' && <p className="text-center text-xs text-slate-400">Click a day to see it hour by hour</p>}
            </div>

            <div className="border-t border-slate-100 pt-4 dark:border-slate-800">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">When it was used</p>
              {periods.length === 0 ? <p className="text-sm text-slate-500">Not used in this period.</p> : (
                <ul className="max-h-56 divide-y divide-slate-100 overflow-y-auto pr-1 dark:divide-slate-800">
                  {periods.map((p) => (
                    <li key={p.start} className="flex items-center justify-between gap-3 py-1.5 text-sm">
                      <span className="tabular-nums">
                        {period === 'week' && <span className="mr-2 text-slate-500">{dayLabel(p.start)}</span>}
                        {clock(p.start)} – {clock(p.end)}
                      </span>
                      <span className="tabular-nums text-slate-500">{p.seconds < 60 ? '< 1m' : duration(p.seconds)}</span>
                    </li>
                  ))}
                </ul>
              )}
              {periods.length > 0 && <p className="help mt-2">Times {app.service} was open while the device was in use. Running alongside other apps, so these can add up to more than the total above.</p>}
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}
