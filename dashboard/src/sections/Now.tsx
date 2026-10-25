import { Eye } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { placeLabel, upper } from '@/caption'
import { ago } from '@/format'
import { useLiveFrame, useNow } from '@/hooks'
import type { Moment } from '@/thread'
import { Panel } from './Panel'
import { Photo } from './Photo'

/** What the glasses see right now: the live camera feed (or the newest captioned frame), where it is, and what's in view. */
export function Now({ moment, ready }: { moment?: Moment; ready: boolean }) {
  const now = useNow(1000)
  const frame = useLiveFrame()
  const live = frame !== null && now - frame.at < 3000
  const view = live
    ? <img src={frame.src} alt="Live view from the glasses" className="aspect-[4/3] w-full rounded-xl bg-raised object-cover" />
    : null
  if (!ready) return <Panel title="Right now" icon={Eye} tone="peach"><Skeleton className="aspect-[4/3] w-full rounded-xl" /></Panel>
  if (!moment) return <Panel title="Right now" icon={Eye} tone="peach" stamp={live ? 'Live' : undefined}>{view ?? <p className="text-muted-foreground">Nothing to show yet. A picture appears here once the glasses are on.</p>}</Panel>
  const { cap } = moment
  const where = [...new Set([upper(cap.placeDetail), placeLabel(cap.place)].filter(Boolean))].join(' · ')
  return (
    <Panel title="Right now" icon={Eye} tone="peach" stamp={live ? 'Live' : ago(moment.ts, now)}>
      {view ?? <Photo src={moment.thumb} alt={cap.scene || 'Latest view from the glasses'} className="aspect-[4/3] w-full rounded-xl" />}
      <p className="mt-4 text-lg font-semibold leading-snug">{where}</p>
      {cap.scene && <p className="mt-1.5 leading-relaxed text-muted-foreground">{cap.scene}</p>}
      {cap.objects.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2" aria-label="In view">
          {cap.objects.slice(0, 6).map(o => <Badge key={o} variant="outline" className="rounded-full px-3 py-1 text-[13px] font-normal text-foreground/80">{o}</Badge>)}
        </div>
      )}
      {cap.signs.length > 0 && <p className="mt-3 text-[13px] text-muted-foreground">Signs nearby: {cap.signs.slice(0, 3).map(s => `“${s}”`).join(', ')}</p>}
    </Panel>
  )
}
