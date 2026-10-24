import { AnimatePresence, motion } from 'motion/react'
import { Heart } from 'lucide-react'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Skeleton } from '@/components/ui/skeleton'
import { ago } from '@/format'
import { EASE, useNow } from '@/hooks'
import { Panel } from './Panel'

export interface PersonRow { name: string; clothingNote: string; lastSeenTs: bigint }

export function People({ people, ready }: { people: PersonRow[]; ready: boolean }) {
  const now = useNow(5000)
  return (
    <Panel title="Friends & family" icon={Heart} tone="sage">
      {!ready ? <Skeleton className="h-12 w-full" /> : people.length === 0 ? (
        <p className="text-muted-foreground">No one introduced yet. They can say “this is my brother Sam” to the glasses.</p>
      ) : (
        <ul className="flex flex-col gap-4">
          <AnimatePresence initial={false}>
            {people.map(p => (
              <motion.li
                key={p.name}
                layout
                className="flex items-start gap-3"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.22, ease: EASE }}
              >
                <Avatar className="size-10">
                  <AvatarFallback className="bg-raised text-sm font-medium text-foreground/80">{p.name.slice(0, 1).toUpperCase()}</AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{p.name}</p>
                  <p className="line-clamp-2 text-[13px] text-muted-foreground">{p.clothingNote}</p>
                  <p className="text-[12px] text-muted-foreground/70">Saw them {ago(Number(p.lastSeenTs), now)}</p>
                </div>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Panel>
  )
}
