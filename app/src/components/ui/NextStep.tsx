import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'

interface NextStepProps {
  readonly id: string
  readonly title: string
  readonly what: ReactNode
  readonly level?: 2 | 3
  readonly children?: ReactNode
}

/** Shared signature panel: what happens next, then owner/deadline/acknowledgement. */
export function NextStep({ id, title, what, level = 2, children }: NextStepProps) {
  const Heading = level === 3 ? 'h3' : 'h2'
  return (
    <section className="next-step" aria-labelledby={id}>
      <Heading className="next-step__head" id={id}><Icon name="arrow" />{title}</Heading>
      <div className="next-step__body">
        <p className="next-step__what">{what}</p>
        {children}
      </div>
    </section>
  )
}
