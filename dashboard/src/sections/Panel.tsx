import type { ReactNode } from 'react'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

/** One titled card. Every section uses it, so spacing and the label style stay identical. */
export function Panel({ title, aside, className, children }: { title: string; aside?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <Card className={cn('gap-4 rounded-[14px] border-border py-5 shadow-none', className)}>
      <div className="flex min-h-5 items-center justify-between gap-3 px-5">
        <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</h2>
        {aside}
      </div>
      <div className="px-5">{children}</div>
    </Card>
  )
}
