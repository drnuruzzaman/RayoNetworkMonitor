import { useEffect, useMemo, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { cx } from './ui'

/**
 * Search box with a dropdown list. Click (or type) to see options, click one to pick it.
 * options: [{ value, label, icon?, hint?, group? }]
 */
export default function SearchSelect({ options, onSelect, placeholder = 'Search…', exclude = [], emptyText = 'No matches', limit = 150 }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [hi, setHi] = useState(0)
  const box = useRef(null)
  const listRef = useRef(null)

  useEffect(() => {
    const h = (e) => box.current && !box.current.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const ex = useMemo(() => new Set(exclude.map(String)), [exclude])
  const list = useMemo(() => {
    const s = q.trim().toLowerCase()
    return options.filter((o) => !ex.has(String(o.value)) && (!s || `${o.label} ${o.hint || ''} ${o.group || ''}`.toLowerCase().includes(s))).slice(0, limit)
  }, [options, q, ex, limit])

  useEffect(() => setHi(0), [q, open])
  useEffect(() => {
    listRef.current?.querySelector(`[data-i="${hi}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [hi])

  const pick = (o) => { onSelect(o.value, o); setQ(''); setHi(0) }
  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHi((h) => Math.min(h + 1, list.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (list[hi]) pick(list[hi]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  let lastGroup = null
  return (
    <div className="relative" ref={box}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input className="input pl-9" placeholder={placeholder} value={q}
        onFocus={() => setOpen(true)} onClick={() => setOpen(true)} onKeyDown={onKey}
        onChange={(e) => { setQ(e.target.value); setOpen(true) }} />
      {open && (
        <div ref={listRef} className="absolute z-40 mt-1 max-h-72 w-full overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-xl dark:border-slate-700 dark:bg-slate-800">
          {list.length === 0 ? <p className="px-3 py-3 text-sm text-slate-500">{emptyText}</p> : list.map((o, i) => {
            const header = o.group && o.group !== lastGroup ? (lastGroup = o.group) : null
            return (
              <div key={`${o.group || ''}${o.value}`}>
                {header && <p className="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{header}</p>}
                <button type="button" data-i={i} onMouseEnter={() => setHi(i)} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(o)}
                  className={cx('flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm', i === hi ? 'bg-brand-50 text-brand-800 dark:bg-brand-950/60 dark:text-brand-100' : 'text-slate-700 dark:text-slate-200')}>
                  {o.icon || <span className="h-4 w-4" />}
                  <span className="flex-1 truncate">{o.label}</span>
                  {o.hint && <span className="shrink-0 text-xs text-slate-400">{o.hint}</span>}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
