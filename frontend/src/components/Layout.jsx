import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity, AppWindow, Bell, CalendarClock, LayoutDashboard, LogOut, Menu as MenuIcon, Moon, Network, PanelLeftClose,
  PanelLeftOpen, Server, Settings, Sun, Wifi, X,
} from 'lucide-react'
import { api, useApi } from '../api'
import { cx } from './ui'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/devices', label: 'Devices', icon: Wifi },
  { to: '/activity', label: 'Activity', icon: Activity },
  { to: '/schedules', label: 'Schedules', icon: CalendarClock },
  { to: '/apps', label: 'Apps & categories', icon: AppWindow },
  { to: '/alerts', label: 'Alerts', icon: Bell, badge: true },
]
const NAV_BOTTOM = [
  { to: '/dhcp', label: 'Address server', icon: Network },
  { to: '/system', label: 'System status', icon: Server },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const toggle = () => {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try { localStorage.setItem('homenet-theme', next ? 'dark' : 'light') } catch {}
    setDark(next)
  }
  return [dark, toggle]
}

function useStored(key, initial) {
  const [v, setV] = useState(() => {
    try { const s = localStorage.getItem(key); return s === null ? initial : JSON.parse(s) } catch { return initial }
  })
  const set = (x) => { setV(x); try { localStorage.setItem(key, JSON.stringify(x)) } catch {} }
  return [v, set]
}

function useNow() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

/** Live date and time (to the second). */
function Clock({ compact }) {
  const now = useNow()
  const time = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  const date = now.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })
  if (compact) {
    return (
      <div className="text-center leading-tight" title={`${date} ${time}`}>
        <p className="text-[11px] font-semibold tabular-nums text-slate-700 dark:text-slate-200">{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
        <p className="text-[10px] tabular-nums text-slate-400">{String(now.getSeconds()).padStart(2, '0')}s</p>
      </div>
    )
  }
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/60">
      <p className="text-lg font-semibold tabular-nums leading-tight text-slate-900 dark:text-white">{time}</p>
      <p className="text-xs text-slate-500">{date}</p>
    </div>
  )
}

function NavItem({ item, unread, onClick, collapsed }) {
  return (
    <NavLink to={item.to} end={item.end} onClick={onClick} title={collapsed ? item.label : undefined}
      className={({ isActive }) => cx('group relative flex items-center rounded-lg py-2 text-sm font-medium transition',
        collapsed ? 'justify-center px-0' : 'gap-3 px-3',
        isActive ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200'
          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white')}>
      <item.icon className="h-[18px] w-[18px] shrink-0" />
      {!collapsed && <span className="flex-1">{item.label}</span>}
      {item.badge && unread > 0 && (
        <span className={cx('rounded-full bg-red-500 text-[10px] font-semibold text-white', collapsed ? 'absolute right-1 top-0.5 px-1' : 'px-1.5 py-0.5')}>
          {unread > 99 ? '99+' : unread}
        </span>
      )}
    </NavLink>
  )
}

function ActionButton({ icon: Icon, label, onClick, collapsed }) {
  return (
    <button onClick={onClick} title={collapsed ? label : undefined}
      className={cx('flex w-full items-center rounded-lg py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800/70',
        collapsed ? 'justify-center' : 'gap-3 px-3')}>
      <Icon className="h-[18px] w-[18px] shrink-0" />{!collapsed && label}
    </button>
  )
}

export default function Layout({ onLogout }) {
  const [dark, toggleTheme] = useTheme()
  const [open, setOpen] = useState(false)
  const [collapsed, setCollapsed] = useStored('homenet-sidebar-collapsed', false)
  const { pathname } = useLocation()
  const { data } = useApi('/alerts?limit=1', { refresh: 30000 })
  const unread = data?.unread || 0
  const logout = async () => { await api('/auth/logout', { method: 'POST' }); onLogout() }

  const sidebar = (c, mobile) => (
    <div className="flex h-full flex-col">
      <div className={cx('flex h-16 items-center', c ? 'justify-center px-2' : 'gap-3 px-5')}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm"><Wifi className="h-5 w-5" /></span>
        {!c && (
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-tight text-slate-900 dark:text-white">HomeNet</p>
            <p className="text-xs leading-tight text-slate-500">Network monitor</p>
          </div>
        )}
        {!c && !mobile && (
          <button onClick={() => setCollapsed(true)} title="Collapse sidebar" aria-label="Collapse sidebar"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200">
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>
      <div className={c ? 'px-2' : 'px-3'}><Clock compact={c} /></div>
      {c && !mobile && (
        <button onClick={() => setCollapsed(false)} title="Expand sidebar" aria-label="Expand sidebar"
          className="mx-auto mt-3 rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200">
          <PanelLeftOpen className="h-4 w-4" />
        </button>
      )}
      <nav className={cx('flex-1 space-y-1 overflow-y-auto py-4', c ? 'px-2' : 'px-3')}>
        {NAV.map((n) => <NavItem key={n.to} item={n} unread={unread} collapsed={c} onClick={() => setOpen(false)} />)}
      </nav>
      <div className={cx('space-y-1 border-t border-slate-200 py-4 dark:border-slate-800', c ? 'px-2' : 'px-3')}>
        {NAV_BOTTOM.map((n) => <NavItem key={n.to} item={n} collapsed={c} onClick={() => setOpen(false)} />)}
        <ActionButton icon={dark ? Sun : Moon} label={dark ? 'Light mode' : 'Dark mode'} onClick={toggleTheme} collapsed={c} />
        <ActionButton icon={LogOut} label="Sign out" onClick={logout} collapsed={c} />
      </div>
    </div>
  )

  return (
    <div className="min-h-screen">
      <aside className={cx('fixed inset-y-0 left-0 z-30 hidden border-r border-slate-200 bg-white transition-[width] duration-200 dark:border-slate-800 dark:bg-slate-900 lg:block',
        collapsed ? 'w-[72px]' : 'w-64')}>
        {sidebar(collapsed, false)}
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl dark:bg-slate-900">
            <button className="absolute right-3 top-4 z-10 rounded-lg p-1.5 text-slate-500" onClick={() => setOpen(false)}><X className="h-5 w-5" /></button>
            {sidebar(false, true)}
          </aside>
        </div>
      )}
      <div className={cx('transition-[padding] duration-200', collapsed ? 'lg:pl-[72px]' : 'lg:pl-64')}>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-slate-600 dark:text-slate-300"><MenuIcon className="h-5 w-5" /></button>
          <span className="flex-1 font-semibold">HomeNet</span>
          <MobileClock />
        </header>
        <main key={pathname.split('/')[1]} className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function MobileClock() {
  const now = useNow()
  return (
    <span className="text-right text-xs leading-tight tabular-nums text-slate-500">
      <span className="block font-semibold text-slate-700 dark:text-slate-200">{now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
      {now.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })}
    </span>
  )
}
