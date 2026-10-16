import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

interface DisclosureProps {
  readonly summary: ReactNode
  readonly icon?: IconName
  readonly open?: boolean
  readonly onToggle?: (open: boolean) => void
  readonly children: ReactNode
}

/** Native <details>; keyboard and no-script friendly. */
export function Disclosure({ summary, icon = 'help', open, onToggle, children }: DisclosureProps) {
  return (
    <details className="disclosure" open={open} onToggle={onToggle ? event => onToggle(event.currentTarget.open) : undefined}>
      <summary><Icon name={icon} /><span className="disclosure__summary-text">{summary}</span><span className="disclosure__marker"><Icon name="chevron" small /></span></summary>
      {children}
    </details>
  )
}
