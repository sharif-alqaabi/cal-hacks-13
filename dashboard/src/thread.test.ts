import assert from 'node:assert/strict'
import { test } from 'node:test'
import type { Caption } from './caption.ts'
import { buildThread, STAY_GAP_MS, type Moment } from './thread.ts'

const cap = (over: Partial<Caption> = {}): Caption =>
  ({ kind: 'frame', place: 'home', placeDetail: '', scene: '', objects: [], signs: [], said: '', people: [], ...over })
const m = (id: number, ts: number, over: Partial<Caption> = {}): Moment => ({ id, ts, thumb: '', cap: cap(over) })

test('frames in the same place within the gap collapse into one stay', () => {
  const items = buildThread([m(1, 1000), m(2, 4000), m(3, 7000)])
  assert.equal(items.length, 1)
  const s = items[0]
  assert.ok(s.type === 'stay')
  assert.equal(s.frames.length, 3)
  assert.deepEqual([s.start, s.at], [1000, 7000])
  assert.equal(s.frames[0].id, 3) // newest first
})

test('a place change starts a new stay once it holds for a few frames, newest first', () => {
  const items = buildThread([m(1, 1000), m(2, 4000, { place: 'outside' }), m(3, 7000, { place: 'outside' }), m(4, 10000, { place: 'outside' })])
  assert.deepEqual(items.map(i => i.type === 'stay' && i.place), ['outside', 'home'])
  assert.equal(items[0].key, 'stay-2')
})

test('a classifier that flips every frame does not split the stay', () => {
  const places = ['store', 'other', 'store', 'other', 'other', 'store', 'other', 'store', 'store']
  const items = buildThread(places.map((place, i) => m(i + 1, i * 1000, { place })))
  assert.equal(items.length, 1)
  assert.ok(items[0].type === 'stay' && items[0].place === 'store' && items[0].frames.length === places.length)
})

test('an unconfirmed change at the end shows in the current stay', () => {
  const items = buildThread([m(1, 1000), m(2, 4000, { place: 'outside' })])
  assert.equal(items.length, 1)
  assert.ok(items[0].type === 'stay' && items[0].frames.length === 2 && items[0].at === 4000)
})

test('a long gap in the same place splits the stay', () => {
  assert.equal(buildThread([m(1, 0), m(2, STAY_GAP_MS + 1)]).length, 2)
})

test('a told fact is its own row and does not split the stay around it', () => {
  const items = buildThread([m(1, 1000), m(2, 2000, { kind: 'fact', said: 'my passport is in the drawer' }), m(3, 3000)])
  assert.deepEqual(items.map(i => i.type).sort(), ['fact', 'stay'])
  const stay = items.find(i => i.type === 'stay')
  assert.ok(stay?.type === 'stay' && stay.frames.length === 2)
})

test('an introduction becomes a met row with the name and clothing', () => {
  const [item] = buildThread([m(1, 1000, { kind: 'person', said: 'this is Sam', people: [{ name: 'Sam', clothing: 'red hoodie' }] })])
  assert.ok(item.type === 'person')
  assert.deepEqual([item.name, item.clothing], ['Sam', 'red hoodie'])
})

test('a stay keeps its key while frames join it', () => {
  const before = buildThread([m(1, 1000)])[0].key
  const after = buildThread([m(1, 1000), m(2, 4000)])[0].key
  assert.equal(before, after)
})
