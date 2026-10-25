import { ago } from '@/format'
import { useNow } from '@/hooks'
import { cn } from '@/lib/utils'

const SHARING_MS = 5 * 60_000 // a still scene yields no new frames (duplicates are skipped), so a few quiet minutes still count as on

/** Sharing reads as on while a photo arrived in the last 5 minutes, and off otherwise (see README). */
export function useSharing(lastTs: number | null) {
  const now = useNow(5000)
  return lastTs !== null && now - lastTs <= SHARING_MS
}

export function StatusPill({ active, lastTs }: { active: boolean; lastTs: number | null }) {
  const now = useNow(1000)
  const recent = useSharing(lastTs)
  const sharing = active && recent
  const detail = !active || lastTs === null ? '' : `${sharing ? 'updated' : 'last update'} ${ago(lastTs, now)}`
  return (
    <span
      role="status"
      className="inline-flex h-8 items-center gap-2 rounded-full border border-border bg-card px-3 text-[13px] font-medium"
    >
      <span className={cn('size-2 rounded-full', sharing ? 'breathe bg-live' : 'bg-muted-foreground/50')} aria-hidden />
      {!active ? 'Connecting…' : sharing ? 'Sharing is on' : 'Sharing is off'}
      {detail && <span className="hidden font-normal text-muted-foreground sm:inline">· {detail}</span>}
    </span>
  )
}
