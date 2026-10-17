const PROPS = ['position', 'top', 'left', 'right', 'width', 'overflow'] as const

/** Freezes the page under an open phone modal so touch scrolling cannot move it (or the browser
    toolbar). Only the touched inline properties are saved and restored, each separately.
    The returned release puts the page back; `restoreScroll: false` leaves scrolling to the caller
    (a route change owns its own scroll and focus). */
export function lockBodyScroll(): (restoreScroll: boolean) => void {
  const body = document.body
  const y = window.scrollY
  const saved = PROPS.map(prop => [prop, body.style.getPropertyValue(prop), body.style.getPropertyPriority(prop)] as const)
  body.style.setProperty('position', 'fixed')
  body.style.setProperty('top', `${-y}px`)
  body.style.setProperty('left', '0')
  body.style.setProperty('right', '0')
  body.style.setProperty('width', '100%')
  body.style.setProperty('overflow', 'hidden')
  let released = false
  return restoreScroll => {
    if (released) return
    released = true
    for (const [prop, value, priority] of saved) {
      if (value) body.style.setProperty(prop, value, priority)
      else body.style.removeProperty(prop)
    }
    if (restoreScroll) window.scrollTo({ top: y, left: 0, behavior: 'instant' })
  }
}
