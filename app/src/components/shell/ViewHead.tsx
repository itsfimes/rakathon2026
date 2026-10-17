import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

interface ViewHeadProps {
  readonly id: string
  readonly icon: IconName
  readonly title: ReactNode
}

/** View heading; focusable (tabIndex -1) so role navigation can move focus to it. */
export function ViewHead({ id, icon, title }: ViewHeadProps) {
  return (
    <div className="view__head">
      <h1 className="view__title" id={id} tabIndex={-1}><Icon name={icon} />{title}</h1>
    </div>
  )
}
