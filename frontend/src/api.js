import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

let onUnauthorized = () => {}
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn }

export async function api(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  let data = null
  const text = await res.text()
  try { data = text ? JSON.parse(text) : null } catch { data = { detail: text } }
  if (!res.ok) {
    let msg = data?.detail
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join(', ')
    if (res.status === 401 && !path.startsWith('/auth/login')) onUnauthorized(msg)
    throw new ApiError(msg || `Request failed (${res.status})`, res.status)
  }
  return data
}

/** Load data, with optional auto-refresh. Returns { data, error, loading, reload, setData }. */
export function useApi(path, { refresh = 0, enabled = true } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)

  const reload = useCallback(async () => {
    if (!path || !enabled) return
    try {
      const d = await api(path)
      if (alive.current) { setData(d); setError(null) }
    } catch (e) {
      if (alive.current) setError(e)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [path, enabled])

  useEffect(() => {
    alive.current = true
    setLoading(true)
    reload()
    let t
    if (refresh) t = setInterval(() => { if (!document.hidden) reload() }, refresh)
    return () => { alive.current = false; clearInterval(t) }
  }, [reload, refresh])

  // Page-level refresh button / auto-refresh (see RefreshControl) bumps this tick.
  const tick = useContext(RefreshContext)
  useEffect(() => { if (tick) reload() }, [tick]) // eslint-disable-line react-hooks/exhaustive-deps

  return { data, error, loading, reload, setData }
}

export const RefreshContext = createContext(0)
