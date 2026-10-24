import type { ComponentType, ReactNode } from 'react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/** One wash and ink per section, so the name reads as a highlighter mark rather than a painted card. */
const TONE = {
  peach: { ink: 'text-[#9a3412]', wash: 'bg-[#ffedd5]', icon: 'text-[#c2410c]' },
  sky: { ink: 'text-[#1e4e79]', wash: 'bg-[#dbeafe]', icon: 'text-[#1d4ed8]' },
  sun: { ink: 'text-[#854d0e]', wash: 'bg-[#fef3c7]', icon: 'text-[#b45309]' },
  sage: { ink: 'text-[#166534]', wash: 'bg-[#dcfce7]', icon: 'text-[#15803d]' },
  lilac: { ink: 'text-[#6b3f72]', wash: 'bg-[#f6e8f4]', icon: 'text-[#9d4e86]' },
} as const

export type PanelTone = keyof typeof TONE

/** One titled card: a quiet icon and title, and an optional time stamp on the right. */
export function Panel({ title, icon: Icon, tone, stamp, aside, className, children }: {
  title: string
  icon?: ComponentType<{ className?: string; 'aria-hidden'?: boolean }>
  tone: PanelTone
  stamp?: string
  aside?: ReactNode
  className?: string
  children: ReactNode
}) {
  const color = TONE[tone]
  return (
    <Card className={cn('gap-4 rounded-2xl border-border py-5 shadow-[0_1px_2px_rgba(24,24,27,0.05),0_14px_34px_-18px_rgba(24,24,27,0.28)]', className)}>
      <div className="flex min-h-6 items-center justify-between gap-3 px-5">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          {Icon && <Icon className={cn('size-4', color.icon)} aria-hidden />}
          <span className={cn('rounded-md px-1.5 py-0.5', color.wash, color.ink)}>{title}</span>
        </h2>
        {stamp && <span className="text-[13px] text-muted-foreground">{stamp}</span>}
        {aside}
      </div>
      <div className="px-5">{children}</div>
    </Card>
  )
}
