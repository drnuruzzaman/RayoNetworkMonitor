import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { MoreHorizontal, Pencil, Radar, Search, ShieldQuestion, Wifi } from 'lucide-react'
import { api, useApi } from '../api'
import DeviceIcon, { TYPE_LABELS } from '../components/DeviceIcon'
import EditDeviceModal from '../components/EditDeviceModal'
import PauseButton from '../components/PauseButton'
import { RefreshControl, RefreshScope, useAutoRefresh } from '../components/RefreshControl'
import { Badge, Button, Card, EmptyState, ErrorState, Loading, Menu, PageHeader, Segmented, Select, StatusDot, useToast } from '../components/ui'
import { duration, timeAgo } from '../lib/format'

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

  const devices = data?.devices || []
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
                  <th className="th">Device</th>
                  <th className="th">Status</th>
                  <th className="th hidden xl:table-cell">Address</th>
                  <th className="th hidden lg:table-cell">Today</th>
                  <th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.map((d) => (
                  <tr key={d.id} className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40" onClick={() => nav(`/devices/${d.id}`)}>
                    <td className="td">
                      <div className="flex items-center gap-3">
                        <DeviceIcon type={d.type} online={d.is_online} paused={d.paused} />
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
                      <StatusDot online={d.is_online} paused={d.paused} />
                      <p className="mt-1 text-xs text-slate-500">{d.paused && d.block_reasons?.length ? d.block_reasons[0] : `${d.is_online ? 'Seen' : 'Last seen'} ${timeAgo(d.last_seen)}`}</p>
                    </td>
                    <td className="td hidden xl:table-cell">
                      <p className="font-mono text-xs">{d.ip || '—'}</p>
                      <p className="font-mono text-xs text-slate-400">{d.mac}{d.is_private_mac && <span title="Private / randomised address" className="ml-1 text-amber-500">•</span>}</p>
                    </td>
                    <td className="td hidden lg:table-cell">
                      {d.today_seconds ? (
                        <>
                          <p className="font-medium tabular-nums">{duration(d.today_seconds)}</p>
                          <p className="max-w-[14rem] truncate text-xs text-slate-500">{d.top.map((t) => t.service).join(', ')}</p>
                        </>
                      ) : <span className="text-slate-400">—</span>}
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
