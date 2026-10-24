import type { CSSProperties, ReactNode } from 'react'
import { Briefcase, CalendarHeart, Bus, House, MapPin, Quote, Store, TreePine, UserRound } from 'lucide-react'
import { Skeleton } from '@/components/ui/skeleton'
import { Timeline, type TimelineEvent } from '@/components/ui/timeline'
import { placeLabel, upper } from '@/caption'
import { clock, lang, zone } from '@/format'
import { useNow } from '@/hooks'
import type { Item, Stay } from '@/thread'
import { Panel } from './Panel'
import { Photo } from './Photo'

const PLACE_ICON = { home: House, outside: TreePine, store: Store, office: Briefcase, transit: Bus, other: MapPin } as const
type PlaceKey = keyof typeof PLACE_ICON

/** Fills the timeline marker with a soft wash of the row's color. */
function Dot({ color, children }: { color: string; children: ReactNode }) {
  return <span className="grid size-full place-items-center" style={{ color, background: `color-mix(in oklab, ${color} 16%, white)` }}>{children}</span>
}

function PlaceIcon({ place }: { place: string }) {
  const key = (place in PLACE_ICON ? place : 'other') as PlaceKey
  const Icon = PLACE_ICON[key]
  return <Dot color={`var(--place-${key})`}><Icon size={14} strokeWidth={2.25} aria-hidden /></Dot>
}

function StayDetail({ stay }: { stay: Stay }) {
  const rooms = [...new Set(stay.frames.map(f => upper(f.cap.placeDetail)).filter(Boolean))]
  const scene = stay.frames.find(f => f.cap.scene)?.cap.scene
  return (
    <div className="flex flex-col gap-2.5">
      {scene && <p>{scene}</p>}
      {rooms.length > 0 && <p>Seen in: {rooms.join(', ')}</p>}
      <div className="flex flex-wrap gap-1.5">
        {stay.frames.slice(0, 12).map(f => (
          <div key={f.id} title={clock(f.ts)}>
            <Photo src={f.thumb} alt={f.cap.scene || `Frame at ${clock(f.ts)}`} className="h-14 w-[72px] rounded-xl" />
          </div>
        ))}
      </div>
    </div>
  )
}

const thumb = (src: string): ReactNode => (src ? <Photo src={src} alt="" className="h-[60px] w-20 rounded-xl" /> : undefined)

function toEvent(item: Item): TimelineEvent {
  if (item.type === 'fact') {
    return { id: item.key, at: item.at, actor: 'Said', title: `“${item.said}”`, meta: item.room ? `At ${upper(item.room)}` : undefined, icon: <Dot color="var(--ink-sun)"><Quote size={14} aria-hidden /></Dot>, detail: thumb(item.thumb) }
  }
  if (item.type === 'person') {
    return { id: item.key, at: item.at, actor: 'Met', title: [item.name, item.clothing].filter(Boolean).join(', '), icon: <Dot color="var(--ink-sage)"><UserRound size={14} aria-hidden /></Dot>, detail: thumb(item.thumb) }
  }
  const n = item.frames.length
  const span = item.start === item.at ? clock(item.at) : `${clock(item.start)}–${clock(item.at)}`
  return {
    id: item.key,
    at: item.at,
    title: placeLabel(item.place),
    meta: `${span} · ${n} photo${n === 1 ? '' : 's'}`,
    icon: <PlaceIcon place={item.place} />,
    detail: <StayDetail stay={item} />,
  }
}

/** The day as one thread, newest first. Long runs in one kind of place are a single row that opens to its pictures. */
export function Today({ items, ready }: { items: Item[]; ready: boolean }) {
  const now = useNow(15_000)
  return (
    <Panel title="Their day" icon={CalendarHeart} tint="sun">
      {!ready ? <div className="flex flex-col gap-4">{[0, 1, 2].map(i => <Skeleton key={i} className="h-12 w-full" />)}</div> : items.length === 0 ? (
        <p className="text-muted-foreground">Nothing yet today. Moments appear here once the glasses are on.</p>
      ) : (
        <div style={{ '--timeline-sticky-top': 'var(--header-h)', '--timeline-bg': 'var(--card)' } as CSSProperties}>
          <Timeline events={items.map(toEvent)} now={now} label="Their day" timeZone={zone} locale={lang} />
        </div>
      )}
    </Panel>
  )
}
