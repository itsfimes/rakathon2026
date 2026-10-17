import { useLayoutEffect } from 'react'
import type { RefObject } from 'react'

/** Publishes the measured heights of the sticky mode strip and app bar as CSS variables,
    so skip/deep-link targets can clear them (scroll-margin) at any text size. */
export function useStickyOffsets(strip: RefObject<HTMLElement | null>, appbar: RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const root = document.documentElement
    const update = () => {
      root.style.setProperty('--mode-strip-h', `${strip.current?.offsetHeight ?? 0}px`)
      root.style.setProperty('--appbar-h', `${appbar.current?.offsetHeight ?? 0}px`)
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    if (strip.current) observer.observe(strip.current)
    if (appbar.current) observer.observe(appbar.current)
    return () => observer.disconnect()
  }, [strip, appbar])
}
