import { AnimatePresence, motion } from 'motion/react'
import { BellRing } from 'lucide-react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { ago } from '@/format'
import { EASE, useNow } from '@/hooks'
import { Photo } from './Photo'

export interface AlertRow { id: bigint; ts: bigint; kind: string; note: string }

const LABEL: Record<string, string> = { help: 'Needs help', lost: "Says they're lost" }

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
          <Alert className="mb-4 grid-cols-1 gap-3 rounded-[14px] border-alert/40 bg-[color-mix(in_oklab,var(--alert)_12%,var(--background))] p-5 text-foreground">
            <div className="flex flex-wrap items-center gap-x-2 text-sm font-semibold uppercase tracking-[0.06em] text-alert">
              <BellRing className="size-4" aria-hidden />
              {LABEL[a.kind] ?? 'Alert'}
              <span className="font-normal normal-case tracking-normal text-muted-foreground">· {ago(Number(a.ts), now)}</span>
            </div>
            <p className="whitespace-pre-wrap text-lg leading-snug">{a.note}</p>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              {thumb && (
                <div className="flex items-center gap-3 text-[13px] text-muted-foreground">
                  <Photo src={thumb} alt="" className="h-[54px] w-[72px] rounded-lg" />
                  Last view from the glasses
                </div>
              )}
              <Button
                onClick={() => onResolve(a.id)}
                className="h-12 w-full bg-alert px-6 text-base font-semibold text-[#1a0705] hover:bg-alert/90 sm:ml-auto sm:w-auto"
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
