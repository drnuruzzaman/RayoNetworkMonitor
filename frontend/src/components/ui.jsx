import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, Info, Loader2, X, XCircle } from 'lucide-react'

export const cx = (...c) => c.filter(Boolean).join(' ')

// ------------------------------------------------------------------ Button
const VARIANTS = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 shadow-sm disabled:bg-brand-400',
  secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 shadow-sm dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700 dark:hover:bg-slate-700',
  ghost: 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
  danger: 'bg-red-600 text-white hover:bg-red-700 shadow-sm',
  'danger-soft': 'bg-red-50 text-red-700 hover:bg-red-100 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/70',
  success: 'bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm',
}
const SIZES = { sm: 'px-2.5 py-1.5 text-xs gap-1.5', md: 'px-3.5 py-2 text-sm gap-2', lg: 'px-5 py-2.5 text-sm gap-2' }

export function Button({ variant = 'primary', size = 'md', loading, icon: Icon, children, className, ...props }) {
  return (
    <button
      className={cx('inline-flex items-center justify-center rounded-lg font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 dark:focus-visible:ring-offset-slate-900',
        VARIANTS[variant], SIZES[size], className)}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : Icon ? <Icon className={size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'} /> : null}
      {children}
    </button>
  )
}

// ------------------------------------------------------------------ Card
export function Card({ title, subtitle, actions, children, className, bodyClass = 'p-5' }) {
  return (
    <section className={cx('card', className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-900 dark:text-white">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function StatCard({ label, value, hint, icon: Icon, tone = 'brand' }) {
  const tones = {
    brand: 'bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300',
    green: 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-300',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-300',
    red: 'bg-red-50 text-red-600 dark:bg-red-950/50 dark:text-red-300',
    violet: 'bg-violet-50 text-violet-600 dark:bg-violet-950/50 dark:text-violet-300',
  }
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</p>
        {Icon && <span className={cx('rounded-lg p-2', tones[tone])}><Icon className="h-4 w-4" /></span>}
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 dark:text-white">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  )
}

// ------------------------------------------------------------------ Badge
const BADGE = {
  gray: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20 dark:bg-emerald-950/50 dark:text-emerald-300',
  red: 'bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-950/50 dark:text-red-300',
  amber: 'bg-amber-50 text-amber-800 ring-amber-600/20 dark:bg-amber-950/50 dark:text-amber-300',
  orange: 'bg-orange-50 text-orange-700 ring-orange-600/20 dark:bg-orange-950/50 dark:text-orange-300',
  blue: 'bg-brand-50 text-brand-700 ring-brand-600/20 dark:bg-brand-950/60 dark:text-brand-300',
  violet: 'bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300',
}
export function Badge({ color = 'gray', children, dot, className }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium', BADGE[color], className)}>
      {dot && <span className={cx('h-1.5 w-1.5 rounded-full', { green: 'bg-emerald-500', red: 'bg-red-500', amber: 'bg-amber-500', orange: 'bg-orange-500', gray: 'bg-slate-400', blue: 'bg-brand-500', violet: 'bg-violet-500' }[color])} />}
      {children}
    </span>
  )
}

/** inUse: true = someone is using it now, false = connected but idle/locked, undefined/null = can't tell. */
export function StatusDot({ online, paused, inUse }) {
  if (paused) return <Badge color="red" dot>Paused</Badge>
  if (!online) return <Badge color="gray" dot>Offline</Badge>
  if (inUse === true) return <Badge color="green" dot>In use</Badge>
  if (inUse === false) {
    return <span title="Connected to Wi-Fi, but only background traffic (e.g. screen locked)"><Badge color="orange" dot>Idle</Badge></span>
  }
  return <Badge color="green" dot>Online</Badge>
}

// ------------------------------------------------------------------ Form controls
export function Toggle({ checked, onChange, disabled, label, description }) {
  const btn = (
    <button
      type="button" role="switch" aria-checked={!!checked} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx('relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-brand-600' : 'bg-slate-200 dark:bg-slate-700')}
    >
      <span className={cx('pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition', checked ? 'translate-x-5' : 'translate-x-0')} />
    </button>
  )
  if (!label) return btn
  return (
    <div className="flex items-start justify-between gap-6">
      <div>
        <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{label}</p>
        {description && <p className="help">{description}</p>}
      </div>
      {btn}
    </div>
  )
}

export function Field({ label, help, children, error }) {
  return (
    <label className="block">
      {label && <span className="label">{label}</span>}
      {children}
      {error ? <p className="mt-1 text-xs text-red-600">{error}</p> : help ? <p className="help">{help}</p> : null}
    </label>
  )
}

export function Select({ value, onChange, options, className, ...props }) {
  return (
    <div className={cx('relative', className)}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="input appearance-none pr-9" {...props}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
    </div>
  )
}

export function Segmented({ value, onChange, options }) {
  return (
    <div className="inline-flex max-w-full flex-wrap rounded-lg border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-800 dark:bg-slate-900">
      {options.map((o) => (
        <button key={o.value} type="button" onClick={() => onChange(o.value)}
          className={cx('whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition',
            value === o.value ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white' : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="mb-6 border-b border-slate-200 dark:border-slate-800">
      <nav className="no-scrollbar -mb-px flex gap-6 overflow-x-auto">
        {tabs.map((t) => (
          <button key={t.value} onClick={() => onChange(t.value)}
            className={cx('flex items-center gap-2 whitespace-nowrap border-b-2 px-1 pb-3 text-sm font-medium transition',
              value === t.value ? 'border-brand-600 text-brand-700 dark:border-brand-400 dark:text-brand-300' : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200')}>
            {t.icon && <t.icon className="h-4 w-4" />}{t.label}
            {t.count != null && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs dark:bg-slate-800">{t.count}</span>}
          </button>
        ))}
      </nav>
    </div>
  )
}

// ------------------------------------------------------------------ Feedback
export function Spinner({ className = 'h-5 w-5' }) {
  return <Loader2 className={cx('animate-spin text-slate-400', className)} />
}

export function Loading({ label = 'Loading…' }) {
  return <div className="flex items-center justify-center gap-3 py-16 text-sm text-slate-500"><Spinner />{label}</div>
}

export function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {Icon && <div className="mb-4 rounded-full bg-slate-100 p-3 dark:bg-slate-800"><Icon className="h-6 w-6 text-slate-400" /></div>}
      <h3 className="text-sm font-semibold text-slate-900 dark:text-white">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

const CALLOUT = {
  info: ['border-brand-200 bg-brand-50 text-brand-900 dark:border-brand-900 dark:bg-brand-950/40 dark:text-brand-100', Info, 'text-brand-500'],
  warning: ['border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-100', AlertTriangle, 'text-amber-500'],
  error: ['border-red-200 bg-red-50 text-red-900 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-100', XCircle, 'text-red-500'],
  success: ['border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-100', CheckCircle2, 'text-emerald-500'],
}
export function Callout({ tone = 'info', title, children, action, className }) {
  const [cls, Icon, iconCls] = CALLOUT[tone]
  return (
    <div className={cx('flex gap-3 rounded-xl border p-4 text-sm', cls, className)}>
      <Icon className={cx('mt-0.5 h-5 w-5 shrink-0', iconCls)} />
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title && 'mt-1', 'opacity-90')}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  return (
    <Callout tone="error" title="Something went wrong" action={onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Retry</Button>}>
      {error?.message || String(error)}
    </Callout>
  )
}

// ------------------------------------------------------------------ Modal
export function Modal({ open, onClose, title, description, children, footer, size = 'md' }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  const widths = { sm: 'max-w-md', md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-[2px]" onClick={onClose} />
      <div className={cx('relative flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-2xl dark:bg-slate-900 sm:rounded-2xl', widths[size])}>
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4 dark:border-slate-800">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h3>
            {description && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"><X className="h-5 w-5" /></button>
        </div>
        <div className="overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-100 bg-slate-50/60 px-6 py-3 dark:border-slate-800 dark:bg-slate-900">{footer}</div>}
      </div>
    </div>
  )
}

export function ConfirmModal({ open, onClose, onConfirm, title, message, confirmLabel = 'Confirm', danger }) {
  const [busy, setBusy] = useState(false)
  return (
    <Modal open={open} onClose={onClose} title={title} size="sm"
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant={danger ? 'danger' : 'primary'} loading={busy}
          onClick={async () => { setBusy(true); try { await onConfirm() } finally { setBusy(false) } }}>{confirmLabel}</Button>
      </>}>
      <p className="text-sm text-slate-600 dark:text-slate-300">{message}</p>
    </Modal>
  )
}

// ------------------------------------------------------------------ Dropdown menu
export function Menu({ trigger, items, align = 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const h = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  return (
    <div className="relative inline-block" ref={ref}>
      <span onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}>{trigger}</span>
      {open && (
        <div className={cx('absolute z-30 mt-1 min-w-[12rem] overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-800', align === 'right' ? 'right-0' : 'left-0')}>
          {items.map((it, i) => it.divider ? <div key={i} className="my-1 border-t border-slate-100 dark:border-slate-700" /> : (
            <button key={i} onClick={(e) => { e.stopPropagation(); setOpen(false); it.onClick() }}
              className={cx('flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-700', it.danger ? 'text-red-600 dark:text-red-400' : 'text-slate-700 dark:text-slate-200')}>
              {it.icon && <it.icon className="h-4 w-4 opacity-70" />}{it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Toasts
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const push = useCallback((message, tone = 'success') => {
    const id = Math.random()
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'error' ? 7000 : 3500)
  }, [])
  const icons = { success: [CheckCircle2, 'text-emerald-500'], error: [XCircle, 'text-red-500'], info: [Info, 'text-brand-500'] }
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2">
        {toasts.map((t) => {
          const [Icon, cls] = icons[t.tone] || icons.info
          return (
            <div key={t.id} className="pointer-events-auto flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-800">
              <Icon className={cx('h-5 w-5 shrink-0', cls)} />
              <p className="text-slate-700 dark:text-slate-200">{t.message}</p>
            </div>
          )
        })}
      </div>
    </ToastCtx.Provider>
  )
}

// ------------------------------------------------------------------ Bars
export function BarList({ items, format, colorFor, max, onClick }) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value))
  return (
    <ul className="space-y-2.5">
      {items.map((it) => (
        <li key={it.key} className={cx(onClick && 'cursor-pointer')} onClick={() => onClick?.(it)}>
          <div className="mb-1 flex items-center justify-between gap-3 text-sm">
            <span className="flex min-w-0 items-center gap-2 truncate font-medium text-slate-700 dark:text-slate-200">
              {it.icon}{it.label}
              {it.sub && <span className="truncate text-xs font-normal text-slate-400">{it.sub}</span>}
            </span>
            <span className="shrink-0 tabular-nums text-slate-500 dark:text-slate-400">{format ? format(it.value) : it.value}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            <div className="h-full rounded-full transition-all" style={{ width: `${Math.max(2, (it.value / top) * 100)}%`, background: colorFor ? colorFor(it) : '#3b66f5' }} />
          </div>
        </li>
      ))}
    </ul>
  )
}
