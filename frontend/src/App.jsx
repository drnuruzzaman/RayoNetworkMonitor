import { useCallback, useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, setUnauthorizedHandler } from './api'
import Layout from './components/Layout'
import { Loading } from './components/ui'
import Activity from './pages/Activity'
import Alerts from './pages/Alerts'
import Apps from './pages/Apps'
import Dashboard from './pages/Dashboard'
import DeviceDetail from './pages/DeviceDetail'
import Dhcp from './pages/Dhcp'
import Devices from './pages/Devices'
import Login from './pages/Login'
import Schedules from './pages/Schedules'
import Settings from './pages/Settings'
import Setup from './pages/Setup'
import System from './pages/System'

export default function App() {
  const [auth, setAuth] = useState({ state: 'loading' })

  const check = useCallback(async () => {
    try {
      const s = await api('/setup/status')
      if (!s.password_set) return setAuth({ state: 'setup', status: s })
      const me = await api('/auth/me')
      setAuth({ state: me.setup_complete ? 'ready' : 'wizard', status: s })
    } catch (e) {
      if (e.status === 401) setAuth({ state: 'login' })
      else setAuth({ state: 'error', error: e })
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => setAuth((a) => (a.state === 'ready' || a.state === 'wizard' ? { state: 'login' } : a)))
    check()
  }, [check])

  if (auth.state === 'loading') return <Loading label="Starting HomeNet…" />
  if (auth.state === 'error') {
    return <div className="mx-auto max-w-md p-10 text-center text-sm text-slate-500">Can't reach the HomeNet service. Is it running? ({auth.error.message})</div>
  }
  if (auth.state === 'login') return <Login onDone={check} />
  if (auth.state === 'setup' || auth.state === 'wizard') {
    return <Setup status={auth.status} passwordSet={auth.state === 'wizard'} onDone={check} />
  }

  return (
    <Routes>
      <Route element={<Layout onLogout={() => setAuth({ state: 'login' })} />}>
        <Route index element={<Dashboard />} />
        <Route path="devices" element={<Devices />} />
        <Route path="devices/:id" element={<DeviceDetail />} />
        <Route path="activity" element={<Activity />} />
        <Route path="schedules" element={<Schedules />} />
        <Route path="dhcp" element={<Dhcp />} />
        <Route path="apps" element={<Apps />} />
        <Route path="alerts" element={<Alerts />} />
        <Route path="system" element={<System />} />
        <Route path="settings" element={<Settings />} />
        <Route path="settings/:tab" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
