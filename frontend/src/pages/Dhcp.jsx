import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Lock, LockOpen, Network, Power, Radar, Save, Trash2, XCircle } from 'lucide-react'
import { api, useApi } from '../api'
import { CopyText } from '../components/Guides'
import { RefreshControl, RefreshScope, useAutoRefresh } from '../components/RefreshControl'
import { Badge, Button, Callout, Card, EmptyState, ErrorState, Loading, Modal, PageHeader, cx, useToast } from '../components/ui'
import { dateTime, number, timeAgo } from '../lib/format'
import { SettingField } from './Settings'

function Step({ n, done, warn, title, children }) {
  return (
    <li className="flex gap-4">
      <span className={cx('flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
        done ? 'bg-emerald-500 text-white' : warn ? 'bg-red-500 text-white' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300')}>
        {done ? <CheckCircle2 className="h-4 w-4" /> : warn ? <XCircle className="h-4 w-4" /> : n}
      </span>
      <div className="min-w-0 flex-1 pb-1">
        <p className="text-sm font-semibold">{title}</p>
        <div className="mt-1 text-sm text-slate-600 dark:text-slate-400">{children}</div>
      </div>
    </li>
  )
}

function StatusCard({ d }) {
  const s = d.status
  const on = d.enabled
  const tone = !on ? 'gray' : s.running ? 'green' : 'red'
  const label = !on ? 'Off' : s.running ? 'Running' : 'Not running'
  const stats = s.stats || {}
  return (
    <Card title={<span className="flex items-center gap-2"><Network className="h-4 w-4" />Status</span>} actions={<Badge color={tone} dot>{label}</Badge>}>
      {on && s.error && <Callout tone="error" className="mb-4">{s.error}</Callout>}
      {d.config_error && <Callout tone="warning" className="mb-4" title="Settings need attention">{d.config_error}</Callout>}
      {d.config && (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
          {[
            ['This PC (server)', d.config.server_ip],
            ['Addresses handed out', `${d.config.range_start} – ${d.config.range_end}`],
            ['Gateway', d.config.gateway],
            ['DNS given to devices', d.config.dns.join(', ')],
            ['Lease length', `${d.config.lease_sec / 3600} hours`],
            ['PC address type', d.config.static_ip ? 'Fixed (static) ✓' : 'Automatic ✗'],
          ].map(([k, v]) => (
            <div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="mt-0.5 font-mono text-xs">{v}</dd></div>
          ))}
        </dl>
      )}
      {on && s.running && (
        <p className="mt-4 text-xs text-slate-500">
          Running since {dateTime(s.started)} · last request {s.last_packet ? timeAgo(s.last_packet) : 'none yet'} ·
          {' '}{number(stats.DISCOVER || 0)} discovers, {number(stats.REQUEST || 0)} requests{stats.NAK_sent ? `, ${stats.NAK_sent} refused` : ''}
        </p>
      )}
    </Card>
  )
}

function EnableModal({ open, onClose, onConfirm, probe, firewallOk }) {
  const [busy, setBusy] = useState(false)
  const others = probe?.servers?.length
  return (
    <Modal open={open} onClose={onClose} title="Turn on the address server?" size="md"
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button icon={Power} loading={busy} onClick={async () => { setBusy(true); try { await onConfirm() } finally { setBusy(false) } }}>Turn on</Button>
      </>}>
      <div className="space-y-4 text-sm text-slate-600 dark:text-slate-300">
        <p>From now on, this PC will give devices their network address and tell them to use AdGuard Home for DNS.</p>
        {firewallOk === false && (
          <Callout tone="error" title="Step 2 isn't done yet">
            Windows Firewall will block devices from reaching the address server. Run the firewall script first.
          </Callout>
        )}
        {others ? (
          <Callout tone="warning" title="Your modem is still handing out addresses">
            Turn off DHCP on the modem straight after this (step 5). Until you do, devices may get addresses from either one.
          </Callout>
        ) : (
          <Callout tone="info">Do step 5 (turn off DHCP on the modem) straight after this.</Callout>
        )}
        <p><b>Keep this PC switched on.</b> Devices keep their address for the whole lease, but new or returning devices need this PC to get one.</p>
      </div>
    </Modal>
  )
}

function DhcpView({ refresh }) {
  const toast = useToast()
  const { data: d, error, loading, reload, setData } = useApi('/dhcp')
  const [draft, setDraft] = useState({})
  const [busy, setBusy] = useState('')
  const [probe, setProbe] = useState(null)
  const [enableOpen, setEnableOpen] = useState(false)
  const [reserveIp, setReserveIp] = useState({})

  if (loading && !d) return <Loading />
  if (error && !d) return <ErrorState error={error} onRetry={reload} />

  const specs = d.settings.filter((s) => s.key !== 'dhcp_enabled')
  const valueOf = (s) => (s.key in draft ? draft[s.key] : s.value)
  const dirty = Object.keys(draft).length > 0
  const other = [...(probe?.servers || []).map((s) => s.ip), ...d.other_servers.map((s) => s.ip)]
  const uniqueOther = [...new Set(other)]
  const gateway = d.config?.gateway || '192.168.1.1'

  const save = async (body, msg) => {
    try {
      await api('/settings', { method: 'PUT', body })
      toast(msg)
      setDraft({})
      setTimeout(reload, 1500)
      reload()
      return true
    } catch (e) { toast(e.message, 'error'); return false }
  }
  const runProbe = async () => {
    setBusy('probe')
    try { setProbe(await api('/dhcp/probe', { method: 'POST' })) } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }
  const leaseAction = async (path, method, body) => {
    try { const r = await api(path, { method, body }); setData({ ...d, leases: r.leases }) } catch (e) { toast(e.message, 'error') }
  }

  return (
    <>
      <PageHeader title="Address server (DHCP)"
        description="For modems that won't let you change DNS: HomeNet hands out network addresses itself, pointing every device at AdGuard Home."
        actions={<RefreshControl state={refresh} />} />

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <StatusCard d={d} />

          <Card title="Switch-over steps" subtitle="Takes about 10 minutes. You can undo it any time.">
            <ol className="space-y-5">
              <Step n={1} done={d.config?.static_ip} warn={d.config && !d.config.static_ip} title="Give this PC a fixed IP address">
                {d.config?.static_ip ? <>Done: this PC is <span className="font-mono">{d.config.server_ip}</span>.</>
                  : 'Windows Settings → Network & internet → Wi-Fi → Hardware properties → IP assignment → Edit → Manual.'}
              </Step>
              <Step n={2} done={d.firewall?.ok} warn={d.firewall?.ok === false} title="Allow it through Windows Firewall">
                {d.firewall?.ok ? 'Done.' : <>Run once in an <b>Administrator</b> PowerShell in the HomeNet folder:
                  <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">powershell -ExecutionPolicy Bypass -File .\scripts\allow-dhcp-firewall.ps1</pre></>}
              </Step>
              <Step n={3} done={probe && !probe.servers?.length && d.enabled} title="See who's handing out addresses now">
                <p>Sends a harmless test request and lists every DHCP server that answers.</p>
                <Button className="mt-2" size="sm" variant="secondary" icon={Radar} loading={busy === 'probe'} onClick={runProbe}>Check now</Button>
                {probe && (probe.ok ? (
                  probe.servers.length ? (
                    <ul className="mt-3 space-y-1">
                      {probe.servers.map((s) => (
                        <li key={s.ip} className="rounded-lg bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                          <b className="font-mono">{s.ip}</b> is handing out addresses (offered {s.offered}, DNS {s.dns.join(', ') || 'none'})
                          {s.ip === gateway && ': that\'s your modem.'}
                        </li>
                      ))}
                    </ul>
                  ) : <p className="mt-3 text-emerald-600 dark:text-emerald-400">No other DHCP server answered. {d.enabled ? 'HomeNet is the only one. 🎉' : ''}</p>
                ) : <p className="mt-3 text-red-600">{probe.error}</p>)}
              </Step>
              <Step n={4} done={d.enabled && d.status.running} title="Turn on HomeNet's address server">
                {d.enabled ? (
                  <Button size="sm" variant="danger-soft" icon={Power} onClick={() => save({ dhcp_enabled: false }, 'Address server turned off')}>Turn off</Button>
                ) : (
                  <Button size="sm" icon={Power} disabled={!d.config?.static_ip || !!d.config_error} onClick={() => setEnableOpen(true)}>Turn on</Button>
                )}
              </Step>
              <Step n={5} done={d.enabled && probe?.ok && !probe.servers.length} warn={d.enabled && uniqueOther.length > 0} title="Turn off DHCP on your TPG modem">
                Open <CopyText text={`http://${gateway}`} />, sign in, and find <b>LAN</b> / <b>DHCP server</b> settings. Set DHCP server to <b>Disabled</b> and save.
                If there's an <b>IPv6</b> LAN option, turn off its DNS / RDNSS too (or IPv6 entirely).
                {uniqueOther.length > 0 && d.enabled && <p className="mt-2 font-medium text-red-600 dark:text-red-400">Still active: {uniqueOther.join(', ')}</p>}
                <p className="mt-2">Then press <b>Check now</b> again: only HomeNet should be left.</p>
              </Step>
              <Step n={6} done={d.leases.some((l) => l.active && !l.static)} title="Reconnect your devices">
                Turn Wi-Fi off and on (or restart) each phone, tablet and laptop. They'll appear under <b>Leases</b> below and their activity starts showing up.
              </Step>
            </ol>
            <Callout tone="info" className="mt-6" title="To undo">
              Turn DHCP back <b>on</b> in the modem, then press <b>Turn off</b> above. Devices pick up the modem again when they reconnect.
            </Callout>
          </Card>
        </div>

        <div className="space-y-6 lg:col-span-2">
          <Card title="Settings">
            <div className="space-y-5">
              {specs.map((s) => (
                <SettingField key={s.key} spec={s} value={valueOf(s)} onChange={(v) => setDraft((x) => ({ ...x, [s.key]: v }))} />
              ))}
              <div className="flex gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
                <Button icon={Save} disabled={!dirty} loading={busy === 'save'}
                  onClick={async () => { setBusy('save'); await save(draft, 'Settings saved'); setBusy('') }}>Save</Button>
                {dirty && <Button variant="secondary" onClick={() => setDraft({})}>Discard</Button>}
              </div>
            </div>
          </Card>
          <Card title="Recent activity" subtitle="What the address server has been doing" bodyClass="max-h-96 overflow-y-auto">
            {!d.events?.length ? <p className="text-sm text-slate-500">Nothing yet. Requests appear here as devices connect.</p> : (
              <ul className="space-y-2.5">
                {d.events.map((e, i) => (
                  <li key={i} className="flex gap-2.5 text-sm">
                    <span className={cx('mt-1.5 h-2 w-2 shrink-0 rounded-full', { success: 'bg-emerald-500', warn: 'bg-amber-500', error: 'bg-red-500' }[e.level] || 'bg-slate-400')} />
                    <div className="min-w-0">
                      <p className="text-slate-700 dark:text-slate-200">{e.text}</p>
                      <p className="text-xs text-slate-400">{new Date(e.ts * 1000).toLocaleTimeString()}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Callout tone="warning" title="Phones still using the modem's IPv6 DNS?">
            This page fixes IPv4. If the <Link to="/system" className="link">setup check</Link> still warns about IPv6 DNS, it lists which devices look affected; turn off IPv6 on the modem's LAN settings if you can.
          </Callout>
        </div>
      </div>

      <Card className="mt-6" title="Leases" subtitle="Which device has which address. Reserve one to keep a device on the same address." bodyClass="">
        {d.leases.length === 0 ? <EmptyState icon={Network} title="No leases yet" description="Devices appear here once they get an address from HomeNet." /> : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-100 text-sm dark:divide-slate-800">
              <thead className="bg-slate-50/70 dark:bg-slate-800/30">
                <tr><th className="th">Device</th><th className="th">Address</th><th className="th hidden md:table-cell">MAC</th><th className="th">Lease</th><th className="th text-right">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {d.leases.map((l) => (
                  <tr key={l.mac}>
                    <td className="td">
                      {l.device_id ? <Link className="link" to={`/devices/${l.device_id}`}>{l.device}</Link> : l.device}
                      {l.hostname && l.hostname !== l.device && <p className="text-xs text-slate-500">{l.hostname}</p>}
                    </td>
                    <td className="td font-mono text-xs">
                      {l.static ? l.ip : (
                        <input className="input w-36 py-1 font-mono text-xs" value={reserveIp[l.mac] ?? l.ip} onChange={(e) => setReserveIp({ ...reserveIp, [l.mac]: e.target.value })} />
                      )}
                    </td>
                    <td className="td hidden font-mono text-xs text-slate-500 md:table-cell">{l.mac}</td>
                    <td className="td">
                      {l.static ? <Badge color="blue"><Lock className="h-3 w-3" />Reserved</Badge>
                        : l.active ? <span className="text-xs text-slate-600 dark:text-slate-300">Until {dateTime(l.expires)}</span>
                          : <Badge>Expired</Badge>}
                    </td>
                    <td className="td text-right">
                      <div className="flex justify-end gap-1">
                        {l.static ? (
                          <Button size="sm" variant="ghost" icon={LockOpen} onClick={() => leaseAction(`/dhcp/leases/${l.mac}/reserve`, 'DELETE')}>Unreserve</Button>
                        ) : (
                          <>
                            <Button size="sm" variant="ghost" icon={Lock} onClick={() => leaseAction(`/dhcp/leases/${l.mac}/reserve`, 'POST', { ip: reserveIp[l.mac] ?? l.ip })}>Reserve</Button>
                            <Button size="sm" variant="ghost" icon={Trash2} className="text-red-600" aria-label="Forget lease" onClick={() => leaseAction(`/dhcp/leases/${l.mac}`, 'DELETE')} />
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <EnableModal open={enableOpen} onClose={() => setEnableOpen(false)} probe={probe} firewallOk={d.firewall?.ok}
        onConfirm={async () => { if (await save({ dhcp_enabled: true }, 'Address server turned on')) setEnableOpen(false) }} />
    </>
  )
}

export default function Dhcp() {
  const refresh = useAutoRefresh('dhcp', 10000)
  return <RefreshScope state={refresh}><DhcpView refresh={refresh} /></RefreshScope>
}
