import { useEffect, useState } from 'react'
import { api } from '../api'
import { TYPE_LABELS } from './DeviceIcon'
import { Button, Field, Modal, Select, Toggle, useToast } from './ui'

export default function EditDeviceModal({ device, open, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (device) setForm({ name: device.name || '', owner: device.owner || '', type: device.type || 'unknown', notes: device.notes || '', trusted: !!device.trusted })
  }, [device, open])
  if (!device) return null
  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v?.target ? v.target.value : v }))

  const save = async () => {
    setBusy(true)
    try {
      await api(`/devices/${device.id}`, { method: 'PATCH', body: form })
      toast('Device saved')
      onSaved?.()
      onClose()
    } catch (e) { toast(e.message, 'error') } finally { setBusy(false) }
  }

  return (
    <Modal open={open} onClose={onClose} title="Edit device" description={`${device.mac} · ${device.ip || 'no IP'}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} onClick={save}>Save</Button></>}>
      <div className="space-y-4">
        <Field label="Name" help={device.hostname ? `Reported name: ${device.hostname}` : 'Give it a name you\'ll recognise, like "Mia\'s iPad".'}>
          <input className="input" value={form.name} onChange={set('name')} placeholder={device.display_name} autoFocus />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Belongs to"><input className="input" value={form.owner} onChange={set('owner')} placeholder="e.g. Mia" /></Field>
          <Field label="Type">
            <Select value={form.type} onChange={set('type')} options={Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))} />
          </Field>
        </div>
        <Field label="Notes"><textarea className="input" rows={2} value={form.notes} onChange={set('notes')} /></Field>
        <Toggle checked={form.trusted} onChange={set('trusted')} label="I know this device" description="Known devices are marked so new or unexpected ones stand out." />
      </div>
    </Modal>
  )
}
