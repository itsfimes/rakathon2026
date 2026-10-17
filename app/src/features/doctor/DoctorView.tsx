import { CaseGate } from '../../components/shell/CaseGate'
import { EmptyState, ErrorState, InvalidCaseState, LoadingState } from '../../components/shell/DataState'
import { ViewHead } from '../../components/shell/ViewHead'
import { NextStep } from '../../components/ui/NextStep'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Tag } from '../../components/ui/Tag'
import { Timeline } from '../../components/ui/Timeline'
import { AttentionPanel, CaseHeader, CaseSectionBody, CaseSectionNav } from '../shared/clinical/CaseSections'
import type { ClinicianNavigation, RoleViewProps } from '../types'
import { BackToList } from '../shared/RouteLinks'
import { LegacyProcessNote } from '../shared/LegacyNote'
import { TaskFacts } from '../shared/TaskFacts'
import { DoctorCaseTable } from './DoctorCaseTable'
import { SourceReviewPanel } from './SourceReviewPanel'
import { UploadPanel } from './UploadPanel'
import type { UploadCapability } from '../../data/backend/uploads'

type DoctorViewProps = RoleViewProps & ClinicianNavigation & {
  readonly uploads?: UploadCapability | null
  readonly uploadCaseId?: string | null
  readonly mockMode?: boolean
}

/** Referring doctor: a neutral demo case list, then one case per page (referral and next step first, extraction review after). */
export function DoctorView({ workspace, detail, actions, route, onNavigate, onReturn, uploads, uploadCaseId, mockMode }: DoctorViewProps) {
  const backend = workspace.status === 'ready' && workspace.value.metadata.origin === 'backend'
  if (route.page === 'list') {
    return (
      <>
        <ViewHead id="t-lekar" icon="steth" title={backend ? 'Lékař: seznam případů' : 'Lékař: ukázkový seznam případů'} />
        {workspace.status === 'ready' ? (
          workspace.value.queue.length === 0
            ? <EmptyState title="Žádné případy" text={backend ? 'Zdroj dat nenabízí žádný případ.' : 'V ukázce teď není žádný případ.'} />
            : (
              <Panel id="t-doctor-list" title={<>{backend ? 'Seznam případů' : 'Ukázkový seznam případů'} <span className="tag tag--neutral">{workspace.value.queue.length}</span></>}>
                <DoctorCaseTable labelledBy="t-doctor-list" queue={workspace.value.queue} onNavigate={onNavigate} asOf={workspace.value.asOf} />
              </Panel>
            )
        ) : workspace.status === 'error' ? <ErrorState error={workspace.error} /> : <LoadingState />}
      </>
    )
  }
  const section = route.page === 'detail' && route.view !== 'mdt' ? route.section ?? 'overview' : 'overview'
  return (
    <>
      <BackToList role="lekar" label="Zpět na seznam případů" onReturn={onReturn} />
      <ViewHead id="t-lekar" icon="steth" title={backend ? 'Lékař: případ' : 'Lékař: odeslaný pacient'} />
      {route.page !== 'detail' ? <InvalidCaseState /> : (
        <>
          <CaseSectionNav role="lekar" caseId={route.caseId} section={section} onNavigate={onNavigate} />
          <CaseGate workspace={workspace} detail={detail}>
            {value => (
              <>
                <CaseHeader detail={value} />
                <CaseSectionBody detail={value} role="lekar" section={section} overview={
                  <>
                    <LegacyProcessNote dates={[value.nextStep?.dueAt, value.nextStep?.requestedAt, value.identity.referredAt]} asOf={workspace.status === 'ready' ? workspace.value.asOf : null} />
                    <p className="context-note"><Tag label={{ tone: 'warning', icon: 'clock', text: value.doctor.diagnosisStatus }} /></p>
                    <div className="split split--side-first">
                      <div className="stack">
                        <Panel id="t-ref" icon="arrow" title="Stav odeslání">
                          <PanelBody><Timeline items={value.doctor.referralStatus} label="Stav odeslání" /></PanelBody>
                        </Panel>
                        <NextStep id="ns-l" title="Další krok v případu" what={value.nextStep?.shortTitle ?? 'Další krok není zadán'}>
                          {value.nextStep ? <TaskFacts step={value.nextStep} withOwnerName={false} withAcknowledgement={false} /> : <p className="placeholder-text">Zdroj dat žádný krok nedodal</p>}
                          <p className="meta">{value.doctor.obligations}</p>
                        </NextStep>
                        <AttentionPanel detail={value} role="lekar" onNavigate={onNavigate} />
                      </div>
                      <div className="stack">
                        <SourceReviewPanel fields={value.doctor.sourceFields} documents={value.documents} actions={actions} />
                        {route.page === 'detail' && uploadCaseId === route.caseId && (
                          <UploadPanel capability={uploads ?? null} caseId={route.caseId} mockMode={mockMode ?? false} />
                        )}
                      </div>
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
