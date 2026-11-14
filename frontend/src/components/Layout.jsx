import { useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  Activity, AppWindow, Bell, CalendarClock, LayoutDashboard, LogOut, Menu as MenuIcon, Moon, Network, Server, Settings, Sun, Wifi, X,
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

function NavItem({ item, unread, onClick }) {
  return (
    <NavLink to={item.to} end={item.end} onClick={onClick}
      className={({ isActive }) => cx('group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition',
        isActive ? 'bg-brand-50 text-brand-700 dark:bg-brand-950/60 dark:text-brand-200'
          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-white')}>
      <item.icon className="h-[18px] w-[18px]" />
      <span className="flex-1">{item.label}</span>
      {item.badge && unread > 0 && <span className="rounded-full bg-red-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">{unread > 99 ? '99+' : unread}</span>}
    </NavLink>
  )
}

export default function Layout({ onLogout }) {
  const [dark, toggleTheme] = useTheme()
  const [open, setOpen] = useState(false)
  const { pathname } = useLocation()
  const { data } = useApi('/alerts?limit=1', { refresh: 30000 })
  const unread = data?.unread || 0

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-3 px-5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm"><Wifi className="h-5 w-5" /></span>
        <div>
          <p className="text-sm font-semibold leading-tight text-slate-900 dark:text-white">HomeNet</p>
          <p className="text-xs leading-tight text-slate-500">Network monitor</p>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV.map((n) => <NavItem key={n.to} item={n} unread={unread} onClick={() => setOpen(false)} />)}
      </nav>
      <div className="space-y-1 border-t border-slate-200 px-3 py-4 dark:border-slate-800">
        {NAV_BOTTOM.map((n) => <NavItem key={n.to} item={n} onClick={() => setOpen(false)} />)}
        <button onClick={toggleTheme} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800/70">
          {dark ? <Sun className="h-[18px] w-[18px]" /> : <Moon className="h-[18px] w-[18px]" />}{dark ? 'Light mode' : 'Dark mode'}
        </button>
        <button onClick={async () => { await api('/auth/logout', { method: 'POST' }); onLogout() }}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800/70">
          <LogOut className="h-[18px] w-[18px]" />Sign out
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/50" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl dark:bg-slate-900">
            <button className="absolute right-3 top-4 rounded-lg p-1.5 text-slate-500" onClick={() => setOpen(false)}><X className="h-5 w-5" /></button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-900/90 lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded-lg p-1.5 text-slate-600 dark:text-slate-300"><MenuIcon className="h-5 w-5" /></button>
          <span className="font-semibold">HomeNet</span>
        </header>
        <main key={pathname.split('/')[1]} className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
