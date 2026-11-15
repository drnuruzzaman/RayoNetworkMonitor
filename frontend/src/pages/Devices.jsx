import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, ChevronUp, ChevronsUpDown, MoreHorizontal, Pencil, Radar, Search, ShieldQuestion, Wifi } from 'lucide-react'
import { api, useApi } from '../api'
import DeviceIcon, { TYPE_LABELS } from '../components/DeviceIcon'
import EditDeviceModal from '../components/EditDeviceModal'
import { LastUsedCell, UsingCell } from '../components/LiveNow'
import PauseButton from '../components/PauseButton'
import { RefreshControl, RefreshScope, useAutoRefresh } from '../components/RefreshControl'
import { Badge, Button, Card, CopyButton, EmptyState, ErrorState, Loading, Menu, PageHeader, Segmented, Select, StatusDot, cx, useToast } from '../components/ui'
import { duration, timeAgo } from '../lib/format'

// Sort keys for the table headers. Each returns a value where "bigger" sorts later in ascending order.
const ipNum = (ip) => (ip && /^\d+\.\d+\.\d+\.\d+$/.test(ip) ? ip.split('.').reduce((n, o) => n * 256 + Number(o), 0) : null)
// Mirrors the status badge: Offline < Paused < Idle < Online (not tracked) < In use.
const statusRank = (d) => (d.paused ? 1 : !d.is_online ? 0 : d.in_use === true ? 4 : d.in_use === false ? 2 : 3)
const SORTS = {
  device: (d) => (d.display_name || '').toLowerCase(),
  status: statusRank,
  // In use first (newest app first), then idle devices by when they were last used.
  using: (d) => (d._live ? 1e12 + (d._live.apps?.[0]?.since ?? d._live.in_use_since) : d._last?.at ?? null),
  address: (d) => ipNum(d.ip),
  today: (d) => d.today_seconds || 0,
}
// First click on a column: names and addresses A→Z, status and time "most first".
const FIRST_DIR = { device: 'asc', status: 'desc', using: 'desc', address: 'asc', today: 'desc' }
const SORT_STORE = 'homenet.devices.sort'

function loadSort() {
  try {
    const s = JSON.parse(localStorage.getItem(SORT_STORE))
    if (s && SORTS[s.key] && (s.dir === 'asc' || s.dir === 'desc')) return s
  } catch { /* storage unavailable */ }
  return null
}

function SortTh({ col, sort, onSort, className, children }) {
  const active = sort?.key === col
  const Icon = !active ? ChevronsUpDown : sort.dir === 'asc' ? ChevronUp : ChevronDown
  return (
    <th className={cx('th', className)} aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(col)}
        className={cx('-mx-1 inline-flex items-center gap-1 rounded px-1 uppercase tracking-wide hover:text-slate-900 dark:hover:text-white',
          active && 'text-slate-900 dark:text-white')}>
        {children}<Icon className={cx('h-3.5 w-3.5', !active && 'opacity-40')} />
      </button>
    </th>
  )
}

export default function Devices() {
  const refresh = useAutoRefresh('devices', 60000)
  return <RefreshScope state={refresh}><DevicesView refresh={refresh} /></RefreshScope>
}

function DevicesView({ refresh }) {
  const nav = useNavigate()
  const toast = useToast()
  const { data, error, loading, reload } = useApi('/devices')
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('all')
  const [type, setType] = useState('all')
  const [editing, setEditing] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [sort, setSort] = useState(loadSort) // null = the server's order

  // Click: sort by that column; click again: reverse; third click: back to the default order.
  const onSort = (key) => setSort((s) => {
    const next = s?.key !== key ? { key, dir: FIRST_DIR[key] } : s.dir === FIRST_DIR[key] ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : null
    try { next ? localStorage.setItem(SORT_STORE, JSON.stringify(next)) : localStorage.removeItem(SORT_STORE) } catch { /* ignore */ }
    return next
  })

  // Who is using what right now (same data as the device page's "Using … since" line); follows the page refresh.
  const liveData = useApi('/live').data
  const liveById = useMemo(() => Object.fromEntries((liveData?.in_use || []).map((l) => [l.id, l])), [liveData])
  const devices = useMemo(() => (data?.devices || []).map((d) => ({ ...d, _live: liveById[d.id], _last: liveData?.last_used?.[d.id] })),
    [data, liveById, liveData])
  const filtered = useMemo(() => devices.filter((d) => {
    if (status === 'online' && !d.is_online) return false
    if (status === 'offline' && d.is_online) return false
    if (status === 'paused' && !d.paused) return false
    if (status === 'new' && d.trusted) return false
    if (type !== 'all' && d.type !== type) return false
    if (q) {
      const s = `${d.display_name} ${d.owner || ''} ${d.ip || ''} ${d.mac} ${d.vendor || ''} ${d.hostname || ''}`.toLowerCase()
      if (!s.includes(q.toLowerCase())) return false
    }
    return true
  }), [devices, q, status, type])

  const rows = useMemo(() => {
    if (!sort) return filtered
    const key = SORTS[sort.key]
    const sign = sort.dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const x = key(a), y = key(b)
      if (x == null || y == null) return x == null && y == null ? 0 : x == null ? 1 : -1 // blanks always last
      const c = typeof x === 'string' ? x.localeCompare(y, undefined, { numeric: true }) : x - y
      return c * sign || (a.display_name || '').localeCompare(b.display_name || '', undefined, { numeric: true })
    })
  }, [filtered, sort])

  const scan = async () => {
    setScanning(true)
    try { const r = await api('/system/scan', { method: 'POST' }); toast(`Scan finished: ${r.found ?? 0} online${r.new ? `, ${r.new} new` : ''}`); reload() } catch (e) { toast(e.message, 'error') } finally { setScanning(false) }
  }

  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  const counts = { online: devices.filter((d) => d.is_online).length, paused: devices.filter((d) => d.paused).length, new: devices.filter((d) => !d.trusted).length }

  return (
    <>
      <PageHeader title="Devices" description="Everything that has connected to your network. Click a device to see its activity and controls."
        actions={<>
          <RefreshControl state={refresh} />
          <Button variant="secondary" icon={Radar} loading={scanning} onClick={scan}>Scan now</Button>
        </>} />

      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center">
        <div className="relative min-w-[16rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input className="input pl-9" placeholder="Search by name, owner, IP, MAC or maker…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Segmented value={status} onChange={setStatus} options={[
          { value: 'all', label: `All ${devices.length}` }, { value: 'online', label: `Online ${counts.online}` },
          { value: 'paused', label: `Paused ${counts.paused}` }, { value: 'new', label: `Unreviewed ${counts.new}` }, { value: 'offline', label: 'Offline' },
        ]} />
        <Select className="sm:w-44" value={type} onChange={setType} options={[{ value: 'all', label: 'All types' }, ...Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))]} />
        </div>
      </div>

      <Card bodyClass="">
        {filtered.length === 0 ? (
          <EmptyState icon={devices.length ? Search : Wifi} title={devices.length ? 'No devices match' : 'No devices found yet'}
            description={devices.length ? 'Try a different search or filter.' : 'Run a scan to discover what\'s on your network.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-100 dark:divide-slate-800">
              <thead className="bg-slate-50/70 dark:bg-slate-800/30">
                <tr>
                  <SortTh col="device" sort={sort} onSort={onSort}>Device</SortTh>
                  <SortTh col="status" sort={sort} onSort={onSort}>Status</SortTh>
                  <SortTh col="using" sort={sort} onSort={onSort} className="hidden md:table-cell">Using now</SortTh>
                  <SortTh col="today" sort={sort} onSort={onSort} className="hidden lg:table-cell">Today</SortTh>
                  <SortTh col="address" sort={sort} onSort={onSort} className="hidden xl:table-cell">Address</SortTh>
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {rows.map((d) => (
                  <tr key={d.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => nav(`/devices/${d.id}`)}>
                    <td className="td">
                      <div className="flex items-center gap-3">
                        <DeviceIcon type={d.type} online={d.is_online} paused={d.paused} inUse={d.in_use} />
                        <div className="min-w-0">
                          <p className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
                            <span className="truncate">{d.display_name}</span>
                            {d.is_self && <Badge color="blue">This PC</Badge>}
                            {d.is_gateway && <Badge color="violet">Router</Badge>}
                            {!d.trusted && !d.is_self && <Badge color="amber"><ShieldQuestion className="h-3 w-3" />Unreviewed</Badge>}
                          </p>
                          <p className="truncate text-xs text-slate-500">{[d.owner, TYPE_LABELS[d.type], d.vendor].filter(Boolean).join(' · ') || '—'}</p>
                        </div>
                      </div>
                    </td>
                    <td className="td">
                      <StatusDot online={d.is_online} paused={d.paused} inUse={d.in_use} />
                      <p className="mt-1 text-xs text-slate-500">{d.paused && d.block_reasons?.length ? d.block_reasons[0] : `${d.is_online ? 'Seen' : 'Last seen'} ${timeAgo(d.last_seen)}`}</p>
                    </td>
                    <td className="td hidden max-w-[16rem] md:table-cell">
                      {d.paused ? <span className="text-slate-400">—</span>
                        : d._live ? <UsingCell live={d._live} last={d._last} />
                        : <LastUsedCell last={d._last} />}
                    </td>
                    <td className="td hidden lg:table-cell">
                      {d.today_seconds ? (
                        <>
                          <p className="font-medium tabular-nums">{duration(d.today_seconds)}</p>
                          <p className="max-w-[14rem] truncate text-xs text-slate-500">{d.top.map((t) => t.service).join(', ')}</p>
                        </>
                      ) : <span className="text-slate-400">—</span>}
                    </td>
                    <td className="td hidden xl:table-cell">
                      <p className="flex items-center font-mono text-xs">{d.ip || '—'}<CopyButton value={d.ip} label="IP address" /></p>
                      <p className="flex items-center font-mono text-xs text-slate-400">{d.mac}{d.is_private_mac && <span title="Private / randomised address" className="ml-1 text-amber-500">•</span>}<CopyButton value={d.mac} label="MAC address" /></p>
                    </td>
                    <td className="td text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-2">
                        <PauseButton device={d} onChange={reload} />
                        <Menu trigger={<Button size="sm" variant="ghost" aria-label="More"><MoreHorizontal className="h-4 w-4" /></Button>}
                          items={[{ label: 'Rename / edit', icon: Pencil, onClick: () => setEditing(d) }, { label: 'Open details', onClick: () => nav(`/devices/${d.id}`) }]} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <EditDeviceModal device={editing} open={!!editing} onClose={() => setEditing(null)} onSaved={reload} />
    </>
  )
}
