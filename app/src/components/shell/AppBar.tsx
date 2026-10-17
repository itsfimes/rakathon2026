import { forwardRef } from 'react'
import { Icon } from '../../icons/Icon'

interface AppBarProps {
  readonly onLogout?: (() => void) | undefined
  readonly loggingOut?: boolean | undefined
  readonly onExitDemo?: (() => void) | undefined
  readonly onResetDemo?: (() => void) | undefined
  readonly demo?: boolean | undefined
}

export const AppBar = forwardRef<HTMLElement, AppBarProps>(function AppBar({ onLogout, loggingOut, onExitDemo, onResetDemo, demo }, ref) {
  return (
    <header ref={ref} className="appbar">
      <div className="appbar__row">
        <p className="brand"><Icon name="case" />Atlas</p>
        {demo && onResetDemo && (
          <span className="appbar__actions">
            <button type="button" className="btn btn--secondary" onClick={onResetDemo}>Obnovit demo</button>
          </span>
        )}
        {onExitDemo && (
          <span className="appbar__actions">
            <button type="button" className="btn btn--secondary" onClick={onExitDemo}>Ukončit ukázku</button>
          </span>
        )}
        {onLogout && (
          <span className="appbar__actions">
            <button type="button" className="btn btn--secondary" onClick={onLogout} disabled={loggingOut}>
              {loggingOut ? 'Odhlašování…' : 'Odhlásit'}
            </button>
          </span>
        )}
      </div>
    </header>
  )
})
