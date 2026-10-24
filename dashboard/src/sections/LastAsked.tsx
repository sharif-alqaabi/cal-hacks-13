import { AnimatePresence, motion } from 'motion/react'
import { Skeleton } from '@/components/ui/skeleton'
import { ago } from '@/format'
import { EASE, useNow } from '@/hooks'
import { Panel } from './Panel'
import { Photo } from './Photo'

export interface RecallRow { id: bigint; ts: bigint; question: string; answer: string; thumbUrl: string }

/** The newest question and the answer the wearer heard; the four before it as one-liners. */
export function LastAsked({ recalls, ready }: { recalls: RecallRow[]; ready: boolean }) {
  const now = useNow(5000)
  const [latest, ...earlier] = recalls
  return (
    <Panel title="Last asked" aside={latest && <span className="text-[13px] text-muted-foreground">{ago(Number(latest.ts), now)}</span>}>
      {!ready ? <Skeleton className="h-20 w-full" /> : !latest ? <p className="text-muted-foreground">Nothing asked yet.</p> : (
        <div aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={String(latest.id)}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.22, ease: EASE }}
            >
              <p className="text-sm text-muted-foreground">“{latest.question}”</p>
              <div className="mt-2 flex items-start gap-4">
                <p className="flex-1 text-lg leading-snug">{latest.answer}</p>
                {latest.thumbUrl && <Photo src={latest.thumbUrl} alt="" className="size-20 rounded-lg" />}
              </div>
            </motion.div>
          </AnimatePresence>
          <ul className="mt-4 divide-y divide-border border-t border-border">
            <AnimatePresence initial={false}>
              {earlier.slice(0, 4).map(r => (
                <motion.li
                  key={String(r.id)}
                  layout
                  className="flex items-baseline gap-3 py-2 text-[13px]"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.22, ease: EASE }}
                >
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{r.question}</span>
                  <span className="shrink-0 text-muted-foreground/70">{ago(Number(r.ts), now)}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </Panel>
  )
}
