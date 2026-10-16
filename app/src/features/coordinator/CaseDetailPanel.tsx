import { Button, ButtonRow, ExampleNote } from '../../components/ui/Button'
import { Facts } from '../../components/ui/Facts'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { StepBar } from '../../components/ui/StepBar'
import type { CaseDetail } from '../../data/contracts'
import type { DemoActions } from '../../hooks/useDemoActions'
import { Icon } from '../../icons/Icon'
import { formatDate } from '../../lib/format'
import { DocumentEvidence } from '../shared/DocumentEvidence'
import { ScopedDisclosure } from '../shared/ScopedDisclosure'
import { UnavailableNote } from '../shared/DemoNote'
import { TaskFacts } from '../shared/TaskFacts'

/** Counts of documents that still need attention; plain tallies of the supplied states, no inference. */
function documentSummary(documents: CaseDetail['documents']): string {
  const missing = documents.filter(document => document.state === 'missing').length
  const uncertain = documents.filter(document => document.state === 'uncertain').length
  const parts = [missing > 0 ? `chybí ${missing}` : '', uncertain > 0 ? `ověřit ${uncertain}` : ''].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : documents.length ? 'vše k dispozici' : 'údaje o podkladech neuvedeny'
}

/** Case page body: the current task first, then its documents, then the patient's phase overview. */
export function CaseDetailPanel({ detail, actions }: { readonly detail: CaseDetail; readonly actions: DemoActions }) {
  const { identity, nextStep } = detail
  const canAccept = nextStep && actions.available && (nextStep.acknowledgement === 'pending' || nextStep.acknowledgement === 'new')
  return (
    <Panel as="article" id="t-case" icon="queue" title="Proces případu" meta="Pořadí a lhůty vyjadřují organizaci práce, ne zdravotní riziko.">
      <PanelBody className="case">
        <section className="case-task" aria-labelledby="ns-k">
          <h3 className="label case-task__label"><Icon name="arrow" small />Další krok</h3>
          <p className="case-task__title" id="ns-k">{nextStep?.title ?? 'Další krok není zadán'}</p>
          {nextStep ? <TaskFacts step={nextStep} inline /> : <p className="placeholder-text">Zdroj dat žádný krok nedodal</p>}
          {canAccept && <div className="case-task__local">
            <Button variant="secondary" icon="check" disabled={actions.busy} aria-describedby="note-k-local" onClick={() => actions.acceptTask(nextStep.id)}>
              Potvrdit převzetí (lokálně v demu)
            </Button>
            <ExampleNote id="note-k-local">Změní stav jen v tomto okně. Nic se neodešle vlastníkovi kroku.</ExampleNote>
          </div>}
          <ScopedDisclosure icon="calendar" summary="Data kroku a případu">
            <Facts items={[
              { key: 'requested', icon: 'arrow', label: 'Krok vyžádán', value: nextStep ? formatDate(nextStep.requestedAt) : 'datum vyžádání neuvedeno' },
              { key: 'accepted', icon: 'check', label: 'Převzetí kroku', value: nextStep ? nextStep.acceptedAt ? formatDate(nextStep.acceptedAt) : 'Zatím nepotvrzeno' : 'Převzetí neuvedeno', placeholder: !nextStep?.acceptedAt },
              { key: 'referred', icon: 'steth', label: 'Pacient odeslán', value: identity.referredAt ? formatDate(identity.referredAt) : 'datum odeslání neuvedeno' },
              { key: 'koc', icon: 'building', label: 'Přijetí v KOC', value: identity.acceptedAt ? formatDate(identity.acceptedAt) : 'Není uvedeno', placeholder: !identity.acceptedAt },
            ]} />
            <p className="meta">Datum vyžádání není datum doručení ani poslední urgence; ta se zde neevidují.</p>
          </ScopedDisclosure>
          {detail.priorityExplanation && <ScopedDisclosure icon="help" summary="Proč je případ nahoře?"><p>{detail.priorityExplanation}</p></ScopedDisclosure>}
        </section>

        <section className="case-section" aria-labelledby="t-case-docs">
          <h3 className="label case-section__label" id="t-case-docs">Podklady <span className="case-section__count">· {documentSummary(detail.documents)}</span></h3>
          <DocumentEvidence documents={detail.documents} coordinatorLabels />
        </section>

        <section className="case-section" aria-labelledby="t-case-phases">
          <h3 className="label case-section__label" id="t-case-phases">Cesta pacienta: úseky T1–T3</h3>
          {detail.phases.length ? <StepBar phases={detail.phases} label="Čas do léčby" /> : <p className="placeholder-text">úsek neuveden</p>}
        </section>

        <section className="case-unavailable" aria-labelledby="t-case-unavailable">
          <h3 className="label" id="t-case-unavailable">Komunikace (zatím nepřipojeno)</h3>
          <ButtonRow>
            <Button variant="secondary" disabled aria-describedby="note-k">Urgovat vlastníka kroku</Button>
            <Button variant="secondary" disabled aria-describedby="note-k">Informovat odesílajícího lékaře</Button>
          </ButtonRow>
          <UnavailableNote id="note-k" />
        </section>
      </PanelBody>
    </Panel>
  )
}
