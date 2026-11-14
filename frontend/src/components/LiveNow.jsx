import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Radio } from 'lucide-react'
import { useApi } from '../api'
import DeviceIcon from './DeviceIcon'
import { Badge, Card, EmptyState, cx } from './ui'
import { categoryColor, clock } from '../lib/format'

function useTick(ms = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

/** "23m 10s" style running duration. */
export function running(sec) {
  sec = Math.max(0, Math.round(sec))
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${String(s).padStart(2, '0')}s`
  return `${s}s`
}

/** One line: "Using YouTube since 14:02 · 23m 10s" (ticks every second). */
export function UsingNow({ live, className }) {
  const now = useTick()
  const app = live?.apps?.[0]
  if (!live) return null
  return (
    <p className={cx('flex flex-wrap items-center gap-x-1.5 text-sm', className)}>
      <span className="relative flex h-2 w-2"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" /><span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" /></span>
      {app ? <>Using <b style={{ color: categoryColor(app.category) }}>{app.service === 'Website' && app.domain ? app.domain : app.service}</b> since {clock(app.since)}
        <span className="tabular-nums text-slate-500">· {running(now - app.since)}</span></>
        : <>In use since {clock(live.in_use_since)} <span className="tabular-nums text-slate-500">· {running(now - live.in_use_since)}</span></>}
      {live.apps?.length > 1 && (
        <span className="text-slate-500">· also {live.apps.slice(1).map((a, i) => (
          <span key={a.service_id}>{i > 0 && ', '}<b style={{ color: categoryColor(a.category) }}>{a.service === 'Website' && a.domain ? a.domain : a.service}</b></span>
        ))}</span>
      )}
    </p>
  )
}

/** Overview panel: who is using what right now, since when. */
export default function LiveNow() {
  const nav = useNavigate()
  const now = useTick()
  const { data } = useApi('/live', { refresh: 15000 })
  if (!data) return null
  return (
    <Card title={<span className="flex items-center gap-2"><Radio className="h-4 w-4 text-emerald-500" />Live now</span>}
      subtitle="What each device is being used for right now, worked out from its internet activity. Updates every 15 seconds."
      bodyClass="">
      {!data.enabled ? (
        <EmptyState icon={Radio} title="Live activity is off" description="Needs AdGuard Home and 'Only count time when someone is actually using the device' in Settings." />
      ) : data.in_use.length === 0 ? (
        <EmptyState icon={Radio} title="Nobody is using a device right now" description={data.idle.length ? `${data.idle.length} connected device${data.idle.length === 1 ? ' is' : 's are'} idle or locked.` : undefined} />
      ) : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {data.in_use.map((d) => {
            const app = d.apps[0]
            return (
              <li key={d.id} className="flex cursor-pointer items-center gap-4 px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => nav(`/devices/${d.id}`)}>
                <DeviceIcon type={d.type} online inUse paused={d.paused} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{d.display_name}{d.owner && <span className="ml-2 text-xs font-normal text-slate-400">{d.owner}</span>}</p>
                  <p className="truncate text-xs text-slate-500">
                    In use since {clock(d.in_use_since)}{d.apps.length > 1 && <> · also {d.apps.slice(1).map((a) => a.service).join(', ')}</>}
                  </p>
                </div>
                <div className="text-right">
                  {app ? (
                    <>
                      <p className="flex items-center justify-end gap-1.5 text-sm font-semibold">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(app.category) }} />{app.service}
                      </p>
                      <p className="text-xs tabular-nums text-slate-500">since {clock(app.since)} · {running(now - app.since)}</p>
                    </>
                  ) : <p className="text-xs text-slate-500">Browsing / other</p>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {data.enabled && data.idle.length > 0 && data.in_use.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-5 py-3 text-xs text-slate-500 dark:border-slate-800">
          Idle / locked:{data.idle.map((d) => <Badge key={d.id} color="orange">{d.display_name}</Badge>)}
        </div>
      )}
    </Card>
  )
}
