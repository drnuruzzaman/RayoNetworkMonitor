import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Activity as ActivityIcon, ArrowLeft, CalendarClock, Globe, LayoutGrid, Pencil, Plus, ShieldCheck, Trash2 } from 'lucide-react'
import { api, useApi } from '../api'
import { PresenceStrip, UsageTimeline } from '../components/Charts'
import DeviceIcon, { TYPE_LABELS } from '../components/DeviceIcon'
import EditDeviceModal from '../components/EditDeviceModal'
import PauseButton from '../components/PauseButton'
import BlockReasons from '../components/BlockReasons'
import ScreenTime from '../components/ScreenTime'
import AppUsageModal from '../components/AppUsage'
import LimitsCard from '../components/Limits'
import { LastUsedLine, UsingNow } from '../components/LiveNow'
import { RefreshControl, RefreshScope, useAutoRefresh } from '../components/RefreshControl'
import { AssignDomainModal, OWN_APP, ServicePicker } from '../components/Pickers'
import {
  Badge, BarList, Button, Callout, Card, ConfirmModal, CopyButton, EmptyState, ErrorState, Loading, Segmented, StatusDot, Tabs, Toggle, useToast,
} from '../components/ui'
import { DAYS, RANGE_OPTIONS, categoryColor, clock, dateTime, duration, number, timeAgo } from '../lib/format'
import { dayDiff } from '../lib/servertime'
import { RuleModal } from './Schedules'

function Info({ label, children, mono }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="shrink-0 text-xs text-slate-500">{label}</dt>
      <dd className={`min-w-0 break-all text-right text-sm ${mono ? 'font-mono text-xs' : ''}`}>{children || '—'}</dd>
    </div>
  )
}

function OverviewTab({ device }) {
  const { data: pres } = useApi(`/devices/${device.id}/presence?range=today`)
  const start = new Date(); start.setHours(0, 0, 0, 0)
  const s = start.getTime() / 1000
  const onlineSec = (pres?.sessions || []).reduce((a, x) => a + (x.end - x.start), 0)
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <Card title="Connected today" subtitle={pres ? `Connected ${duration(onlineSec)} · actually in use ${duration(pres.in_use_seconds || 0)}` : ''}>
          <PresenceStrip sessions={pres?.sessions || []} inUse={pres?.in_use || []} start={s} end={s + 86400} />
        </Card>
        <ScreenTime deviceId={device.id} />
      </div>
      <div className="space-y-6">
        <Card title="Details">
          <dl className="-my-2 divide-y divide-slate-100 dark:divide-slate-800">
            <Info label="IP address" mono>{device.ip && <span className="inline-flex items-center">{device.ip}<CopyButton value={device.ip} label="IP address" /></span>}</Info>
            <Info label="MAC address" mono>{device.mac && <span className="inline-flex items-center">{device.mac}<CopyButton value={device.mac} label="MAC address" /></span>}</Info>
            <Info label="Maker">{device.vendor || (device.is_private_mac ? 'Hidden (private address)' : null)}</Info>
            <Info label="Reported name">{device.hostname}</Info>
            <Info label="First seen">{dateTime(device.first_seen)}</Info>
            <Info label="Last seen">{timeAgo(device.last_seen)}</Info>
            <Info label="Last internet activity">{timeAgo(device.last_dns)}</Info>
            <Info label="Type">{TYPE_LABELS[device.type]}</Info>
          </dl>
          {device.background_hosts?.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
              <p className="text-sm font-medium">Background chatter (ignored)</p>
              <p className="mb-2 text-xs text-slate-500">Addresses this device contacts all day whether or not anyone is using it. Learned from the last 7 days.</p>
              <ul className="space-y-1">
                {device.background_hosts.map((h) => (
                  <li key={h.domain} className="flex justify-between gap-3 text-xs">
                    <span className="truncate font-mono">{h.domain}</span>
                    <span className="shrink-0 tabular-nums text-slate-500">{Math.round(h.share * 100)}% of the time</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {device.notes && <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800/50">{device.notes}</p>}
        </Card>
      </div>
    </div>
  )
}

function ActivityTab({ device }) {
  const [range, setRange] = useState('today')
  const [assign, setAssign] = useState(null)
  const [openApp, setOpenApp] = useState(null)
  const sessions = useApi(`/usage/sessions?range=${range}&device_id=${device.id}`)
  const [showBackground, setShowBackground] = useState(false)
  const domains = useApi(`/usage/domains?range=${range}&device_id=${device.id}&limit=60&in_use=${!showBackground}&sort=recent`)
  return (
    <div className="space-y-6">
      <Segmented value={range} onChange={setRange} options={RANGE_OPTIONS} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Sessions" subtitle="When each app was in use (estimated)" bodyClass="max-h-[32rem] overflow-y-auto">
          {!sessions.data?.sessions?.length ? <EmptyState icon={ActivityIcon} title="No sessions" /> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {sessions.data.sessions.map((x) => (
                <li key={x.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: categoryColor(x.category) }} />
                  {x.service_id
                    ? <button type="button" className="flex-1 truncate text-left font-medium hover:underline" title={`See when ${x.service} was used`} onClick={() => setOpenApp(x)}>{x.service}</button>
                    : <span className="flex-1 font-medium">{x.service}</span>}
                  <span className="text-xs text-slate-500">{range === 'today' || range === 'yesterday' ? '' : new Date(x.start * 1000).toLocaleDateString([], { weekday: 'short' }) + ' '}{clock(x.start)}–{clock(x.end)}</span>
                  <span className="w-16 text-right tabular-nums text-slate-600 dark:text-slate-300">{duration(x.seconds)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Websites & services" bodyClass="max-h-[32rem] overflow-y-auto"
          subtitle={showBackground ? 'Everything looked up, including background traffic while idle or locked.' : 'What was used while someone was actually using the device.'}
          actions={<label className="flex items-center gap-2 whitespace-nowrap text-xs text-slate-500"><Toggle checked={showBackground} onChange={setShowBackground} />Show background</label>}>
          {!domains.data?.domains?.length ? (
            <EmptyState icon={Globe} title={showBackground ? 'No lookups' : 'Not used in this period'}
              description={showBackground ? 'Activity appears once this device uses AdGuard Home for DNS.' : 'There was only background traffic (e.g. screen locked). Turn on "Show background" to see it.'} />
          ) : (
            <table className="min-w-full text-sm">
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {domains.data.domains.slice().sort((a, b) => (b.last || 0) - (a.last || 0)).map((x) => (
                  <tr key={x.domain}>
                    <td className="px-5 py-2 align-top">
                      <p className="max-w-[16rem] truncate font-mono text-xs" title={x.domain}>{x.domain}</p>
                      {x.last && <p className="mt-0.5 text-[11px] text-slate-500" title={dateTime(x.last)}>Last {dayDiff(x.last) === 0 ? clock(x.last) : dateTime(x.last)} · {timeAgo(x.last)}</p>}
                      <BlockReasons items={x.blocked_by} />
                    </td>
                    <td className="px-2 py-2 align-top">{x.service ? <button type="button" title={`See when ${x.service} was used`} onClick={() => setOpenApp({ service_id: x.service_id, service: x.service, category: x.category })}><Badge color="blue">{x.service}</Badge></button> : <button className="link text-xs" onClick={() => setAssign(x.domain)}>Assign…</button>}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-right align-top tabular-nums text-slate-500" title={x.blocked ? `${x.blocked} of ${x.queries} lookups blocked` : `${x.queries} lookups`}>
                      {number(x.queries)}{x.blocked ? <span className="ml-1 text-xs text-red-500">({x.blocked} blocked)</span> : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
      {assign && <AssignDomainModal domain={assign} onClose={() => setAssign(null)} onDone={() => { domains.reload(); sessions.reload() }} />}
      {openApp && <AppUsageModal app={openApp} deviceId={device.id} initialPeriod={range === 'yesterday' || range === 'today' ? 'day' : 'week'} onClose={() => setOpenApp(null)} />}
    </div>
  )
}

function ControlsTab({ device, reload }) {
  const toast = useToast()
  const [c, setC] = useState(device.controls)
  const [busy, setBusy] = useState(false)
  // Only reset the form when the saved controls actually change, so auto-refresh doesn't wipe unsaved edits.
  const saved = JSON.stringify(device.controls)
  useEffect(() => setC(JSON.parse(saved)), [saved])
  const dirty = JSON.stringify(c) !== JSON.stringify(device.controls)
  const set = (k) => (v) => setC((x) => ({ ...x, [k]: v }))
  const { data: global } = useApi('/adguard/global-filters')
  const FILTERS = ['filtering', 'safebrowsing', 'parental', 'safe_search']
  // While following AdGuard, show AdGuard's own (global) values. Changing any switch makes this device custom.
  const shown = (k) => (c.use_global && global?.available ? global[k] : c[k])
  const flip = (k) => (v) => setC((x) => {
    const base = x.use_global && global?.available ? Object.fromEntries(FILTERS.map((f) => [f, global[f]])) : {}
    return { ...x, ...base, use_global: false, [k]: v }
  })
  const save = async () => {
    setBusy(true)
    try { await api(`/devices/${device.id}/controls`, { method: 'PUT', body: c }); toast('Controls saved'); reload() } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }
  return (
    <div className="space-y-6">
      {device.is_self && <Callout tone="info">This is the PC running HomeNet. You can still set filters, but you can't pause it.</Callout>}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Always block these apps" subtitle="Blocked all day. For a daily allowance use Time limits; for set hours use a schedule." className="lg:col-span-2">
          <ServicePicker ownApps
            value={[...(c.blocked_services || []), ...(c.blocked_apps || []).map((id) => `${OWN_APP}${id}`)]}
            onChange={(list) => setC((x) => ({
              ...x,
              blocked_services: list.filter((v) => !String(v).startsWith(OWN_APP)),
              blocked_apps: list.filter((v) => String(v).startsWith(OWN_APP)).map((v) => Number(String(v).slice(OWN_APP.length))),
            }))} />
          <p className="help mt-3">"Yours" apps come from Apps &amp; categories and are blocked by their web addresses. Add any app there first to block it here.</p>
        </Card>
        <Card title="Filtering"
          actions={c.use_global ? <Badge color="green">AdGuard defaults</Badge> : <Badge color="blue">Custom</Badge>}>
          <div className="space-y-5">
            <Toggle checked={shown('filtering')} onChange={flip('filtering')} label="Block ads & trackers" />
            <Toggle checked={shown('safebrowsing')} onChange={flip('safebrowsing')} label="Block malware & phishing" />
            <Toggle checked={shown('parental')} onChange={flip('parental')} label="Block adult websites" />
            <Toggle checked={shown('safe_search')} onChange={flip('safe_search')} label="Force safe search" description="Google, Bing, YouTube and others." />
            <p className="help">{c.use_global
              ? "Following AdGuard Home's settings. Change any switch to customise it for this device."
              : 'Custom for this device. AdGuard’s filter lists still apply when "Block ads & trackers" is on.'}</p>
            {!c.use_global && <Button size="sm" variant="secondary" onClick={() => setC((x) => ({ ...x, use_global: true }))}>Reset to AdGuard defaults</Button>}
            {!shown('filtering') && <Callout tone="warning">With ad & tracker filtering off, pausing, schedules and time limits won't work on this device.</Callout>}
          </div>
        </Card>
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" disabled={!dirty} onClick={() => setC(device.controls)}>Discard</Button>
        <Button disabled={!dirty} loading={busy} onClick={save}>Save controls</Button>
      </div>
      <LimitsCard device={device} />
    </div>
  )
}

function SchedulesTab({ device, reload }) {
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const toast = useToast()
  return (
    <Card title="Schedules for this device" actions={<Button size="sm" icon={Plus} onClick={() => setEditing({ device_ids: [device.id] })}>Add schedule</Button>} bodyClass="">
      {!device.rules.length ? <EmptyState icon={CalendarClock} title="No schedules" description="Set bedtime or homework hours to pause internet or block apps automatically." /> : (
        <ul className="divide-y divide-slate-100 dark:divide-slate-800">
          {device.rules.map((r) => (
            <li key={r.id} className="flex items-center gap-4 px-5 py-3">
              <div className="flex-1">
                <p className="flex items-center gap-2 text-sm font-medium">{r.name}{r.active && <Badge color="red" dot>Active now</Badge>}{!r.enabled && <Badge>Off</Badge>}</p>
                <p className="text-xs text-slate-500">{r.action === 'pause_internet' ? 'Pause internet' : `Block ${r.services.length} app${r.services.length === 1 ? '' : 's'}`} · {r.start}–{r.end} · {r.days.map((d) => DAYS[d]).join(', ')}</p>
              </div>
              <Button size="sm" variant="ghost" icon={Pencil} onClick={() => setEditing(r)}>Edit</Button>
              <Button size="sm" variant="ghost" icon={Trash2} className="text-red-600 dark:text-red-400" aria-label="Delete schedule" title="Delete schedule" onClick={() => setDeleting(r)} />
            </li>
          ))}
        </ul>
      )}
      {editing && <RuleModal rule={editing} onClose={() => setEditing(null)} onSaved={reload} />}
      <ConfirmModal open={!!deleting} onClose={() => setDeleting(null)} danger title="Delete schedule?" confirmLabel="Delete"
        message={deleting && deleting.device_ids.length > 1
          ? `"${deleting.name}" also applies to ${deleting.device_ids.length - 1} other device${deleting.device_ids.length > 2 ? 's' : ''}. Deleting it removes it for all of them.`
          : `"${deleting?.name}" will stop running straight away.`}
        onConfirm={async () => {
          try { await api(`/rules/${deleting.id}`, { method: 'DELETE' }); toast('Schedule deleted'); setDeleting(null); reload() } catch (e) { toast(e.message, 'error') }
        }} />
    </Card>
  )
}

/** Tells the parent whether a pause is actually working for this device, and why it might not be. */
function PauseHealth({ device }) {
  if (device.is_self) return null
  const r = device.recent_lookups || { total: 0, blocked: 0 }
  const usesAdGuard = device.last_dns && Date.now() / 1000 - device.last_dns < 3600
  if (!device.paused) {
    if (device.adguard_enabled && device.is_online && !usesAdGuard) {
      return (
        <Callout tone="warning" className="mb-6" title="Pausing won't work for this device yet">
          It hasn't sent any lookups to AdGuard Home in the last hour, so HomeNet can't see or block its activity.
          Point it at this PC for DNS (see <Link className="link" to="/dhcp">Address server</Link> or the <Link className="link" to="/settings/guide">setup guide</Link>).
        </Callout>
      )
    }
    return null
  }
  if (!device.adguard_enabled) {
    return <Callout tone="warning" className="mb-6" title="Pause is waiting for AdGuard Home">Connect AdGuard Home in Settings so the pause can take effect.</Callout>
  }
  if (!usesAdGuard) {
    return (
      <Callout tone="error" className="mb-6" title="This pause can't take effect">
        The device isn't sending lookups to AdGuard Home, so there's nothing to block. It may use the modem, a VPN or iCloud Private Relay for DNS.
        Point it at this PC for DNS (see <Link className="link" to="/dhcp">Address server</Link>).
      </Callout>
    )
  }
  return (
    <Callout tone="info" className="mb-6" title={r.blocked ? `Pause is working: ${r.blocked} of ${r.total} lookups blocked in the last 15 minutes` : 'Pause is active'}>
      New connections are blocked straight away. Apps that were <b>already connected</b> (video, WhatsApp, games) can keep working for a few minutes until they reconnect.
      To cut them off now, turn the device's Wi-Fi off and on, or close the apps.
      {r.total > r.blocked && r.blocked > 0 && <> Some lookups still got through: check iCloud Private Relay or VPN apps on the device.</>}
    </Callout>
  )
}

export default function DeviceDetail() {
  const { id } = useParams()
  const refresh = useAutoRefresh('device', 60000)
  return <RefreshScope state={refresh}><DeviceView id={id} refresh={refresh} /></RefreshScope>
}

function DeviceView({ id, refresh }) {
  const nav = useNavigate()
  const toast = useToast()
  const { data: device, error, loading, reload } = useApi(`/devices/${id}`)
  const [tab, setTab] = useState('overview')
  const [edit, setEdit] = useState(false)
  const [del, setDel] = useState(false)

  if (loading && !device) return <Loading />
  if (error && !device) return <ErrorState error={error} onRetry={reload} />

  return (
    <>
      <div className="mb-4 flex items-center justify-between gap-4">
        <Link to="/devices" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"><ArrowLeft className="h-4 w-4" />All devices</Link>
        <RefreshControl state={refresh} />
      </div>
      <div className="card mb-6 flex flex-col gap-5 p-5 sm:flex-row sm:items-center">
        <DeviceIcon type={device.type} online={device.is_online} paused={device.paused} inUse={device.in_use} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold">{device.display_name}
            {device.is_self && <Badge color="blue">This PC</Badge>}{device.is_gateway && <Badge color="violet">Router</Badge>}
          </h1>
          <p className="mt-1 flex flex-wrap items-center text-sm text-slate-500">
            {[device.owner && `Belongs to ${device.owner}`, TYPE_LABELS[device.type], device.ip].filter(Boolean).join(' · ')}
            {device.ip && <CopyButton value={device.ip} label="IP address" />}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusDot online={device.is_online} paused={device.paused} inUse={device.in_use} />
            {device.block_reasons.map((r) => <Badge key={r} color="red">{r}</Badge>)}
            {device.is_private_mac && <Badge color="amber" title="This device uses a private/random MAC address">Private address</Badge>}
          </div>
          {!device.paused && (device.live
            ? <UsingNow live={device.live} last={device.last_used} className="mt-2" />
            : device.last_used && <LastUsedLine last={device.last_used} className="mt-2" />)}
        </div>
        <div className="flex flex-wrap gap-2">
          <PauseButton device={device} onChange={reload} size="md" />
          <Button variant="secondary" icon={Pencil} onClick={() => setEdit(true)}>Edit</Button>
          <Button variant="danger-soft" icon={Trash2} onClick={() => setDel(true)} aria-label="Forget device" />
        </div>
      </div>

      <PauseHealth device={device} />

      <Tabs value={tab} onChange={setTab} tabs={[
        { value: 'overview', label: 'Overview', icon: LayoutGrid },
        { value: 'activity', label: 'Activity', icon: ActivityIcon },
        { value: 'controls', label: 'Controls', icon: ShieldCheck },
        { value: 'schedules', label: 'Schedules', icon: CalendarClock, count: device.rules.length },
      ]} />
      {tab === 'overview' && <OverviewTab device={device} />}
      {tab === 'activity' && <ActivityTab device={device} />}
      {tab === 'controls' && <ControlsTab device={device} reload={reload} />}
      {tab === 'schedules' && <SchedulesTab device={device} reload={reload} />}

      <EditDeviceModal device={device} open={edit} onClose={() => setEdit(false)} onSaved={reload} />
      <ConfirmModal open={del} onClose={() => setDel(false)} danger confirmLabel="Forget device" title="Forget this device?"
        message="Its history and controls will be deleted. If it connects again it will show up as a new device."
        onConfirm={async () => { await api(`/devices/${id}`, { method: 'DELETE' }); toast('Device removed'); nav('/devices') }} />
    </>
  )
}
