import type { DataError } from '../../data/contracts'
import type { ViewId } from '../../lib/roles'
import { roleRoute, routeHref } from '../../lib/routes'
import { Notice } from '../ui/Notice'
import { Skeleton } from '../ui/Skeleton'
import { ViewHead } from './ViewHead'

/** Explicit loading / error / empty states. Never substitutes data. */
export function LoadingState() {
  return (
    <div className="view__state" aria-busy="true">
      <Notice icon="clock" title="Načítání" role="status"><Skeleton /><Skeleton /></Notice>
    </div>
  )
}

export function ErrorState({ error }: { readonly error: DataError }) {
  const unconfigured = error.code === 'backend-unconfigured'
  const title = unconfigured ? 'Data nejsou k dispozici' : error.code === 'not-found' ? 'Případ nebyl nalezen' : 'Data se nepodařilo načíst'
  return (
    <div className="view__state">
      <Notice tone={unconfigured ? 'warning' : 'danger'} icon={unconfigured ? 'database' : 'alert'} title={title} role="alert">
        {error.message}{unconfigured ? ' Pohled se zobrazí, až bude backend připojen.' : ''}
      </Notice>
    </div>
  )
}

export function EmptyState({ title, text }: { readonly title: string; readonly text: string }) {
  return (
    <div className="view__state">
      <Notice icon="queue" title={title} role="status">{text}</Notice>
    </div>
  )
}

/** Malformed case address: an honest explanation, never a substitute case. */
export function InvalidCaseState() {
  return (
    <div className="view__state">
      <Notice tone="danger" icon="alert" title="Neplatný odkaz na případ" role="alert">
        Adresa neobsahuje platné označení případu, proto se žádný případ nenačetl. Vraťte se na seznam a případ vyberte znovu.
      </Notice>
    </div>
  )
}

/** Recognized role, unsupported section: no default case or live view is substituted. */
export function InvalidViewState({ view, onReturn }: { readonly view: ViewId; readonly onReturn: () => void }) {
  return (
    <>
      <ViewHead id={`t-${view}`} icon="alert" title="Neplatný odkaz na pohled" />
      <div className="view__state">
        <Notice tone="danger" icon="alert" title="Neznámá sekce" role="alert">
          Tato sekce není k dispozici. Žádný případ se nenačetl.{' '}
          <a href={routeHref(roleRoute(view))} onClick={event => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
            event.preventDefault()
            onReturn()
          }}>Zpět na hlavní pohled</a>
        </Notice>
      </div>
    </>
  )
}
