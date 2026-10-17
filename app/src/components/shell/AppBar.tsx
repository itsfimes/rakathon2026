import { forwardRef, useId, useRef } from 'react'
import { Icon } from '../../icons/Icon'
import { VIEW_LINKS } from '../../lib/roles'
import type { ViewId } from '../../lib/roles'
import { formatDate } from '../../lib/format'

interface AppBarProps {
  readonly view: ViewId
  readonly asOf: string | null
  readonly demo: boolean
  readonly onLogout?: (() => void) | undefined
  readonly loggingOut?: boolean | undefined
}

const VIEW_LABEL = new Map<ViewId, string>(VIEW_LINKS.map(item => [item.id, item.label]))

export const AppBar = forwardRef<HTMLElement, AppBarProps>(function AppBar({ view, asOf, demo, onLogout, loggingOut }, ref) {
  const confirmRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  return (
    <header ref={ref} className="appbar">
      <div className="appbar__row">
        <p className="brand"><Icon name="case" />Atlas</p>
        <p className="appbar__role"><Icon name="person" small />{VIEW_LABEL.get(view) ?? view}</p>
        {asOf && <span className="appbar__date">{demo ? 'Stav k' : 'Načteno'} {formatDate(asOf)}</span>}
        {onLogout && <button type="button" className="appbar__logout" onClick={() => confirmRef.current?.showModal()} disabled={loggingOut} aria-haspopup="dialog">
          {loggingOut ? 'Odhlašování…' : 'Odhlásit'}
        </button>}
        {onLogout && <dialog ref={confirmRef} className="source-dialog logout-confirm" aria-labelledby={titleId}
          onClose={event => { if (event.currentTarget.returnValue === 'confirm') onLogout(); event.currentTarget.returnValue = '' }}>
          <form method="dialog" className="source-dialog__body">
            <h2 className="source-dialog__title" id={titleId}>Opravdu se chcete odhlásit?</h2>
            <div className="btn-row logout-confirm__actions">
              <button type="submit" value="cancel" className="btn btn--secondary" autoFocus>Zrušit</button>
              <button type="submit" value="confirm" className="btn">Odhlásit se</button>
            </div>
          </form>
        </dialog>}
      </div>
    </header>
  )
})
