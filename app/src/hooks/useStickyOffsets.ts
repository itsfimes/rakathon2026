import { useLayoutEffect } from 'react'
import type { RefObject } from 'react'

/** Publishes the measured height of the sticky app bar as a CSS variable,
    so skip/deep-link targets can clear it (scroll-margin) at any text size. */
export function useStickyOffsets(appbar: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const root = document.documentElement
    const update = () => {
      root.style.setProperty('--appbar-h', `${appbar.current?.offsetHeight ?? 0}px`)
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    if (appbar.current) observer.observe(appbar.current)
    return () => observer.disconnect()
  }, [appbar])
}
