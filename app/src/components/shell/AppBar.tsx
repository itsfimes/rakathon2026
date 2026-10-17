import { forwardRef } from 'react'
import type { RefObject } from 'react'
import { Icon } from '../../icons/Icon'
import { VIEW_LINKS } from '../../lib/roles'
import type { ViewId } from '../../lib/roles'
import { formatDate } from '../../lib/format'

interface AppBarProps {
  readonly view: ViewId
  readonly asOf: string | null
  readonly demo: boolean
  readonly assistantOpen: boolean
  readonly onAssistant: () => void
  readonly assistantRef: RefObject<HTMLButtonElement | null>
}

const VIEW_LABEL = new Map<ViewId, string>(VIEW_LINKS.map(item => [item.id, item.label]))

export const AppBar = forwardRef<HTMLElement, AppBarProps>(function AppBar({ view, asOf, demo, assistantOpen, onAssistant, assistantRef }, ref) {
  return (
    <header ref={ref} className="appbar">
      <div className="appbar__row">
        <p className="brand"><Icon name="case" />Atlas</p>
        <p className="appbar__role"><Icon name="person" small />Pohled: {VIEW_LABEL.get(view) ?? view}</p>
        {asOf && <span className="appbar__date">{demo ? 'Stav k' : 'Načteno'} {formatDate(asOf)}</span>}
        <button type="button" ref={assistantRef} className="appbar__assist" aria-haspopup="dialog" aria-expanded={assistantOpen} onClick={onAssistant}>
          <Icon name="help" small />Asistent
        </button>
      </div>
    </header>
  )
})
