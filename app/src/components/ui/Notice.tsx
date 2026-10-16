import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

interface NoticeProps {
  readonly tone?: 'neutral' | 'info' | 'warning' | 'danger' | 'success'
  readonly icon: IconName
  readonly title: ReactNode
  readonly children?: ReactNode
  readonly role?: 'note' | 'status' | 'alert'
}

export function Notice({ tone = 'neutral', icon, title, children, role }: NoticeProps) {
  return (
    <div className={tone === 'neutral' ? 'notice' : `notice notice--${tone}`} role={role}>
      <Icon name={icon} />
      <div><strong>{title}</strong>{children}</div>
    </div>
  )
}
