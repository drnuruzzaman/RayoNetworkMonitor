/**
 * One clock for the whole dashboard: the HomeNet server's time (the PC on your network), not the
 * viewing device's. The server timestamps all activity, so anchoring here keeps times consistent and
 * correct even if the phone or laptop you're viewing from has a wrong clock or a different timezone.
 *
 * Until the server clock has loaded, everything falls back to the browser's own time, so nothing breaks.
 */
let skewMs = 0 // serverNow - browserNow
let offsetMin = null // server's UTC offset in minutes; null = not loaded yet (use browser local)
let tzName = null // chosen IANA timezone (e.g. 'Australia/Sydney'); wins over offsetMin, handles daylight saving

function validTz(name) {
  if (!name) return null
  try { new Intl.DateTimeFormat('en', { timeZone: name }); return name } catch { return null }
}

export function setServerClock({ now, tz_offset, display_tz } = {}) {
  if (typeof now === 'number') skewMs = now * 1000 - Date.now()
  if (typeof tz_offset === 'number') offsetMin = tz_offset
  if (display_tz !== undefined) tzName = validTz(display_tz)
}

export const serverNowMs = () => Date.now() + skewMs
export const serverNowSec = () => serverNowMs() / 1000
export const serverOffsetMin = () => offsetMin

// How times render:
//  - a chosen timezone (tzName) → format the real Date with { timeZone: tzName } (daylight-saving aware)
//  - else the PC's offset → shift the Date and format as UTC, so fields read as the PC's wall clock
//  - else (nothing loaded) → the browser's own local time
export const serverDate = (ts) => (!tzName && offsetMin != null ? new Date(ts * 1000 + offsetMin * 60000) : new Date(ts * 1000))
export const tzOpt = () => (tzName ? { timeZone: tzName } : offsetMin != null ? { timeZone: 'UTC' } : {})

/** yyyy-mm-dd for a timestamp in the display timezone. */
export function ymd(ts) {
  if (tzName) {
    return new Intl.DateTimeFormat('en-CA', { timeZone: tzName, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(ts * 1000))
  }
  const d = serverDate(ts)
  const p = (n) => String(n).padStart(2, '0')
  return offsetMin == null
    ? `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    : `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}`
}

/** yyyy-mm-dd for "today" in the display timezone (so day-based views request the right day). */
export const serverToday = () => ymd(serverNowSec())

/** Whole days between two timestamps, by calendar day in the display timezone (today - ts). */
export function dayDiff(ts, from = serverNowSec()) {
  const toUTC = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10))
  return Math.round((toUTC(ymd(from)) - toUTC(ymd(ts))) / 86400000)
}

/** Fetch the server clock once at startup (and periodically, to correct drift). */
export async function initServerClock() {
  const load = async () => {
    try {
      const r = await fetch('/api/time', { credentials: 'same-origin' })
      if (r.ok) setServerClock(await r.json())
    } catch { /* keep browser time */ }
  }
  await load()
  setInterval(load, 10 * 60 * 1000)
}
