import type { ClinicalFact, ClinicalSource, LabPayload } from '../../../data/clinical'
import { Tag } from '../../../components/ui/Tag'
import { FactTags, SourceInspect } from './FactBlock'
import { LAB_FLAG, LAB_PANEL, SUSCEPTIBILITY } from './clinicalText'
import { GroupedTable, Missing } from './GroupedTable'
import { groupInOrder, labTimes, sharedValue, VALUES } from './grouping'
import type { TableGroup } from './grouping'

interface LabTableProps {
  readonly facts: readonly ClinicalFact<LabPayload>[]
  readonly sources: readonly ClinicalSource[]
  readonly labelledBy: string
}

const COLUMNS = [{ label: 'Vyšetření' }, { label: 'Hodnota', numeric: true }, { label: 'Jednotka' }, { label: 'Rozmezí ze zdroje' }, { label: 'Označení' }, { label: 'Zdroj' }] as const

/** Rows sharing panel and both dates form one group; a source note shared by the whole group is lifted into its header. */
function labGroups(facts: readonly ClinicalFact<LabPayload>[]): TableGroup<ClinicalFact<LabPayload>>[] {
  return groupInOrder(facts, fact => JSON.stringify([panelName(fact.value.panel), ...labTimes(fact.value, fact.effective)])).map(group => {
    const first = group.items[0]!
    const note = sharedValue(group.items, fact => fact.value.suppliedNote)
    return { key: group.key, items: group.items, title: panelName(first.value.panel), meta: [labTimes(first.value, first.effective).join(' · '), ...note ? [note] : []] }
  })
}

const panelName = (panel: string | undefined) => panel ? LAB_PANEL[panel] ?? panel : 'Panel neuveden'

/** Dense lab results: grouped by panel and dates, value and unit as the scan line, absent fields one quiet mark. */
export function LabTable({ facts, sources, labelledBy }: LabTableProps) {
  const groups = labGroups(facts)
  return <GroupedTable labelledBy={labelledBy} columns={COLUMNS} groups={groups} fold={{ unit: 'skupiny', items: VALUES }}
    row={(fact, group) => <LabRow key={fact.id} fact={fact} sources={sources} showNote={!sharedValue(group.items, item => item.value.suppliedNote)} />} />
}

function LabRow({ fact, sources, showNote }: { readonly fact: ClinicalFact<LabPayload>; readonly sources: readonly ClinicalSource[]; readonly showNote: boolean }) {
  const v = fact.value
  const flag = v.abnormalFlag ? LAB_FLAG[v.abnormalFlag] : null
  const cultureOnly = v.culture && v.value === undefined
  return (
    <tr className="lab-table__row">
      <th scope="row" className="lab-table__test">
        <span className="lab-table__name">{v.test}</span>
        <FactTags fact={fact} />
        {showNote && v.suppliedNote && <span className="sub">{v.suppliedNote}</span>}
        {v.culture && <div className="culture">
          <p>{v.culture.organism}{v.culture.quantity ? ` · ${v.culture.quantity}` : ''}</p>
          <ul className="plain-list">{v.culture.susceptibility.map(item => <li key={item.agent}>{item.agent}: {SUSCEPTIBILITY[item.result]}{item.mic ? ` (MIC ${item.mic}${item.unit ? ` ${item.unit}` : ''})` : ''}</li>)}</ul>
        </div>}
        {v.sediment && <span className="sub">Sediment: {v.sediment}</span>}
      </th>
      <td className="lab-table__num lab-table__value">
        {cultureOnly ? <span className="sub">viz kultivace</span> : v.value !== undefined ? <span className="num">{v.value}</span> : <Missing />}
      </td>
      <td className="lab-table__unit">{v.unit ?? (cultureOnly ? null : <Missing />)}</td>
      <td className="lab-table__range" data-label="Rozmezí"><span className="num">{v.referenceRange ?? <Missing />}</span></td>
      <td className="lab-table__flag" data-label="Označení">{flag ? <Tag label={flag} /> : <Missing />}</td>
      <td className="lab-table__source"><SourceInspect fact={fact} sources={sources} effectiveLabel="Platnost výsledku" presentation="dialog" compactFor={v.test} /></td>
    </tr>
  )
}
