import type { ComponentType, ReactNode } from 'react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export type Tint = 'peach' | 'sky' | 'sage' | 'lilac' | 'sun'

/** One titled card in its own color: a tinted icon, the title in the tint's deep tone, and an optional time stamp pill. */
export function Panel({ title, icon: Icon, tint = 'peach', stamp, aside, className, children }: {
  title: string
  icon?: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>
  tint?: Tint
  stamp?: string
  aside?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <Card
      className={cn('relative gap-5 rounded-[26px] border-border py-6 shadow-[var(--shadow-soft)]', className)}
      style={{ background: `linear-gradient(to bottom, color-mix(in oklab, var(--tint-${tint}) 90%, white) 0, var(--card) 120px)` }}
    >
      <div className="flex min-h-10 items-center justify-between gap-3 px-6">
        <h2 className="flex items-center gap-3 text-lg font-extrabold tracking-tight" style={{ color: `var(--ink-${tint})` }}>
          {Icon && (
            <span className="grid size-10 place-items-center rounded-2xl bg-white/80 shadow-sm" style={{ color: `var(--ink-${tint})` }}>
              <Icon className="size-5" aria-hidden />
            </span>
          )}
          {title}
        </h2>
        {stamp && (
          <span className="rounded-full bg-white/80 px-3 py-1 text-[13px] font-bold" style={{ color: `var(--ink-${tint})` }}>{stamp}</span>
        )}
        {aside}
      </div>
      <div className="px-6">{children}</div>
    </Card>
  )
}
