import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type' | 'className'> {
  readonly variant?: 'primary' | 'secondary'
  readonly icon?: IconName
  readonly children: ReactNode
}

export function Button({ variant = 'primary', icon, children, ...rest }: ButtonProps) {
  return (
    <button type="button" className={variant === 'secondary' ? 'btn btn--secondary' : 'btn'} {...rest}>
      {icon && <Icon name={icon} />}{children}
    </button>
  )
}

export function ButtonRow({ children }: { readonly children: ReactNode }) {
  return <div className="btn-row">{children}</div>
}

/** Small explanatory line under buttons (what a control does or why it is unavailable). */
export function ExampleNote({ id, children }: { readonly id: string; readonly children: ReactNode }) {
  return <p className="example-note" id={id}><Icon name="info" small />{children}</p>
}
