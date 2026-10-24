// A moment's caption_json, parsed once per id. Shapes come from memory/service.py: a frame has objects/people/text,
// a told fact has `fact`, an introduction has `said` and no `fact`.
export type Kind = 'frame' | 'fact' | 'person'

export interface Caption {
  kind: Kind
  place: string
  placeDetail: string
  scene: string
  objects: string[]
  signs: string[]
  said: string
  people: { name: string; clothing: string }[]
}

export const known = (v: unknown): string => {
  const s = typeof v === 'string' ? v.trim() : ''
  return s.toLowerCase() === 'unknown' ? '' : s
}

const EMPTY: Caption = { kind: 'frame', place: 'other', placeDetail: '', scene: '', objects: [], signs: [], said: '', people: [] }
const cache = new Map<string, Caption>()

export function parseCaption(id: bigint | number, json: string): Caption {
  const key = String(id)
  const hit = cache.get(key)
  if (hit) return hit
  let c: Caption
  try {
    const raw = JSON.parse(json)
    const said = known(raw.said)
    c = {
      kind: raw.fact ? 'fact' : said ? 'person' : 'frame',
      place: known(raw.place) || 'other',
      placeDetail: known(raw.place_detail),
      scene: known(raw.scene),
      objects: [...new Set<string>((raw.objects ?? []).map((o: { name?: string }) => known(o.name)).filter(Boolean))],
      signs: (raw.text ?? []).map(known).filter(Boolean),
      said: said || known(raw.fact?.statement),
      people: (raw.people ?? []).map((p: { name?: string; clothing?: string }) => ({ name: known(p.name), clothing: known(p.clothing) })),
    }
  } catch {
    c = EMPTY
  }
  cache.set(key, c)
  return c
}

const PLACES: Record<string, string> = {
  home: 'Home', outside: 'Outside', office: 'Office', store: 'Store', transit: 'In transit', other: 'Elsewhere',
}
export const placeLabel = (place: string) => PLACES[place] ?? PLACES.other

export const upper = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s)
