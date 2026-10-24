import type { Caption } from './caption.ts'

export interface Moment { id: number; ts: number; thumb: string; cap: Caption }

// Frames arrive about every 3 s, so a day is thousands of rows. Consecutive frames in the same kind of place
// (home, outside, ...) collapse into one stay; what the wearer said and who they met stay as their own rows.
export interface Stay { type: 'stay'; key: string; at: number; start: number; place: string; frames: Moment[] } // frames newest first
export interface Fact { type: 'fact'; key: string; at: number; said: string; room: string; thumb: string }
export interface Met { type: 'person'; key: string; at: number; name: string; clothing: string; thumb: string }
export type Item = Stay | Fact | Met

export const STAY_GAP_MS = 30 * 60_000

/** Newest first. A stay's key is its first frame's id, so a growing stay is the same row, not a new one. */
export function buildThread(moments: Moment[]): Item[] {
  const items: Item[] = []
  let open: Stay | null = null
  for (const m of [...moments].sort((a, b) => a.ts - b.ts)) {
    const { cap } = m
    if (cap.kind === 'fact') {
      items.push({ type: 'fact', key: `fact-${m.id}`, at: m.ts, said: cap.said, room: cap.placeDetail, thumb: m.thumb })
    } else if (cap.kind === 'person') {
      const p = cap.people[0]
      items.push({ type: 'person', key: `met-${m.id}`, at: m.ts, name: p?.name ?? '', clothing: p?.clothing ?? '', thumb: m.thumb })
    } else if (open && open.place === cap.place && m.ts - open.at <= STAY_GAP_MS) {
      open.frames.unshift(m)
      open.at = m.ts
    } else {
      open = { type: 'stay', key: `stay-${m.id}`, at: m.ts, start: m.ts, place: cap.place, frames: [m] }
      items.push(open)
    }
  }
  return items.sort((a, b) => b.at - a.at)
}
