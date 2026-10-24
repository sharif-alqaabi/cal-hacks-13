const locale = typeof navigator === 'undefined' ? 'en-US' : navigator.language
const clockFmt = new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit' })
const dateFmt = new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' })

export const clock = (ts: number) => clockFmt.format(ts)
export const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
export const lang = locale

/** "3s ago". A phone clock a little ahead of the glasses gives a negative age, which reads as "just now". */
export function ago(ts: number, now: number) {
  const s = Math.max(0, Math.floor((now - ts) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} h ago`
  return `${dateFmt.format(ts)}, ${clock(ts)}`
}
