import type { ReactNode } from 'react'

export interface ChecklistItem {
  readonly key: string
  readonly label: ReactNode
  readonly status: ReactNode
}

export function Checklist({ items }: { readonly items: readonly ChecklistItem[] }) {
  return (
    <ul className="checklist">
      {items.map(item => <li key={item.key}><span>{item.label}</span><span className="checklist__tags">{item.status}</span></li>)}
    </ul>
  )
}
