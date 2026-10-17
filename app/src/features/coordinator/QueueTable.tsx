import { StackCell, Table } from '../../components/ui/Table'
import { MiniSteps } from '../../components/ui/StepBar'
import { Tag } from '../../components/ui/Tag'
import type { QueueItem } from '../../data/contracts'
import { Icon } from '../../icons/Icon'
import { calendarParts, formatDate, formatDayMonth } from '../../lib/format'
import { acknowledgementLabel, diagnosisText, ownerText, PRIORITY, unknownPriority } from '../../lib/labels'
import type { Route } from '../../lib/routes'
import { caseRowId, rowActivation } from '../shared/routeActivation'
import { RouteLink } from '../shared/RouteLinks'

interface QueueTableProps {
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

/** Case queue; each patient name is a real link to the case page, a plain click anywhere in the row opens it too. */
export function QueueTable({ labelledBy, queue, onNavigate, asOf }: QueueTableProps) {
  return (
    <Table labelledBy={labelledBy}
      columns={['Pacient', 'Další krok · vlastník', 'Termín', 'Převzetí', 'Priorita', 'Úsek']}>
      {queue.map(item => {
        const route: Route = { view: 'koordinator', page: 'detail', caseId: item.caseId }
        return (
          <tr key={item.caseId} className="is-selectable" onClick={event => rowActivation(event, () => onNavigate(route))}>
            <StackCell label="Pacient">
              <RouteLink route={route} onNavigate={onNavigate} id={caseRowId('koordinator', item.caseId)} className="row-select">
                {item.patientLabel}
              </RouteLink>
               <span className="sub">{diagnosisText(item.diagnosis)}</span>
            </StackCell>
            <StackCell label="Další krok">
               <span className="cell-icon"><Icon name="file" /><span><span className="cell-icon__main">{item.nextStep?.shortTitle ?? 'Další krok není zadán'}</span><span className="sub">{ownerText(item.nextStep)}</span></span></span>
            </StackCell>
             <StackCell label="Termín">{item.nextStep ? <DueDate due={item.nextStep.dueAt} asOf={asOf} /> : 'termín neuveden'}</StackCell>
            <StackCell label="Převzetí"><Tag label={acknowledgementLabel(item.nextStep)} /></StackCell>
             <StackCell label="Priorita"><Tag label={item.priority ? PRIORITY[item.priority] : unknownPriority} /></StackCell>
             <StackCell label="Úsek">{item.phase ?? 'úsek neuveden'}{item.phaseDay !== undefined ? ` · den ${item.phaseDay}` : ''}{item.phase && <MiniSteps phase={item.phase} />}</StackCell>
          </tr>
        )
      })}
    </Table>
  )
}
