import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import { roleRoute, routeHref } from '../../lib/routes'
import type { ListRole, Route } from '../../lib/routes'
import { isPlainActivation } from './routeActivation'

interface RouteLinkProps {
  readonly route: Route
  readonly onNavigate: (route: Route) => void
  readonly id?: string
  readonly className?: string
  /** Marks the link for the page being shown (aria-current="page"). */
  readonly current?: boolean
  readonly children: ReactNode
}

/** Real link to an app route; plain clicks navigate in place, modified clicks stay native. */
export function RouteLink({ route, onNavigate, id, className, current = false, children }: RouteLinkProps) {
  return (
    <a id={id} className={className} href={routeHref(route)} aria-current={current ? 'page' : undefined}
      onClick={event => { if (!isPlainActivation(event)) return; event.preventDefault(); onNavigate(route) }}>
      {children}
    </a>
  )
}

/** Return link shown above every clinician detail, outside loading/error gates. */
export function BackToList({ role, label, onReturn }: { readonly role: ListRole; readonly label: string; readonly onReturn: () => void }) {
  return (
    <p className="back-link">
      <a href={routeHref(roleRoute(role))}
        onClick={event => { if (!isPlainActivation(event)) return; event.preventDefault(); onReturn() }}>
        <Icon name="arrow" small />{label}
      </a>
    </p>
  )
}
