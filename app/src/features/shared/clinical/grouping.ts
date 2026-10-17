import { useState } from 'react'
import type { ReactNode } from 'react'
import type { ClinicalTime, MeasurementPayload } from '../../../data/clinical'
import { clinicalTimeText } from './clinicalText'

/** Czech count: 1 hodnota, 2–4 hodnoty, 5+ hodnot (same pattern for záznam). */
export const countText = (count: number, [one, few, many]: readonly [string, string, string]) =>
  `${count} ${count === 1 ? one : count >= 2 && count <= 4 ? few : many}`
export const VALUES = ['hodnota', 'hodnoty', 'hodnot'] as const
export const ENTRIES = ['záznam', 'záznamy', 'záznamů'] as const

/** Groups items by key in first-appearance order. Nothing is re-sorted or merged inside a group. */
export function groupInOrder<T>(items: readonly T[], keyOf: (item: T) => string): { readonly key: string; readonly items: T[] }[] {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const key = keyOf(item)
    const group = groups.get(key)
    if (group) group.push(item)
    else groups.set(key, [item])
  }
  return [...groups.entries()].map(([key, grouped]) => ({ key, items: grouped }))
}

/** Value shared by every item (shown once in a group header), else undefined. Single items keep their own. */
export function sharedValue<T>(items: readonly T[], read: (item: T) => string | undefined): string | undefined {
  if (items.length < 2) return undefined
  const first = read(items[0]!)
  return first && items.every(item => read(item) === first) ? first : undefined
}

export interface Fold { readonly unit: string; readonly items: readonly [string, string, string] }

/** Progressive disclosure for long histories: at most `limit` groups and roughly `budget` items (always at least one
    whole group; groups are never split), the rest behind one explicit toggle. */
export function useFolded<G extends { readonly items: readonly unknown[] }>(groups: readonly G[], limit: number, budget = Infinity) {
  const [expanded, setExpanded] = useState(false)
  let count = 0, used = 0
  while (count < groups.length && count < limit && (count === 0 || used + groups[count]!.items.length <= budget)) used += groups[count++]!.items.length
  const hidden = groups.slice(count)
  return { shown: expanded ? groups : groups.slice(0, count), expanded, toggle: () => setExpanded(open => !open),
    hiddenGroups: hidden.length, hiddenItems: hidden.reduce((sum, group) => sum + group.items.length, 0) }
}

export interface Column { readonly label: string; readonly numeric?: boolean }
export interface TableGroup<T> {
  readonly key: string
  readonly title: ReactNode
  /** Quiet context lines lifted out of the rows (dates, shared notes, shared source). */
  readonly meta: readonly ReactNode[]
  readonly items: readonly T[]
}

export const MEASUREMENT_SEP = ' · '
export interface MeasurementLike { readonly type: MeasurementPayload['type']; readonly value: string; readonly unit?: string | undefined; readonly examination?: string | undefined }
export const measurementParts = (v: MeasurementLike) => v.examination?.split(MEASUREMENT_SEP).filter(Boolean) ?? []
export const SESSION_FOLD: Fold = { unit: 'sezení', items: VALUES }
export const SESSION_LIMIT = 3
export const MEASUREMENT_COLUMNS: readonly Column[] = [{ label: 'Měření' }, { label: 'Hodnota', numeric: true }, { label: 'Jednotka' }, { label: 'Zdroj' }]

/** Rows with the same measurement time form one session (source order kept). Trailing descriptor parts shared by
    every row, plus any extra context the caller lifts (e.g. one shared source), go once into the session header. */
export function measurementSessions<R>(rows: readonly R[], read: (row: R) => MeasurementLike, time: (row: R) => ClinicalTime, extra: (rows: readonly R[]) => readonly ReactNode[] = () => []):
  (TableGroup<R> & { readonly shared: readonly string[] })[] {
  return groupInOrder(rows, row => clinicalTimeText(time(row))).map(group => {
    const first = measurementParts(read(group.items[0]!))
    const shared = group.items.length > 1 ? first.slice(1).filter(part => group.items.every(row => measurementParts(read(row)).slice(1).includes(part))) : []
    const dated = time(group.items[0]!).kind !== 'unknown'
    return { key: group.key, items: group.items, shared,
      title: dated ? `Změřeno: ${group.key}` : 'Datum měření neuvedeno',
      meta: [countText(group.items.length, VALUES), ...dated ? [] : ['Nelze považovat za aktuální.'], ...shared.length ? [shared.join(MEASUREMENT_SEP)] : [], ...extra(group.items)] }
  })
}

/** Sample/result dates as the source states them; when neither is stated, the result's validity time stands in, labelled as such. */
export const labTimes = (v: { readonly sampleAt?: ClinicalTime | undefined; readonly resultAt?: ClinicalTime | undefined }, effective: ClinicalTime) =>
  !v.sampleAt && !v.resultAt && effective.kind !== 'unknown'
    ? [`Odběr ani výsledek: datum neuvedeno`, `Platnost výsledku: ${clinicalTimeText(effective)}`]
    : [`Odběr: ${clinicalTimeText(v.sampleAt)}`, `Výsledek: ${clinicalTimeText(v.resultAt)}`]
