import { useEffect, useMemo } from 'react'
import { MotionConfig } from 'motion/react'
import { useReducer, useSpacetimeDB, useTable } from 'spacetimedb/react'
import { reducers, tables } from './module_bindings'
import { parseCaption } from './caption'
import { buildThread, type Moment } from './thread'
import { AlertBand } from './sections/AlertBand'
import { LastAsked } from './sections/LastAsked'
import { Now } from './sections/Now'
import { People } from './sections/People'
import { Privacy } from './sections/Privacy'
import { StatusPill } from './sections/StatusPill'
import { Today } from './sections/Today'

const TEN_MIN = 10 * 60_000
const MAX_MOMENTS = 300 // shortcut: render the newest 300; upgrade to paging if a day gets longer than that

const log = (what: string) => (e: unknown) => console.error(what, e)

export default function App() {
  const { isActive } = useSpacetimeDB()
  const [momentRows, momentsReady] = useTable(tables.moment)
  const [personRows, peopleReady] = useTable(tables.person)
  const [alertRows] = useTable(tables.alert)
  const [recallRows, recallsReady] = useTable(tables.recall)
  const resolveAlert = useReducer(reducers.resolveAlert)
  const deleteSince = useReducer(reducers.deleteMomentsSince)
  const deleteAll = useReducer(reducers.deleteAll)

  const moments = useMemo<Moment[]>(
    () => momentRows
      .map(r => ({ id: Number(r.id), ts: Number(r.ts), thumb: r.thumbUrl, cap: parseCaption(r.id, r.captionJson) }))
      .sort((a, b) => b.ts - a.ts)
      .slice(0, MAX_MOMENTS),
    [momentRows],
  )
  const thread = useMemo(() => buildThread(moments), [moments])
  const latestFrame = moments.find(m => m.cap.kind === 'frame') ?? moments[0]
  const alerts = useMemo(() => alertRows.filter(a => !a.resolved).sort((a, b) => Number(b.ts - a.ts)), [alertRows])
  const people = useMemo(() => [...personRows].sort((a, b) => Number(b.lastSeenTs - a.lastSeenTs)), [personRows])
  const recalls = useMemo(() => [...recallRows].sort((a, b) => Number(b.ts - a.ts)), [recallRows])

  useEffect(() => {
    document.title = alerts.length ? `● ${alerts[0].kind === 'help' ? 'Help needed' : 'Wearer is lost'} · Memory` : 'Memory'
  }, [alerts])

  return (
    <MotionConfig reducedMotion="user">
      <header className="sticky top-0 z-20 border-b border-border bg-background" style={{ height: 'var(--header-h)' }}>
        <div className="mx-auto flex h-full max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <h1 className="text-[15px] font-semibold tracking-tight">Memory</h1>
          <StatusPill active={isActive} lastTs={moments[0]?.ts ?? null} />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 pb-16 pt-5 sm:px-6">
        <AlertBand alerts={alerts} thumb={latestFrame?.thumb ?? ''} onResolve={id => resolveAlert({ id }).catch(log('resolve failed'))} />
        <div className="grid gap-4 lg:grid-cols-12 lg:grid-rows-[repeat(4,auto)_1fr] lg:items-start">
          <div className="lg:col-span-5 lg:row-start-1"><Now moment={latestFrame} ready={momentsReady} /></div>
          <div className="lg:col-span-5 lg:row-start-2"><LastAsked recalls={recalls} ready={recallsReady} /></div>
          <div className="lg:col-span-5 lg:row-start-3"><People people={people} ready={peopleReady} /></div>
          <div className="lg:col-span-7 lg:col-start-6 lg:row-span-5 lg:row-start-1"><Today items={thread} ready={momentsReady} /></div>
          <div className="lg:col-span-5 lg:row-start-4">
            <Privacy
              onForgetRecent={() => deleteSince({ sinceTs: BigInt(Date.now() - TEN_MIN) }).catch(log('forget recent failed'))}
              onForgetAll={() => deleteAll().catch(log('forget all failed'))}
            />
          </div>
        </div>
      </main>
    </MotionConfig>
  )
}
