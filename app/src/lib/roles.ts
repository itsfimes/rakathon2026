import type { IconName } from '../icons/paths'
import { routeFromLocation } from './routes'

/** Four role views plus the separate design-system tool view (not a role). */
export const VIEWS = ['koordinator', 'pacient', 'lekar', 'mdt', 'specimen'] as const
export type ViewId = (typeof VIEWS)[number]
export const DEFAULT_VIEW: ViewId = 'koordinator'

export const VIEW_LINKS: readonly { readonly id: ViewId; readonly href: string; readonly label: string; readonly icon: IconName }[] = [
  { id: 'koordinator', href: '#koordinator', label: 'Koordinátor', icon: 'queue' },
  { id: 'pacient', href: '#pacient', label: 'Pacient', icon: 'person' },
  { id: 'lekar', href: '#lekar', label: 'Lékař', icon: 'steth' },
  { id: 'mdt', href: '#mdt', label: 'MDT', icon: 'team' },
]

export function isView(value: string): value is ViewId {
  return (VIEWS as readonly string[]).includes(value)
}

/** Compatibility projection of the complete route; URL values never select a data mode. */
export function viewFromLocation(location: Pick<Location, 'hash' | 'search'>): ViewId {
  return routeFromLocation(location).view
}
