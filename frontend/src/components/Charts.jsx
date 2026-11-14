import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { categoryColor, duration } from '../lib/format'

function TipBox({ active, payload, label, unit = 'min' }) {
  if (!active || !payload?.length) return null
  const v = payload[0].value
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-800">
      <p className="font-medium text-slate-700 dark:text-slate-200">{label || payload[0].payload.label || payload[0].name}</p>
      <p className="text-slate-500">{unit === 'min' ? duration(v * 60) : unit === 'sec' ? duration(v) : v}</p>
    </div>
  )
}

export function UsageTimeline({ data, height = 240, bar }) {
  const Chart = bar ? BarChart : AreaChart
  return (
    <ResponsiveContainer width="100%" height={height}>
      <Chart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="usageFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#3b66f5" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#3b66f5" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="label" tickLine={false} axisLine={false} interval="preserveStartEnd" minTickGap={24} />
        <YAxis tickLine={false} axisLine={false} allowDecimals={false} width={52}
          tickFormatter={(v) => (v >= 60 ? `${+(v / 60).toFixed(v % 60 ? 1 : 0)}h` : `${v}m`)} />
        <Tooltip content={<TipBox />} cursor={{ fill: 'rgba(59,102,245,0.06)' }} />
        {bar
          ? <Bar dataKey="minutes" fill="#3b66f5" radius={[4, 4, 0, 0]} maxBarSize={36} />
          : <Area type="monotoneX" dataKey="minutes" stroke="#3b66f5" strokeWidth={2} fill="url(#usageFill)" />}
      </Chart>
    </ResponsiveContainer>
  )
}

export function CategoryDonut({ data, height = 200 }) {
  const total = data.reduce((a, b) => a + b.seconds, 0)
  return (
    <div className="flex flex-col items-center gap-5">
      <div className="relative" style={{ width: height, height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="seconds" nameKey="category" innerRadius="62%" outerRadius="100%" paddingAngle={2} stroke="none">
              {data.map((d) => <Cell key={d.category} fill={categoryColor(d.category)} />)}
            </Pie>
            <Tooltip content={<TipBox unit="sec" />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-semibold">{duration(total)}</span>
          <span className="text-xs text-slate-500">total</span>
        </div>
      </div>
      <ul className="w-full flex-1 space-y-2 text-sm">
        {data.map((d) => (
          <li key={d.category} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(d.category) }} />
            <span className="flex-1 text-slate-700 dark:text-slate-300">{d.category}</span>
            <span className="tabular-nums text-slate-500">{duration(d.seconds)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Horizontal strip showing when a device was online in the given window. */
export function PresenceStrip({ sessions, inUse = [], start, end }) {
  const span = end - start
  const hours = [0, 6, 12, 18, 24]
  const fmt = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <div>
      <div className="relative h-8 overflow-hidden rounded-md bg-slate-100 dark:bg-slate-800">
        {inUse.map((s, i) => (
          <div key={`u${i}`} className="absolute bottom-0 z-10 h-full rounded-sm bg-emerald-600"
            style={{ left: `${((s.start - start) / span) * 100}%`, width: `${Math.max(0.4, ((s.end - s.start) / span) * 100)}%` }}
            title={`In use ${fmt(s.start)} – ${fmt(s.end)}`} />
        ))}
        {sessions.map((s, i) => (
          <div key={i} className="absolute inset-y-0 rounded-sm bg-orange-300/70 dark:bg-orange-700/60"
            style={{ left: `${((s.start - start) / span) * 100}%`, width: `${Math.max(0.4, ((s.end - s.start) / span) * 100)}%` }}
            title={`${new Date(s.start * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} – ${s.open ? 'now' : new Date(s.end * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`} />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">{hours.map((h) => <span key={h}>{String(h).padStart(2, '0')}:00</span>)}</div>
      <div className="mt-2 flex gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-emerald-600" />In use</span>
        <span className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-orange-300/70 dark:bg-orange-700/60" />Connected (idle or locked)</span>
      </div>
    </div>
  )
}
