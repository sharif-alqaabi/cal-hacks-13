import { AnimatePresence, motion } from 'motion/react'
import { MessageCircleQuestion } from 'lucide-react'
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
    <Panel title="What they asked" icon={MessageCircleQuestion} tint="sky" stamp={latest && ago(Number(latest.ts), now)}>
      {!ready ? <Skeleton className="h-20 w-full" /> : !latest ? <p className="text-muted-foreground">No questions yet. When they ask the glasses something, you'll see it here.</p> : (
        <div aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={String(latest.id)}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.22, ease: EASE }}
            >
              <p className="inline-block rounded-2xl rounded-bl-md bg-[var(--ink-sky)] px-4 py-2.5 text-[15px] font-semibold text-white">“{latest.question}”</p>
              <div className="mt-3 flex items-start gap-4">
                <p className="flex-1 rounded-2xl rounded-tl-md bg-[var(--tint-sky)] px-4 py-3 text-[16px] leading-snug">{latest.answer}</p>
                {latest.thumbUrl && <Photo src={latest.thumbUrl} alt="" className="size-20 rounded-2xl" />}
              </div>
            </motion.div>
          </AnimatePresence>
          <ul className="mt-5 divide-y divide-border border-t border-border">
            <AnimatePresence initial={false}>
              {earlier.slice(0, 4).map(r => (
                <motion.li
                  key={String(r.id)}
                  layout
                  className="flex items-baseline gap-3 py-2.5 text-sm"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.22, ease: EASE }}
                >
                  <span className="size-1.5 shrink-0 translate-y-[-2px] rounded-full bg-[var(--ink-sky)]/60" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-foreground/80">{r.question}</span>
                  <span className="shrink-0 font-semibold text-[var(--ink-sky)]/70">{ago(Number(r.ts), now)}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ul>
        </div>
      )}
    </Panel>
  )
}
