import { Badge } from '@/components/ui/badge'
import { ago } from '@/format'
import { useNow } from '@/hooks'
import { cn } from '@/lib/utils'

const LIVE_MS = 120_000 // a still scene yields no new frames (duplicates are skipped), so 2 min of quiet is normal

export function StatusPill({ active, lastTs }: { active: boolean; lastTs: number | null }) {
  const now = useNow(1000)
  const live = active && lastTs !== null && now - lastTs <= LIVE_MS
  const label = !active
    ? 'Reconnecting…'
    : lastTs === null
      ? 'Connected · no frames yet'
      : `${live ? 'Live' : 'Idle'} · last frame ${ago(lastTs, now)}`
  return (
    <Badge variant="outline" className="h-8 gap-2 px-3 text-[13px] font-normal text-muted-foreground" role="status">
      <span className={cn('size-2 rounded-full', live ? 'breathe bg-live' : 'bg-muted-foreground/60')} aria-hidden />
      {label}
    </Badge>
  )
}
