import { forwardRef } from 'react'
import type { RefObject } from 'react'
import { Icon } from '../../icons/Icon'
import { SegmentedLinks } from '../ui/Segmented'
import { isView, VIEW_LINKS } from '../../lib/roles'
import type { ViewId } from '../../lib/roles'
import { formatDate } from '../../lib/format'

interface AppBarProps {
  readonly view: ViewId
  readonly asOf: string | null
  readonly demo: boolean
  readonly assistantOpen: boolean
  readonly onAssistant: () => void
  readonly assistantRef: RefObject<HTMLButtonElement | null>
  /** Role link activation: always the role's list (or view), even from that role's own detail. */
  readonly onRole: (view: ViewId) => void
  /** In-page jump to the disclaimer; never rewrites the route. */
  readonly onAbout: () => void
}

export const AppBar = forwardRef<HTMLElement, AppBarProps>(function AppBar({ view, asOf, demo, assistantOpen, onAssistant, assistantRef, onRole, onAbout }, ref) {
  return (
    <header ref={ref} className="appbar">
      <div className="appbar__row">
        <p className="brand"><Icon name="case" />Sdílený případ</p>
        <a className="demo-tag" href="#o-ukazce" onClick={event => {
          if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
          event.preventDefault()
          onAbout()
        }}><Icon name="info" small />{demo ? 'Ukázka · smyšlená data' : 'O aplikaci'}</a>
        <nav className="roles" aria-label="Pohled podle role">
          <div className="roles__scroll">
            <SegmentedLinks items={VIEW_LINKS} current={view} onActivate={id => { if (isView(id)) onRole(id) }} />
          </div>
        </nav>
        {asOf && <span className="appbar__date">{demo ? 'Stav k' : 'Načteno'} {formatDate(asOf)}</span>}
        <button type="button" ref={assistantRef} className="appbar__assist" aria-haspopup="dialog" aria-expanded={assistantOpen} onClick={onAssistant}>
          <Icon name="help" small />Asistent
        </button>
      </div>
    </header>
  )
})
