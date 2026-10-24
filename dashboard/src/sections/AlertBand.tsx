import { AnimatePresence, motion } from 'motion/react'
import { BellRing } from 'lucide-react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ago } from '@/format'
import { EASE, useNow } from '@/hooks'
import { Photo } from './Photo'

export interface AlertRow { id: bigint; ts: bigint; kind: string; note: string }

const LABEL: Record<string, string> = { help: 'They asked for help', lost: "They said they're lost" }

/** Open alerts, newest first. Each opens from zero height and pushes the page down; resolving closes it the same way. */
export function AlertBand({ alerts, thumb, onResolve }: { alerts: AlertRow[]; thumb: string; onResolve: (id: bigint) => void }) {
  const now = useNow(1000)
  return (
    <AnimatePresence initial={false}>
      {alerts.map(a => (
        <motion.div
          key={String(a.id)}
          className="-m-1 overflow-hidden p-1"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.3, ease: EASE }}
        >
          <Alert className="mb-4 grid-cols-1 gap-3 rounded-[24px] border-alert/30 bg-[color-mix(in_oklab,var(--alert)_8%,white)] p-6 shadow-[var(--shadow-soft)] text-foreground">
            <div className="flex flex-wrap items-center gap-x-2 text-base font-bold text-alert">
              <BellRing className="size-4" aria-hidden />
              {LABEL[a.kind] ?? 'Alert'}
              <span className="font-medium text-muted-foreground">· {ago(Number(a.ts), now)}</span>
            </div>
            <p className="whitespace-pre-wrap text-lg leading-snug">{a.note}</p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              {thumb && (
                <div className="flex items-center gap-3 text-[13px] text-muted-foreground">
                  <Photo src={thumb} alt="" className="h-[60px] w-20 rounded-xl" />
                  Last view from the glasses
                </div>
              )}
              <Button
                onClick={() => onResolve(a.id)}
                className="h-12 w-full rounded-full bg-alert px-7 text-base font-bold text-white hover:bg-alert/90 sm:ml-auto sm:w-auto"
              >
                I'm on it
              </Button>
            </div>
          </Alert>
        </motion.div>
      ))}
    </AnimatePresence>
  )
}
