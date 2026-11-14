import { clock } from '../lib/format'
import { cx } from './ui'

export const BLOCK_SOURCES = {
  pause: { label: 'Paused', cls: 'bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300', help: 'Blocked because this device was paused (by you or a schedule).' },
  limit: { label: 'Time limit reached', cls: 'bg-orange-50 text-orange-700 dark:bg-orange-950/50 dark:text-orange-300', help: 'Blocked because the daily time limit for this app ran out.' },
  app: { label: 'Blocked app', cls: 'bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300', help: 'Blocked by an app block in this device\'s Controls or a schedule.' },
  filter: { label: 'Ad/tracker filter', cls: 'bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300', help: 'Blocked by an AdGuard filter list. These are usually ads, trackers or analytics.' },
  adult: { label: 'Adult filter', cls: 'bg-pink-50 text-pink-700 dark:bg-pink-950/50 dark:text-pink-300', help: 'Blocked by the adult-content filter.' },
  malware: { label: 'Malware filter', cls: 'bg-orange-50 text-orange-700 dark:bg-orange-950/50 dark:text-orange-300', help: 'Blocked as malware or phishing.' },
  custom: { label: 'Your AdGuard rule', cls: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300', help: 'Blocked by a custom rule in AdGuard.' },
  other: { label: 'Other', cls: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300', help: 'Blocked by AdGuard for another reason.' },
  unknown: { label: 'Blocked', cls: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300', help: 'Blocked before HomeNet recorded the reason.' },
}

/** Small chips explaining why a domain's lookups were blocked, e.g. "Paused 13" and "Ad/tracker filter 40". */
export default function BlockReasons({ items }) {
  if (!items?.length) return null
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {items.map((b, i) => {
        const s = BLOCK_SOURCES[b.source] || BLOCK_SOURCES.other
        const when = b.first && b.last ? `${clock(b.first)}–${clock(b.last)}` : ''
        const title = [s.help, b.detail && `Source: ${b.detail}`, when && `When: ${when}`].filter(Boolean).join('\n')
        return (
          <span key={i} title={title} className={cx('inline-flex cursor-help items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium', s.cls)}>
            {s.label}{b.source === 'app' && b.detail ? `: ${b.detail}` : ''}
            <span className="tabular-nums opacity-70">{b.count}</span>
          </span>
        )
      })}
    </span>
  )
}
