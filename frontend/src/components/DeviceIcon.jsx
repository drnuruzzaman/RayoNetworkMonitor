import { Camera, Cpu, Gamepad2, HelpCircle, Laptop, Monitor, Printer, Router, Smartphone, Speaker, Tablet, Tv } from 'lucide-react'
import { cx } from './ui'

const ICONS = {
  phone: Smartphone, tablet: Tablet, laptop: Laptop, computer: Monitor, tv: Tv, console: Gamepad2,
  speaker: Speaker, camera: Camera, iot: Cpu, router: Router, printer: Printer, unknown: HelpCircle,
}

export const TYPE_LABELS = {
  phone: 'Phone', tablet: 'Tablet', laptop: 'Laptop', computer: 'Computer', tv: 'TV / streaming', console: 'Games console',
  speaker: 'Smart speaker', camera: 'Camera', iot: 'Smart home', router: 'Router / network', printer: 'Printer', unknown: 'Unknown',
}

export default function DeviceIcon({ type, online, paused, inUse, size = 'md' }) {
  const Icon = ICONS[type] || HelpCircle
  const box = size === 'lg' ? 'h-14 w-14 rounded-2xl' : size === 'sm' ? 'h-8 w-8 rounded-lg' : 'h-10 w-10 rounded-xl'
  const ic = size === 'lg' ? 'h-7 w-7' : size === 'sm' ? 'h-4 w-4' : 'h-5 w-5'
  return (
    <span className={cx('relative inline-flex shrink-0 items-center justify-center', box,
      paused ? 'bg-red-50 text-red-600 dark:bg-red-950/50 dark:text-red-300'
        : online ? 'bg-brand-50 text-brand-600 dark:bg-brand-950/60 dark:text-brand-300'
          : 'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500')}>
      <Icon className={ic} />
      <span className={cx('absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white dark:border-slate-900',
        paused ? 'bg-red-500' : !online ? 'bg-slate-300 dark:bg-slate-600' : inUse === false ? 'bg-orange-500' : 'bg-emerald-500')} />
    </span>
  )
}
