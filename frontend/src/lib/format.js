export function duration(sec) {
  sec = Math.round(sec || 0)
  if (sec < 60) return sec > 0 ? '<1m' : '0m'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (h === 0) return `${m}m`
  return m ? `${h}h ${m}m` : `${h}h`
}

import { serverNowSec, serverDate, tzOpt } from './servertime'

export function timeAgo(ts) {
  if (!ts) return 'never'
  const s = serverNowSec() - ts
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  if (s < 86400 * 30) return `${Math.round(s / 86400)}d ago`
  return serverDate(ts).toLocaleDateString([], tzOpt())
}

export const clock = (ts) => ts ? serverDate(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', ...tzOpt() }) : '—'
export const dateTime = (ts) => ts ? serverDate(ts).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short', ...tzOpt() }) : '—'
export const number = (n) => (n ?? 0).toLocaleString()

export function bytes(n) {
  if (!n) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

export const RANGE_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
]

export const CATEGORY_COLORS = {
  Video: '#ef4444', Social: '#ec4899', Gaming: '#8b5cf6', Messaging: '#06b6d4', Music: '#22c55e',
  Education: '#f59e0b', Productivity: '#3b66f5', Shopping: '#f97316', AI: '#14b8a6', System: '#94a3b8', Finance: '#10b981', Kids: '#facc15', Government: '#0ea5e9', Gambling: '#b91c1c', News: '#64748b',
  Privacy: '#6366f1', Other: '#a8a29e', Background: '#cbd5e1',
}
const FALLBACK = ['#0ea5e9', '#a855f7', '#84cc16', '#e11d48', '#eab308', '#10b981', '#6366f1']
export function categoryColor(cat) {
  if (CATEGORY_COLORS[cat]) return CATEGORY_COLORS[cat]
  let h = 0
  for (const c of cat || '') h = (h * 31 + c.charCodeAt(0)) >>> 0
  return FALLBACK[h % FALLBACK.length]
}

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
