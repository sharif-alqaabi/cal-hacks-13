import { AnimatePresence, motion } from 'motion/react'
import { ImageOff } from 'lucide-react'
import { EASE, useLoadedSrc } from '@/hooks'
import { cn } from '@/lib/utils'

/** A frame thumbnail: fades in once loaded, crossfades when the source changes, and shows a plain tile if it can't load. */
export function Photo({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const { shown, failed } = useLoadedSrc(src)
  return (
    <div className={cn('relative shrink-0 overflow-hidden bg-raised', className)}>
      <AnimatePresence initial={false}>
        {shown && (
          <motion.img
            key={shown}
            src={shown}
            alt={alt}
            className="absolute inset-0 h-full w-full object-cover"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22, ease: EASE }}
          />
        )}
      </AnimatePresence>
      {(failed || !src) && (
        <div className="absolute inset-0 grid place-items-center text-muted-foreground" role="img" aria-label="No picture">
          <ImageOff className="size-5" aria-hidden />
        </div>
      )}
    </div>
  )
}
