import { ShieldCheck } from 'lucide-react'
import { HoldToConfirm } from '@/components/ui/hold-to-confirm'
import { wearer } from '@/wearer'
import { Panel } from './Panel'

/** Sharing is the wearer's choice: the switch shows it's on, and only the glasses can pause it (display only for now, see
 *  README). The two holds need no modal: a press has to last, so a stray tap does nothing. */
export function Privacy({ sharing, onForgetRecent, onForgetAll }: { sharing: boolean; onForgetRecent: () => void; onForgetAll: () => void }) {
  return (
    <Panel title="Privacy" icon={ShieldCheck} tint="lilac">
      <div className="flex flex-col gap-3">
        <div className={`flex items-center gap-3 rounded-2xl p-4 ${sharing ? 'bg-[var(--tint-sage)]' : 'bg-muted'}`}>
          <div className="min-w-0 flex-1">
            <p className={`font-extrabold ${sharing ? 'text-[var(--ink-sage)]' : 'text-foreground/70'}`}>{sharing ? 'Sharing is on' : 'Sharing is off'}</p>
            <p className="text-[13px] text-foreground/75">
              {wearer('They')} chose to share their day with family, and can pause it from the glasses anytime.
            </p>
          </div>
          <span
            role="switch"
            aria-checked={sharing}
            aria-readonly
            aria-label="Sharing, controlled from the glasses"
            title="Only the wearer can pause sharing, from the glasses"
            className={`relative h-7 w-12 shrink-0 rounded-full ${sharing ? 'bg-live' : 'bg-muted-foreground/40'}`}
          >
            <span className={`absolute top-1 size-5 rounded-full bg-white shadow transition-[left] ${sharing ? 'left-6' : 'left-1'}`} />
          </span>
        </div>
        <p className="mt-1 text-sm font-semibold text-foreground/80">Anything shared can also be forgotten, by them or by you.</p>
        <HoldToConfirm onConfirm={onForgetRecent} duration={1500} confirmLabel="Last 10 minutes forgotten">
          Hold to forget the last 10 minutes
        </HoldToConfirm>
        <HoldToConfirm onConfirm={onForgetAll} duration={2500} confirmLabel="Everything forgotten">
          Hold to forget everything
        </HoldToConfirm>
      </div>
    </Panel>
  )
}
