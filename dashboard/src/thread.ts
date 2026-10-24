import type { Caption } from './caption.ts'

export interface Moment { id: number; ts: number; thumb: string; cap: Caption }

// Frames arrive about every 3 s, so a day is thousands of rows. Consecutive frames in the same kind of place
// (home, outside, ...) collapse into one stay; what the wearer said and who they met stay as their own rows.
export interface Stay { type: 'stay'; key: string; at: number; start: number; place: string; frames: Moment[] } // frames newest first
export interface Fact { type: 'fact'; key: string; at: number; said: string; room: string; thumb: string }
export interface Met { type: 'person'; key: string; at: number; name: string; clothing: string; thumb: string }
export type Item = Stay | Fact | Met

export const STAY_GAP_MS = 30 * 60_000
// The place classifier flickers (a close-up of a wall reads as "other" in the middle of a coffee shop), so a new
// place only starts a stay once this many frames in a row agree on it; shorter blips stay in the current stay.
export const SWITCH_FRAMES = 3

/** Newest first. A stay's key is its first frame's id, so a growing stay is the same row, not a new one. */
export function buildThread(moments: Moment[]): Item[] {
  const items: Item[] = []
  let open: Stay | null = null
  let pending: Moment[] = [] // frames since `open`'s place was last seen, not yet enough to start a new stay
  const join = (s: Stay, ms: Moment[]) => {
    for (const f of ms) s.frames.unshift(f)
    if (ms.length) s.at = ms[ms.length - 1].ts
  }
  const start = (ms: Moment[]): Stay => {
    const s: Stay = { type: 'stay', key: `stay-${ms[0].id}`, at: ms[0].ts, start: ms[0].ts, place: ms[0].cap.place, frames: [] }
    join(s, ms)
    items.push(s)
    return s
  }
  for (const m of [...moments].sort((a, b) => a.ts - b.ts)) {
    const { cap } = m
    if (cap.kind === 'fact') {
      items.push({ type: 'fact', key: `fact-${m.id}`, at: m.ts, said: cap.said, room: cap.placeDetail, thumb: m.thumb })
    } else if (cap.kind === 'person') {
      const p = cap.people[0]
      items.push({ type: 'person', key: `met-${m.id}`, at: m.ts, name: p?.name ?? '', clothing: p?.clothing ?? '', thumb: m.thumb })
    } else if (!open) {
      open = start([m])
    } else if (m.ts - (pending.length ? pending[pending.length - 1].ts : open.at) > STAY_GAP_MS) {
      join(open, pending)
      pending = []
      open = start([m])
    } else if (cap.place === open.place) {
      join(open, [...pending, m]) // the blip was noise
      pending = []
    } else {
      pending.push(m)
      const run = pending.slice(-SWITCH_FRAMES)
      if (run.length === SWITCH_FRAMES && run.every(f => f.cap.place === cap.place)) {
        join(open, pending.slice(0, -SWITCH_FRAMES))
        pending = []
        open = start(run)
      }
    }
  }
  if (open) join(open, pending) // not confirmed yet: show it in the current stay for now
  return items.sort((a, b) => b.at - a.at)
}
