import { useEffect, useState } from 'react'

export const EASE = [0.2, 0, 0, 1] as const

/** Re-renders every `ms` so "3s ago" labels stay true. */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(id)
  }, [ms])
  return now
}

/** Holds the previous image on screen until the next one has loaded, so frames never flash empty. */
export function useLoadedSrc(src: string) {
  const [state, setState] = useState<{ shown: string | null; failed: boolean }>({ shown: null, failed: false })
  useEffect(() => {
    if (!src) return setState({ shown: null, failed: false })
    let live = true
    const img = new Image()
    img.onload = () => live && setState({ shown: src, failed: false })
    img.onerror = () => live && setState({ shown: null, failed: true })
    img.src = src
    return () => { live = false }
  }, [src])
  return state
}

/** Tracks a CSS media query, so the layout can move whole cards between columns instead of leaving grid gaps. */
export function useMedia(query: string) {
  const [match, setMatch] = useState(() => typeof window !== 'undefined' && window.matchMedia(query).matches)
  useEffect(() => {
    const mql = window.matchMedia(query)
    const on = () => setMatch(mql.matches)
    on()
    mql.addEventListener('change', on)
    return () => mql.removeEventListener('change', on)
  }, [query])
  return match
}
