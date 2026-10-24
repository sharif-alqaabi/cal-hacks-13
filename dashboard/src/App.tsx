import { useEffect, useMemo } from 'react'
import { MotionConfig } from 'motion/react'
import { useReducer, useSpacetimeDB, useTable } from 'spacetimedb/react'
import { reducers, tables } from './module_bindings'
import { parseCaption } from './caption'
import { useMedia } from './hooks'
import { WEARER } from './wearer'
import { buildThread, type Moment } from './thread'
import { AlertBand } from './sections/AlertBand'
import { LastAsked } from './sections/LastAsked'
import { Now } from './sections/Now'
import { People } from './sections/People'
import { Privacy } from './sections/Privacy'
import { StatusPill, useSharing } from './sections/StatusPill'
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

  const sharing = useSharing(moments[0]?.ts ?? null)
  const wide = useMedia('(min-width: 1280px)')
  const twoUp = useMedia('(min-width: 1024px)')

  const now = <Now moment={latestFrame} ready={momentsReady} />
  const asked = <LastAsked recalls={recalls} ready={recallsReady} />
  const friends = <People people={people} ready={peopleReady} />
  const day = <Today items={thread} ready={momentsReady} />
  const privacy = (
    <Privacy
      sharing={sharing}
      onForgetRecent={() => deleteSince({ sinceTs: BigInt(Date.now() - TEN_MIN) }).catch(log('forget recent failed'))}
      onForgetAll={() => deleteAll().catch(log('forget all failed'))}
    />
  )
  // Three columns on a big screen (the day in the middle), two on a laptop, one on a phone.
  const columns = wide
    ? [{ span: 'xl:col-span-4', cards: [now, asked] }, { span: 'xl:col-span-5', cards: [day] }, { span: 'xl:col-span-3', cards: [friends, privacy] }]
    : twoUp
      ? [{ span: 'lg:col-span-5', cards: [now, asked, friends, privacy] }, { span: 'lg:col-span-7', cards: [day] }]
      : [{ span: '', cards: [now, asked, day, friends, privacy] }]

  return (
    <MotionConfig reducedMotion="user">
      <header className="sticky top-0 z-20 border-b border-border/70 bg-background/85 backdrop-blur-md" style={{ height: 'var(--header-h)' }}>
        <div className="mx-auto flex h-full max-w-[1520px] items-center justify-between gap-3 px-5 sm:px-8 xl:px-12">
          <div className="flex items-center gap-2.5">
            <span className="grid size-9 place-items-center rounded-full bg-[var(--tint-peach)]"><span className="size-3.5 rounded-full bg-primary" /></span>
            <span className="text-lg font-extrabold tracking-tight">Memory</span>
          </div>
          <StatusPill active={isActive} lastTs={moments[0]?.ts ?? null} />
        </div>
      </header>
      <main className="mx-auto max-w-[1520px] px-5 pb-20 pt-8 sm:px-8 xl:px-12">
        <section className="mb-8 flex flex-col gap-1">
          <h1 className="text-[30px] font-extrabold leading-tight tracking-tight text-[var(--ink-peach)] sm:text-[38px]">{greeting()} 👋</h1>
          <p className="text-[17px] font-semibold text-foreground/75">
            {WEARER || 'Your loved one'} is sharing their day with you. Here's how it's going.
          </p>
        </section>
        <AlertBand alerts={alerts} thumb={latestFrame?.thumb ?? ''} onResolve={id => resolveAlert({ id }).catch(log('resolve failed'))} />
        <div className="grid items-start gap-6 lg:grid-cols-12 xl:gap-8">
          {columns.map((c, i) => (
            <div key={i} className={`flex min-w-0 flex-col gap-6 xl:gap-8 ${c.span}`}>
              {c.cards.map((card, j) => <div key={j}>{card}</div>)}
            </div>
          ))}
        </div>
        <p className="mt-12 text-center text-sm font-semibold text-muted-foreground">
          💛 {WEARER || 'They'} chose to share this with family, so you can help when it matters. Sharing can be paused from the glasses anytime.
        </p>
      </main>
    </MotionConfig>
  )
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}
