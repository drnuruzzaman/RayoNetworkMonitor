import { useState } from 'react'
import { ChevronDown, Pause, Play } from 'lucide-react'
import { api } from '../api'
import { Button, Menu, useToast } from './ui'

const OPTIONS = [
  { label: '15 minutes', minutes: 15 },
  { label: '30 minutes', minutes: 30 },
  { label: '1 hour', minutes: 60 },
  { label: '2 hours', minutes: 120 },
  { label: 'Until I resume', minutes: null },
]

export default function PauseButton({ device, onChange, size = 'sm' }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  if (device.is_self) return null

  const run = async (fn, msg) => {
    setBusy(true)
    try {
      const r = await fn()
      toast(msg)
      if (r && r.adguard_enabled === false) toast('AdGuard Home isn\'t connected yet, so the pause takes effect once it is.', 'info')
      onChange?.()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }

  if (device.paused) {
    const scheduleOnly = !device.paused_indefinitely && !device.paused_until
    if (scheduleOnly) return <Button size={size} variant="secondary" disabled title={(device.block_reasons || []).join(', ')}>Scheduled pause</Button>
    return (
      <Button size={size} variant="success" icon={Play} loading={busy}
        onClick={(e) => { e.stopPropagation(); run(() => api(`/devices/${device.id}/resume`, { method: 'POST' }), `Internet resumed for ${device.display_name}`) }}>
        Resume
      </Button>
    )
  }
  return (
    <Menu
      trigger={<Button size={size} variant="secondary" icon={Pause} loading={busy}>Pause<ChevronDown className="h-3.5 w-3.5 opacity-60" /></Button>}
      items={OPTIONS.map((o) => ({
        label: o.label,
        onClick: () => run(() => api(`/devices/${device.id}/pause`, { method: 'POST', body: { minutes: o.minutes } }),
          `Internet paused for ${device.display_name}. Apps that are already connected may keep working for a few minutes. Turn the device's Wi-Fi off and on to cut them off now.`),
      }))}
    />
  )
}
