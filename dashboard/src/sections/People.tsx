import { AnimatePresence, motion } from 'motion/react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Skeleton } from '@/components/ui/skeleton'
import { ago } from '@/format'
import { EASE, useNow } from '@/hooks'
import { Panel } from './Panel'

export interface PersonRow { name: string; clothingNote: string; lastSeenTs: bigint }

export function People({ people, ready }: { people: PersonRow[]; ready: boolean }) {
  const now = useNow(5000)
  return (
    <Panel title="People">
      {!ready ? <Skeleton className="h-12 w-full" /> : people.length === 0 ? (
        <p className="text-muted-foreground">No one introduced yet. Say “this is my brother Sam” to the glasses.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {people.map(p => (
              <motion.li
                key={p.name}
                layout
                className="flex items-center gap-3"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.22, ease: EASE }}
              >
                <Avatar className="size-10">
                  <AvatarFallback className="bg-raised text-sm font-medium">{p.name.slice(0, 1).toUpperCase()}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{p.name}</p>
                  <p className="truncate text-[13px] text-muted-foreground">{p.clothingNote}</p>
                </div>
                <span className="shrink-0 text-[13px] text-muted-foreground">{ago(Number(p.lastSeenTs), now)}</span>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Panel>
  )
}
