import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

interface PanelProps {
  readonly id: string
  readonly title: ReactNode
  readonly icon?: IconName
  readonly meta?: ReactNode
  readonly aside?: ReactNode
  readonly as?: 'section' | 'article'
  /** Lets code move focus to the title (tabIndex -1), e.g. after selecting a row on a phone. */
  readonly focusableTitle?: boolean
  readonly children: ReactNode
}

/** Bordered section with a sunken head (title, optional meta line and trailing tag). */
export function Panel({ id, title, icon, meta, aside, as: Tag = 'section', focusableTitle = false, children }: PanelProps) {
  return (
    <Tag className="panel" aria-labelledby={id}>
      <div className="panel__head">
        <h2 className="panel__title" id={id} tabIndex={focusableTitle ? -1 : undefined}>{icon && <Icon name={icon} />}{title}</h2>
        {aside}
      </div>
      {children}
    </Tag>
  )
}

export function PanelBody({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return <div className={className ? `panel__body ${className}` : 'panel__body'}>{children}</div>
}
