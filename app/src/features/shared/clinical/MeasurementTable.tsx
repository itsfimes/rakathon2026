import type { ReactNode } from 'react'
import type { ClinicalFact, ClinicalSource, MeasurementPayload } from '../../../data/clinical'
import { FactTags, SourceInspect } from './FactBlock'
import { MEASUREMENT_TYPE } from './clinicalText'
import { GroupedTable, Missing } from './GroupedTable'
import { MEASUREMENT_COLUMNS, MEASUREMENT_SEP, measurementParts, measurementSessions, SESSION_FOLD, SESSION_LIMIT } from './grouping'
import type { MeasurementLike } from './grouping'

/** Name, own descriptor and value cells of one measurement row; the caller supplies status tags and the source cell. */
export function MeasurementCells({ v, shared, tags, source }: { readonly v: MeasurementLike; readonly shared: readonly string[]; readonly tags: ReactNode; readonly source: (name: string) => ReactNode }) {
  const own = measurementParts(v).filter((part, index) => index === 0 || !shared.includes(part))
  const name = v.type === 'examination' ? own[0] ?? MEASUREMENT_TYPE.examination! : MEASUREMENT_TYPE[v.type] ?? v.type
  const detail = (v.type === 'examination' ? own.slice(1) : own).join(MEASUREMENT_SEP)
  return <>
    <th scope="row" className="lab-table__test">
      <span className="lab-table__name">{name}</span>
      {tags}
      {detail && <span className="sub">{detail}</span>}
    </th>
    <td className="lab-table__num lab-table__value"><span className="num">{v.value}</span></td>
    <td className="lab-table__unit">{v.unit ?? <Missing />}</td>
    {source(name)}
  </>
}

/** Measurements grouped by session: one header per measurement time, value and unit as the scan line. */
export function MeasurementTable({ facts, sources, labelledBy }: { readonly facts: readonly ClinicalFact<MeasurementPayload>[]; readonly sources: readonly ClinicalSource[]; readonly labelledBy: string }) {
  const groups = measurementSessions(facts, fact => fact.value, fact => fact.effective)
  const shared = new Map(groups.map(group => [group.key, group.shared]))
  return <GroupedTable labelledBy={labelledBy} caption={`Sezení měření v pořadí zdroje (${groups.length}). „—“ = ve zdroji neuvedeno.`} columns={MEASUREMENT_COLUMNS}
    groups={groups} limit={SESSION_LIMIT} fold={SESSION_FOLD}
    row={(fact, group) => (
      <tr key={fact.id} className="lab-table__row">
        <MeasurementCells v={fact.value} shared={shared.get(group.key) ?? []} tags={<FactTags fact={fact} />}
          source={name => <td className="lab-table__source"><SourceInspect fact={fact} sources={sources} effectiveLabel="Změřeno" presentation="dialog" compactFor={name} /></td>} />
      </tr>
    )} />
}
