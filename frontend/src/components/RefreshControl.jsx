import { useCallback, useEffect, useState } from 'react'
import { Check, ChevronDown, RefreshCw } from 'lucide-react'
import { RefreshContext } from '../api'
import { Menu, cx } from './ui'

export const REFRESH_OPTIONS = [
  { ms: 0, label: 'Off' },
  { ms: 5000, label: '5 seconds' },
  { ms: 10000, label: '10 seconds' },
  { ms: 60000, label: '1 minute' },
  { ms: 300000, label: '5 minutes' },
  { ms: 900000, label: '15 minutes' },
]

/** Manual + automatic refresh for a page. The interval is remembered per page in this browser. */
export function useAutoRefresh(key, defaultMs = 60000) {
  const storageKey = `homenet-refresh-${key}`
  const [intervalMs, setIntervalMs] = useState(() => {
    try {
      const v = localStorage.getItem(storageKey)
      return v === null ? defaultMs : Number(v)
    } catch { return defaultMs }
  })
  const [tick, setTick] = useState(0)
  const [updated, setUpdated] = useState(() => Date.now())

  const refresh = useCallback(() => { setTick((t) => t + 1); setUpdated(Date.now()) }, [])

  useEffect(() => {
    if (!intervalMs) return undefined
    const id = setInterval(() => { if (!document.hidden) refresh() }, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs, refresh])

  const choose = (ms) => {
    setIntervalMs(ms)
    try { localStorage.setItem(storageKey, String(ms)) } catch {}
  }
  return { tick, refresh, intervalMs, setIntervalMs: choose, updated }
}

/** Provides the refresh tick to every useApi() call inside the page. */
export function RefreshScope({ state, children }) {
  return <RefreshContext.Provider value={state.tick}>{children}</RefreshContext.Provider>
}

export function RefreshControl({ state }) {
  const [spin, setSpin] = useState(false)
  const current = REFRESH_OPTIONS.find((o) => o.ms === state.intervalMs)
  const click = () => {
    state.refresh()
    setSpin(true)
    setTimeout(() => setSpin(false), 700)
  }
  const when = new Date(state.updated)
  return (
    <div className="flex items-center gap-3">
      <div className="hidden shrink-0 whitespace-nowrap text-right leading-tight sm:block">
        <p className="text-xs text-slate-500 dark:text-slate-400">Last updated</p>
        <p className="text-xs font-medium tabular-nums text-slate-700 dark:text-slate-300" title={when.toLocaleString()}>
          {when.toLocaleDateString([], { day: 'numeric', month: 'short' })}, {when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </p>
      </div>
      <div className="inline-flex overflow-visible rounded-lg border border-slate-300 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
        <button type="button" onClick={click} title="Refresh now" aria-label="Refresh now"
          className="flex items-center gap-1.5 rounded-l-lg px-2.5 py-2 text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-700">
          <RefreshCw className={cx('h-4 w-4', spin && 'animate-spin')} />
          {state.intervalMs > 0 && <span className="text-xs text-slate-500 dark:text-slate-400">{current?.label.replace(' seconds', 's').replace(' minutes', 'm').replace(' minute', 'm')}</span>}
        </button>
        <Menu
          trigger={
            <button type="button" title="Auto-refresh" aria-label="Auto-refresh interval"
              className="flex h-full items-center rounded-r-lg border-l border-slate-300 px-2 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-700">
              <ChevronDown className="h-4 w-4" />
            </button>
          }
          items={[
            ...REFRESH_OPTIONS.map((o) => ({
              label: <span className="flex w-full items-center justify-between gap-6">{o.label}{o.ms === state.intervalMs && <Check className="h-4 w-4 text-brand-600" />}</span>,
              onClick: () => state.setIntervalMs(o.ms),
            })),
          ]}
        />
      </div>
    </div>
  )
}
