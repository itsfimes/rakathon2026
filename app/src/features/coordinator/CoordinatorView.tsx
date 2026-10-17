import { CaseGate } from '../../components/shell/CaseGate'
import { EmptyState, ErrorState, InvalidCaseState, LoadingState } from '../../components/shell/DataState'
import { ViewHead } from '../../components/shell/ViewHead'
import { Panel } from '../../components/ui/Panel'
import { formatDate } from '../../lib/format'
import type { ClinicianNavigation, RoleViewProps } from '../types'
import { BackToList } from '../shared/RouteLinks'
import { LegacyProcessNote } from '../shared/LegacyNote'
import { AttentionPanel, CaseHeader, CaseSectionBody, CaseSectionNav } from '../shared/clinical/CaseSections'
import { SECTION_LABEL } from '../shared/clinical/facts'
import { CaseDetailPanel } from './CaseDetailPanel'
import { QueueTable } from './QueueTable'

type CoordinatorViewProps = RoleViewProps & ClinicianNavigation

/** Coordinator: the queue and each case are separate pages; the queue never shares the screen with a detail. */
export function CoordinatorView({ workspace, detail, actions, route, onNavigate, onReturn }: CoordinatorViewProps) {
  if (route.page === 'detail' || route.page === 'invalid-detail') {
    const section = route.page === 'detail' && route.view !== 'mdt' ? route.section ?? 'overview' : 'overview'
    return (
      <>
        <BackToList role="koordinator" label="Zpět na frontu případů" onReturn={onReturn} />
        <ViewHead id="t-koordinator" icon="queue" title="Detail případu" lead={route.page === 'detail' ? SECTION_LABEL[section] : undefined} />
        {route.page !== 'detail' ? <InvalidCaseState /> : (
          <>
            <CaseSectionNav role="koordinator" caseId={route.caseId} section={section} onNavigate={onNavigate} />
            <CaseGate workspace={workspace} detail={detail}>
              {value => (
                <>
                  <CaseHeader detail={value} />
                  <CaseSectionBody detail={value} role="koordinator" section={section} overview={
                    <>
                    <LegacyProcessNote dates={[value.nextStep?.dueAt, value.nextStep?.requestedAt, value.identity.referredAt]} asOf={workspace.status === 'ready' ? workspace.value.asOf : null} />
                    <div className="split">
                      <CaseDetailPanel detail={value} actions={actions} />
                      <AttentionPanel detail={value} role="koordinator" onNavigate={onNavigate} />
                    </div>
                    </>
                  } />
                </>
              )}
            </CaseGate>
          </>
        )}
      </>
    )
  }
  const lead = workspace.status === 'ready'
    ? workspace.value.metadata.origin === 'backend' ? `` : ``
    : undefined
  return (
    <>
      <ViewHead id="t-koordinator" icon="queue" title="Koordinátor: fronta případů" lead={lead} />
      {workspace.status === 'ready' ? (
        workspace.value.queue.length === 0
          ? <EmptyState title="Fronta je prázdná" text={workspace.value.metadata.origin === 'backend' ? 'Zdroj dat nenabízí žádný případ.' : 'Žádný případ nečeká na další krok.'} />
          : (
            <Panel id="t-queue" title={<>{workspace.value.metadata.origin === 'backend' ? 'Dostupné případy' : 'Případy podle priority'} <span className="tag tag--neutral">{workspace.value.queue.length}</span></>}>
              <QueueTable labelledBy="t-queue" queue={workspace.value.queue} onNavigate={onNavigate} asOf={workspace.value.asOf} />
            </Panel>
          )
      ) : workspace.status === 'error' ? <ErrorState error={workspace.error} /> : <LoadingState />}
    </>
  )
}
