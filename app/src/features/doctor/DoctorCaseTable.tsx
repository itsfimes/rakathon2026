import { StackCell, Table } from '../../components/ui/Table'
import { MiniSteps } from '../../components/ui/StepBar'
import type { QueueItem } from '../../data/contracts'
import { calendarParts, formatDate, formatDayMonth } from '../../lib/format'
import { ageText, diagnosisText, ownerText } from '../../lib/labels'
import type { Route } from '../../lib/routes'
import { caseRowId, rowActivation } from '../shared/routeActivation'
import { RouteLink } from '../shared/RouteLinks'

interface DoctorCaseTableProps {
  readonly labelledBy: string
  readonly queue: readonly QueueItem[]
  readonly onNavigate: (route: Route) => void
  /** Workspace "as of" day; older due dates are marked, never re-dated. */
  readonly asOf?: string | undefined
}


/** Due date; a date before the workspace "as of" day shows its year and a plain note, nothing more is inferred. */
function DueDate({ due, asOf }: { readonly due: string; readonly asOf: string | undefined }) {
  const dueDay = calendarParts(due) ? due.slice(0, 10) : null
  const asOfDay = asOf && calendarParts(asOf) ? asOf.slice(0, 10) : null
  if (!dueDay || !asOfDay || dueDay >= asOfDay) return <>{formatDayMonth(due)}</>
  return <>{formatDate(due)}<span className="sub">starší údaj · datum před stavem k {formatDate(asOfDay)}</span></>
}

/** Neutral demo list built only from the shared queue summaries: no per-case reads, no ownership claim,
    no coordinator priority. Order is the queue's order. */
export function DoctorCaseTable({ labelledBy, queue, onNavigate, asOf }: DoctorCaseTableProps) {
  return (
    <Table labelledBy={labelledBy}
      columns={['Pacient', 'Další krok v případu · kdo', 'Termín kroku', 'Úsek']}>
      {queue.map(item => {
        const route: Route = { view: 'lekar', page: 'detail', caseId: item.caseId }
        return (
          <tr key={item.caseId} className="is-selectable" onClick={event => rowActivation(event, () => onNavigate(route))}>
            <StackCell label="Pacient">
              <RouteLink route={route} onNavigate={onNavigate} id={caseRowId('lekar', item.caseId)} className="row-select">
                {item.patientLabel}
              </RouteLink>
               <span className="sub">{ageText(item.age)} · {diagnosisText(item.diagnosis)}</span>
            </StackCell>
            <StackCell label="Další krok">
               <span className="cell-icon__main">{item.nextStep?.shortTitle ?? 'Další krok není zadán'}</span>
              <span className="sub">{ownerText(item.nextStep)}</span>
            </StackCell>
             <StackCell label="Termín">{item.nextStep ? <DueDate due={item.nextStep.dueAt} asOf={asOf} /> : 'termín neuveden'}</StackCell>
             <StackCell label="Úsek">{item.phase ?? 'úsek neuveden'}{item.phase && <MiniSteps phase={item.phase} />}</StackCell>
          </tr>
        )
      })}
    </Table>
  )
}
