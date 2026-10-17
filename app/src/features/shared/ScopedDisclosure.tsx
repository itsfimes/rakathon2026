import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'
import { useDetailScope } from './detailScope'

interface ScopedDisclosureProps {
  readonly summary: string
  readonly icon?: IconName
  readonly children: ReactNode
}

/** Native <details> for case detail. Closed again on every scope change; while the case is not
    current the body is not rendered at all and the summary explains why. */
export function ScopedDisclosure({ summary, icon = 'file', children }: ScopedDisclosureProps) {
  const { key, live } = useDetailScope()
  if (!live) {
    return (
      <div className="disclosure disclosure--pending">
        <p><Icon name="clock" />{summary} · podrobnosti se zobrazí po načtení aktuálního stavu</p>
      </div>
    )
  }
  return (
    <details key={key} className="disclosure">
      <summary><Icon name={icon} /><span className="disclosure__summary-text">{summary}</span><span className="disclosure__marker"><Icon name="chevron" small /></span></summary>
      <div className="disclosure__body">{children}</div>
    </details>
  )
}
