import { HoldToConfirm } from '@/components/ui/hold-to-confirm'
import { Panel } from './Panel'

/** Two holds, no modal: a press has to last, so a stray tap does nothing. */
export function Privacy({ onForgetRecent, onForgetAll }: { onForgetRecent: () => void; onForgetAll: () => void }) {
  return (
    <Panel title="Privacy">
      <div className="flex flex-col gap-3">
        <HoldToConfirm onConfirm={onForgetRecent} duration={1500} confirmLabel="Last 10 minutes forgotten">
          Hold to forget the last 10 minutes
        </HoldToConfirm>
        <HoldToConfirm onConfirm={onForgetAll} duration={2500} confirmLabel="Everything forgotten">
          Hold to forget everything
        </HoldToConfirm>
        <p className="text-[13px] text-muted-foreground">
          Removes the pictures and what was remembered from them. Forgetting everything also clears people, alerts and questions.
        </p>
      </div>
    </Panel>
  )
}
