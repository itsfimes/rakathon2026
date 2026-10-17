import type { ReactNode } from 'react'
import { countText, ENTRIES, useFolded } from './grouping'
import type { Column, Fold, TableGroup } from './grouping'

/** One quiet, consistent mark for a value the source does not state; still read out as "neuvedeno". */
export function Missing() {
  return <span className="lab-missing" title="Ve zdroji neuvedeno"><span aria-hidden="true">—</span><span className="visually-hidden">neuvedeno</span></span>
}

/** The single toggle naming exactly what is folded; nothing is hidden silently. */
export function FoldToggle({ fold, expanded, hiddenGroups, hiddenItems, onToggle }: { readonly fold: Fold; readonly expanded: boolean; readonly hiddenGroups: number; readonly hiddenItems: number; readonly onToggle: () => void }) {
  if (hiddenGroups === 0) return null
  // One-item groups make both counts the same number; say it once instead of "(8, 8 záznamů)".
  const folded = countText(hiddenItems, fold.items)
  const counts = hiddenGroups === hiddenItems ? folded : `${hiddenGroups}, ${folded}`
  return (
    <div className="meas-more">
      <button type="button" className="btn btn--secondary" aria-expanded={expanded} onClick={onToggle}>
        {expanded ? `Zobrazit méně (${fold.unit})` : `Zobrazit další ${fold.unit} (${counts})`}
      </button>
    </div>
  )
}

interface GroupedTableProps<T> {
  readonly labelledBy: string
  readonly caption: ReactNode
  readonly columns: readonly Column[]
  readonly groups: readonly TableGroup<T>[]
  readonly row: (item: T, group: TableGroup<T>) => ReactNode
  /** Groups shown before folding; omit to show everything. */
  readonly limit?: number
  /** Approximate row budget before folding (whole groups only). */
  readonly budget?: number
  readonly fold?: Fold
}

/** Dense grouped data: one header per group carrying its shared context, compact rows, optional folding. Uses the lab-table look. */
export function GroupedTable<T>({ labelledBy, caption, columns, groups, row, limit, budget = 24, fold = { unit: 'skupiny', items: ENTRIES } }: GroupedTableProps<T>) {
  const folded = useFolded(groups, limit ?? groups.length, budget)
  return (
    <>
      <div className="table-wrap" role="region" aria-labelledby={labelledBy} tabIndex={0}>
        <table className="table lab-table">
          <caption>{caption}</caption>
          <thead><tr>{columns.map(column => <th key={column.label} scope="col" className={column.numeric ? 'lab-table__num' : undefined}>{column.label}</th>)}</tr></thead>
          {folded.shown.map(group => (
            <tbody key={group.key}>
              <tr className="lab-table__group">
                <th scope="rowgroup" colSpan={columns.length}>
                  <span className="lab-table__panel">{group.title}</span>
                  {group.meta.map((line, index) => <span key={index} className="lab-table__dates">{line}</span>)}
                </th>
              </tr>
              {group.items.map(item => row(item, group))}
            </tbody>
          ))}
        </table>
      </div>
      <FoldToggle fold={fold} expanded={folded.expanded} hiddenGroups={folded.hiddenGroups} hiddenItems={folded.hiddenItems} onToggle={folded.toggle} />
    </>
  )
}
