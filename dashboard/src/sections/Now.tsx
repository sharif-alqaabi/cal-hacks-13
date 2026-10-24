import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { placeLabel, upper } from '@/caption'
import { ago } from '@/format'
import { useNow } from '@/hooks'
import type { Moment } from '@/thread'
import { Panel } from './Panel'
import { Photo } from './Photo'

/** What the glasses see right now: the newest frame, where it is, and what's in view. */
export function Now({ moment, ready }: { moment?: Moment; ready: boolean }) {
  const now = useNow(1000)
  if (!ready) return <Panel title="Now"><Skeleton className="aspect-[4/3] w-full rounded-[10px]" /></Panel>
  if (!moment) return <Panel title="Now"><p className="text-muted-foreground">Waiting for the first frame from the glasses.</p></Panel>
  const { cap } = moment
  const where = [...new Set([upper(cap.placeDetail), placeLabel(cap.place)].filter(Boolean))].join(' · ')
  return (
    <Panel title="Now" aside={<span className="text-[13px] text-muted-foreground">{ago(moment.ts, now)}</span>}>
      <Photo src={moment.thumb} alt={cap.scene || 'Latest view from the glasses'} className="aspect-[4/3] w-full rounded-[10px]" />
      <p className="mt-3 text-lg font-medium leading-snug">{where}</p>
      {cap.scene && <p className="mt-1 text-muted-foreground">{cap.scene}</p>}
      {cap.objects.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5" aria-label="In view">
          {cap.objects.slice(0, 6).map(o => <Badge key={o} variant="outline" className="px-2.5 py-1 text-[13px] font-normal">{o}</Badge>)}
        </div>
      )}
      {cap.signs.length > 0 && <p className="mt-3 text-[13px] text-muted-foreground">Signs: {cap.signs.slice(0, 3).map(s => `“${s}”`).join(', ')}</p>}
    </Panel>
  )
}
