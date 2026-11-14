import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Database, RefreshCw, Radar, Server, ShieldCheck, Workflow } from 'lucide-react'
import { api, useApi } from '../api'
import { SetupCheckCard } from '../components/SetupCheck'
import { Badge, Button, Card, ErrorState, Loading, PageHeader, useToast } from '../components/ui'
import { bytes, dateTime, number, timeAgo } from '../lib/format'

function Row({ label, children }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium">{children ?? '—'}</span>
    </div>
  )
}

function Health({ ok, off }) {
  if (off) return <Badge>Off</Badge>
  if (ok === null || ok === undefined) return <Badge color="amber" dot>Waiting</Badge>
  return ok ? <Badge color="green" dot>Healthy</Badge> : <Badge color="red" dot>Problem</Badge>
}

export default function System() {
  const toast = useToast()
  const { data, error, loading, reload } = useApi('/system/status', { refresh: 10000 })
  const [busy, setBusy] = useState('')
  if (loading && !data) return <Loading />
  if (error && !data) return <ErrorState error={error} onRetry={reload} />
  const { status: st } = data
  const act = async (key, path, msg) => {
    setBusy(key)
    try { const r = await api(path, { method: 'POST' }); toast(msg(r)); reload() } catch (e) { toast(e.message, 'error') } finally { setBusy('') }
  }

  return (
    <>
      <PageHeader title="System status" description={`HomeNet ${data.version} · running since ${dateTime(st.started)}`} />
      <div className="mb-6"><SetupCheckCard /></div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Radar className="h-4 w-4" />Network scanner</span>} actions={<Health ok={st.scan.last_run ? !st.scan.error : null} />}>
          <Row label="Adapter">{st.scan.interface ? `${st.scan.interface.alias} (${st.scan.interface.ip})` : null}</Row>
          <Row label="Range">{st.scan.interface?.network}</Row>
          <Row label="Router">{st.scan.interface?.gateway}</Row>
          <Row label="Last scan">{st.scan.last_run ? `${timeAgo(st.scan.last_run)} · ${st.scan.duration ?? '?'}s` : 'Not yet'}</Row>
          <Row label="Devices found">{st.scan.found}</Row>
          {st.scan.error && <p className="mt-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{st.scan.error}</p>}
          <Button className="mt-4" variant="secondary" size="sm" icon={Radar} loading={busy === 'scan' || st.scan.running} onClick={() => act('scan', '/system/scan', (r) => `Scan finished: ${r.found ?? 0} online`)}>Scan now</Button>
        </Card>

        <Card title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" />AdGuard Home</span>} actions={<Health ok={st.adguard.ok} off={!data.adguard_enabled} />}>
          {!data.adguard_enabled ? (
            <p className="text-sm text-slate-500">Not connected. <Link to="/settings/adguard" className="link">Set it up</Link> to track app usage and pause devices.</p>
          ) : (
            <>
              <Row label="Version">{st.adguard.version}</Row>
              <Row label="Last sync">{st.adguard.last_sync ? timeAgo(st.adguard.last_sync) : 'Not yet'}</Row>
              <Row label="Lookups imported (this run)">{number(st.adguard.ingested)}</Row>
              {st.adguard.error && <p className="mt-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{st.adguard.error}</p>}
              <Button className="mt-4" variant="secondary" size="sm" icon={RefreshCw} loading={busy === 'sync'} onClick={() => act('sync', '/system/sync', (r) => `Imported ${r.ingested} new lookups`)}>Sync now</Button>
            </>
          )}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Workflow className="h-4 w-4" />Pauses &amp; schedules</span>} actions={<Health ok={st.enforcer.last_run ? !st.enforcer.error : null} off={!data.adguard_enabled} />}>
          <Row label="Last applied">{st.enforcer.last_run ? timeAgo(st.enforcer.last_run) : 'Not yet'}</Row>
          <Row label="Addresses blocked right now">{st.enforcer.blocked_ips?.length ? st.enforcer.blocked_ips.join(', ') : 'None'}</Row>
          {st.enforcer.error && <p className="mt-2 rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{st.enforcer.error}</p>}
        </Card>

        <Card title={<span className="flex items-center gap-2"><Database className="h-4 w-4" />Data</span>}>
          <Row label="Database size">{bytes(data.db_size)}</Row>
          <Row label="Known devices">{data.devices}</Row>
          <Row label="Stored lookups">{number(data.queries)}</Row>
          <Row label="Manufacturer entries">{number(data.oui_entries)}</Row>
          <Row label="Dashboard address"><span className="font-mono">{data.bind.host}:{data.bind.port}</span></Row>
          <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500"><Server className="h-3.5 w-3.5" />All data stays on this PC.</p>
        </Card>
      </div>
    </>
  )
}
