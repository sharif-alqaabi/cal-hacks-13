import { Eye } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { placeLabel, upper } from '@/caption'
import { ago } from '@/format'
import { useNow } from '@/hooks'
import type { Moment } from '@/thread'
import { Panel } from './Panel'
import { Photo } from './Photo'

/** What the glasses see right now: the newest frame, where it is, and what's in view. */
const PLACE_INK = { home: 1, outside: 1, store: 1, office: 1, transit: 1 }

export function Now({ moment, ready }: { moment?: Moment; ready: boolean }) {
  const now = useNow(1000)
  if (!ready) return <Panel title="Right now" icon={Eye} tint="peach"><Skeleton className="aspect-[4/3] w-full rounded-[18px]" /></Panel>
  if (!moment) return <Panel title="Right now" icon={Eye} tint="peach"><p className="text-muted-foreground">Nothing to show yet. A picture appears here once the glasses are on.</p></Panel>
  const { cap } = moment
  const where = [...new Set([upper(cap.placeDetail), placeLabel(cap.place)].filter(Boolean))].join(' · ')
  return (
    <Panel title="Right now" icon={Eye} tint="peach" stamp={ago(moment.ts, now)}>
      <Photo src={moment.thumb} alt={cap.scene || 'Latest view from the glasses'} className="aspect-[4/3] w-full rounded-[18px]" />
      <p className="mt-4 text-xl font-extrabold leading-snug" style={{ color: `var(--place-${cap.place in PLACE_INK ? cap.place : 'other'})` }}>{where}</p>
      {cap.scene && <p className="mt-1.5 leading-relaxed text-foreground/75">{cap.scene}</p>}
      {cap.objects.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2" aria-label="In view">
          {cap.objects.slice(0, 6).map(o => <Badge key={o} variant="secondary" className="rounded-full bg-[var(--tint-peach)] px-3 py-1 text-[13px] font-semibold text-[var(--ink-peach)]">{o}</Badge>)}
        </div>
      )}
      {cap.signs.length > 0 && <p className="mt-3 text-[13px] text-muted-foreground">Signs nearby: {cap.signs.slice(0, 3).map(s => `“${s}”`).join(', ')}</p>}
    </Panel>
  )
}
