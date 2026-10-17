import { StackCell, Table } from '../../components/ui/Table'
import { MiniSteps } from '../../components/ui/StepBar'
import type { QueueItem } from '../../data/contracts'
import { ageText, diagnosisText } from '../../lib/labels'
import type { Route } from '../../lib/routes'
import { caseRowId, rowActivation } from '../shared/routeActivation'
import { RouteLink } from '../shared/RouteLinks'

interface MdtCaseTableProps {
  readonly labelledBy: string
  readonly queue: readonly QueueItem[]
  readonly onNavigate: (route: Route) => void
}

/** Every case the data source offers, from the shared workspace summaries only: no per-case reads,
    no meeting membership, schedule or preparation status is claimed here. */
export function MdtCaseTable({ labelledBy, queue, onNavigate }: MdtCaseTableProps) {
  return (
    <Table labelledBy={labelledBy}
      columns={['Pacient', 'Diagnóza', 'Úsek']}>
      {queue.map(item => {
        const route: Route = { view: 'mdt', page: 'detail', caseId: item.caseId }
        return (
          <tr key={item.caseId} className="is-selectable" onClick={event => rowActivation(event, () => onNavigate(route))}>
            <StackCell label="Pacient">
              <RouteLink route={route} onNavigate={onNavigate} id={caseRowId('mdt', item.caseId)} className="row-select">
                {item.patientLabel}
              </RouteLink>
               <span className="sub">{ageText(item.age)}</span>
            </StackCell>
             <StackCell label="Diagnóza">{diagnosisText(item.diagnosis)}</StackCell>
             <StackCell label="Úsek">{item.phase ?? 'úsek neuveden'}{item.phase && <MiniSteps phase={item.phase} />}</StackCell>
          </tr>
        )
      })}
    </Table>
  )
}
