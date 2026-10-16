import type { MouseEvent } from 'react'
import type { ListRole } from '../../lib/routes'

/** Plain primary click without modifiers: the app handles it. Anything else (new tab, copy link,
    middle click) keeps the native link behaviour, so every href must stay valid on its own. */
export function isPlainActivation(event: MouseEvent<Element>): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && !event.defaultPrevented
}

/** Stable, role-distinct id of a list row's link; list focus restoration targets it. */
export const caseRowId = (role: ListRole, caseId: string) => `case-row-${role}-${caseId}`

const INTERACTIVE = 'a, button, input, select, textarea, summary, label, [role="button"]'

/** Pointer convenience for whole-row selection. Keyboard and assistive tech use the native row link
    (one tab stop per row). Controls, modifier clicks and text selection are left alone. */
export function rowActivation(event: MouseEvent<HTMLTableRowElement>, open: () => void) {
  if (!isPlainActivation(event)) return
  if (event.target instanceof Element && event.target.closest(INTERACTIVE)) return
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed && event.currentTarget.contains(selection.anchorNode)) return
  open()
}
