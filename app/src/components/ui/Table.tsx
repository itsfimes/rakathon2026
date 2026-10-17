import type { ReactNode } from 'react'

interface TableProps {
  readonly labelledBy: string
  readonly columns: readonly string[]
  readonly caption?: ReactNode
  readonly children: ReactNode
}

/** Scrollable data table that stacks into label/value rows on phones (labels via StackCell). */
export function Table({ labelledBy, columns, caption, children }: TableProps) {
  return (
    <div className="table-wrap" role="region" aria-labelledby={labelledBy} tabIndex={0}>
      <table className="table table--stack">
        <thead><tr>{columns.map(column => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

/** Table cell carrying its column label for the stacked mobile layout. All content sits in one
    wrapper so the stacked grid keeps it together in the value track. */
export function StackCell({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return <td data-label={label}><div className="stack-cell__value">{children}</div></td>
}
