import { CaseGate } from '../../components/shell/CaseGate'
import { EmptyState, ErrorState, InvalidCaseState, LoadingState } from '../../components/shell/DataState'
import { ViewHead } from '../../components/shell/ViewHead'
import { Button, ButtonRow, ExampleNote } from '../../components/ui/Button'
import { Cells } from '../../components/ui/Cells'
import { Notice } from '../../components/ui/Notice'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Tag } from '../../components/ui/Tag'
import type { ClinicalRecord } from '../../data/clinical'
import type { CaseDetail, CaseDocument, DocumentState } from '../../data/contracts'
import type { MdtPreparation, PreparationExclusionReason } from '../../data/mdtPreparation'
import { Icon } from '../../icons/Icon'
import { formatDate } from '../../lib/format'
import type { StatusLabel } from '../../lib/labels'
import { ageText } from '../../lib/labels'
import type { MdtSection, Route } from '../../lib/routes'
import type { ClinicianNavigation, RoleViewProps } from '../types'
import { BackToList, RouteLink } from '../shared/RouteLinks'
import { MdtCaseTable } from './MdtCaseTable'
import { CareBody, PlanFacts } from '../shared/clinical/CareBody'
import { ClinicalRecordBody } from '../shared/clinical/ClinicalRecordBody'
import { SourceInspect } from '../shared/clinical/FactBlock'
import { PersonBody } from '../shared/clinical/PersonBody'

const KIND_LABEL: Record<CaseDocument['kind'], string> = {
  imaging: 'Zobrazení', markers: 'Nádorové markery', fitness: 'Komorbidity a výkonnost', staging: 'Staging', histology: 'Histologie',
}
const STATE_LABEL: Record<DocumentState, StatusLabel> = {
  available: { tone: 'success', icon: 'check', text: 'Doloženo' },
  missing: { tone: 'danger', icon: 'missing', text: 'Chybí' },
  uncertain: { tone: 'warning', icon: 'help', text: 'Nejisté – ověřit' },
}
const COMPLETENESS: Record<MdtPreparation['counts']['completeness'], StatusLabel> = {
  complete: { tone: 'success', icon: 'check', text: 'Úplné podle zadaných požadavků' },
  incomplete: { tone: 'danger', icon: 'missing', text: 'Neúplné' },
  unestablished: { tone: 'warning', icon: 'help', text: 'Úplnost nelze potvrdit' },
}
const EXCLUSION_TEXT: Record<PreparationExclusionReason, string> = {
  'after-cutoff': 'k dispozici až po dni porady',
  'same-day-order-unknown': 'k dispozici v den porady, pořadí neověřeno',
  'availability-overlaps-cutoff': 'dostupnost zasahuje do dne porady',
  'availability-unestablished': 'dostupnost před poradou není doložena',
  'contradictory-source-time': 'časy zdroje si odporují',
  'invalid-source-time': 'neplatný čas zdroje',
  'invalid-effective-time': 'neplatný čas údaje',
  'invalid-meeting-date': 'neplatné datum porady',
  'ambiguous-fact-id': 'nejednoznačná položka',
  'invalid-source-ref': 'neplatný odkaz na zdroj',
  'empty-source-refs': 'bez zdroje',
  'duplicate-source-ref': 'zdvojený odkaz na zdroj',
  'unresolved-source-ref': 'zdroj nenalezen',
  'ambiguous-source-ref': 'zdroj není jednoznačný',
}

function MdtNav({ caseId, current, onNavigate }: { readonly caseId: string; readonly current: MdtSection; readonly onNavigate: (route: Route) => void }) {
  return (
    <nav className="section-nav" aria-label="Části porady">
      <ul>
        <li><RouteLink route={{ view: 'mdt', page: 'detail', caseId }} onNavigate={onNavigate} className="section-nav__link" current={current === 'preparation'}><Icon name="file" />Příprava porady</RouteLink></li>
        <li><RouteLink route={{ view: 'mdt', page: 'detail', caseId, section: 'plan' }} onNavigate={onNavigate} className="section-nav__link" current={current === 'plan'}><Icon name="team" />Zaznamenaný plán po poradě</RouteLink></li>
      </ul>
    </nav>
  )
}

/** Minimal safe identity line: label and age only. */
function MdtWho({ detail }: { readonly detail: CaseDetail }) {
  return <div className="case-header"><h2 className="case-header__who"><Icon name="person" />{detail.identity.patientLabel} · {ageText(detail.identity.age)}</h2></div>
}

function Unavailable({ title, text }: { readonly title: string; readonly text: string }) {
  return <div className="view__state"><Notice tone="warning" icon="database" title={title} role="status">{text}</Notice></div>
}

/** Historical preparation: renders ONLY the frozen MdtPreparation, never live case fields or counts. */
function Preparation({ prep }: { readonly prep: MdtPreparation }) {
  const day = formatDate(prep.meetingDate)
  if (prep.status !== 'ready') {
    return <div className="view__state"><Notice tone="danger" icon="alert" title="Příprava porady je neplatná" role="alert">Datum porady v přípravě není platné, proto se žádné podklady nezobrazují.</Notice></div>
  }
  const snapshot: ClinicalRecord = { revision: prep.revision, sources: prep.sources, domains: prep.facts }
  const reasons = new Map<PreparationExclusionReason, number>()
  prep.exclusions.forEach(item => reasons.set(item.reason, (reasons.get(item.reason) ?? 0) + 1))
  const { counts } = prep
  return (
    <div className="record">
      <Notice tone="info" icon="calendar" title={`Podklady doložené před ${day}; u stejného dne není pořadí ověřeno.`} role="note">
        <ul className="plain-list">{prep.limitations.map(item => <li key={item}>{item}</li>)}</ul>
      </Notice>
      <div className="split">
        <Panel id="t-mdt-req" icon="file" title={<>Požadované podklady <Tag label={COMPLETENESS[counts.completeness]} /></>}
          meta={counts.total === 0 ? 'Požadavky nejsou zadány, úplnost proto nelze potvrdit.' : `Doloženo ${counts.available} z ${counts.total} · chybí ${counts.missing} · nejisté ${counts.uncertain}. Sada požadavků je ukázková, ne norma.`}>
          <PanelBody>
            {prep.documents.length > 0 && <Cells states={prep.documents.map(document => document.state)} />}
            <ul className="req-list">
              {prep.documents.map(document => {
                const fact = prep.requirements.find(item => item.value.documentKind === document.kind)
                return (
                  <li key={document.kind}>
                    <span className="req-list__name">{KIND_LABEL[document.kind]}</span>
                    <Tag label={STATE_LABEL[document.state]} />
                    {fact && <SourceInspect fact={fact} sources={prep.sources} effectiveLabel="Stav k" />}
                  </li>
                )
              })}
            </ul>
          </PanelBody>
        </Panel>
        <div className="stack">
          <Panel id="t-mdt-task" icon="flag" title="Úkoly a termíny doložené před poradou">
            <PanelBody><PlanFacts facts={prep.taskPlan} sources={prep.sources} empty="Žádný doložený úkol ani termín." /></PanelBody>
          </Panel>
          <Panel id="t-mdt-excl" icon="lock" title={`Vyřazeno z přípravy: ${prep.exclusions.length}`} meta="Jen počty a důvody. Obsah vyřazených položek se zde nezobrazuje.">
            <PanelBody>
              {reasons.size === 0 ? <p className="placeholder-text">Nic nebylo vyřazeno.</p>
                : <ul className="plain-list">{[...reasons].map(([reason, count]) => <li key={reason}>{count} × {EXCLUSION_TEXT[reason]}</li>)}</ul>}
            </PanelBody>
          </Panel>
          <Panel id="t-mdt-final" icon="lock" title="Závěr porady">
            <PanelBody>
              <p>Závěr zapisuje a podepisuje předseda porady mimo tuto aplikaci.</p>
              <ButtonRow><Button icon="lock" disabled aria-describedby="note-m">Finalizovat závěr</Button></ButtonRow>
              <ExampleNote id="note-m">Nedostupné: tato aplikace nic nepodepisuje ani nerozhoduje.</ExampleNote>
            </PanelBody>
          </Panel>
        </div>
      </div>
      <h2 className="record-heading">Klinické údaje doložené před poradou</h2>
      <ClinicalRecordBody domains={prep.facts} sources={prep.sources} idPrefix="t-mdt-rec" />
      <h2 className="record-heading">Odeslání, osoba a podpora doložené před poradou</h2>
      <CareBody record={snapshot} idPrefix="t-mdt-care" snapshot />
      <PersonBody record={snapshot} idPrefix="t-mdt-person" />
    </div>
  )
}

/** Current recorded plan after the meeting; read-only, explicitly later than the preparation. */
function RecordedPlan({ detail, asOf }: { readonly detail: CaseDetail; readonly asOf: string | null }) {
  if (!detail.clinical) return <Unavailable title="Zaznamenaný plán není k dispozici" text="Pro tento případ zdroj dat nedodal strukturovaný záznam porady ani plánu." />
  return (
    <div className="record">
      <Notice tone="info" icon="clock" title={detail.clinical.coverage ? `Načtení dat${asOf ? ` ${formatDate(asOf)}` : ''}` : `Aktuální záznam${asOf ? ` k ${formatDate(asOf)}` : ''}`} role="note">
        {detail.clinical.coverage ? 'Zdroj žádný plán porady nedodal. Čas načtení nepotvrzuje aktuálnost klinických údajů.' : 'Obsahuje i údaje vzniklé po přípravě porady. Nejde o podklady, které měla porada k dispozici. Nic zde nelze upravit ani finalizovat.'}
      </Notice>
      <Panel id="t-mdt-plan" icon="team" title="Porady, závěry a navazující kroky">
        <PanelBody><PlanFacts facts={detail.clinical.domains.mdtPlan} sources={detail.clinical.sources} empty="Žádný závěr ani plán není zaznamenán." /></PanelBody>
      </Panel>
    </div>
  )
}

type MdtViewProps = RoleViewProps & ClinicianNavigation

/** MDT: its own list of available cases, then one exact case per page (frozen preparation, or the separately routed recorded plan). */
export function MdtView({ workspace, detail, route, onNavigate, onReturn }: MdtViewProps) {
  if (route.page === 'list' || (route.page !== 'detail' && route.page !== 'invalid-detail')) {
    return (
      <>
        <ViewHead id="t-mdt" icon="team" title="MDT: pacienti pro MDT" lead="Případy dostupné ze zdroje dat. Nejde o program porady ani o potvrzené zařazení na poradu." />
        {workspace.status === 'ready' ? (
          workspace.value.queue.length === 0
            ? <EmptyState title="Žádné případy" text="Zdroj dat teď nenabízí žádný případ." />
            : (
              <Panel id="t-mdt-list" title={<>Pacienti pro MDT <span className="tag tag--neutral">{workspace.value.queue.length}</span></>}>
                <MdtCaseTable labelledBy="t-mdt-list" queue={workspace.value.queue} onNavigate={onNavigate} />
              </Panel>
            )
        ) : workspace.status === 'error' ? <ErrorState error={workspace.error} /> : <LoadingState />}
      </>
    )
  }
  if (route.page === 'invalid-detail' || route.view !== 'mdt') {
    return (
      <>
        <BackToList role="mdt" label="Zpět na pacienty pro MDT" onReturn={onReturn} />
        <ViewHead id="t-mdt" icon="team" title="MDT: případ" />
        <InvalidCaseState />
      </>
    )
  }
  const section: MdtSection = route.section ?? 'preparation'
  const caseId = route.caseId
  // Only a fresh snapshot of the exact requested case may be shown as current.
  const matching: typeof detail = detail.status === 'ready' && (!detail.fresh || detail.value.identity.caseId !== caseId) ? { status: 'loading' } : detail
  const prep = matching.status === 'ready' ? matching.value.mdt.preparation : undefined
  const title = section === 'plan' ? 'MDT: zaznamenaný plán po poradě' : `MDT: příprava porady${prep ? ` ${formatDate(prep.meetingDate)}` : ''}`
  return (
    <>
      <BackToList role="mdt" label="Zpět na pacienty pro MDT" onReturn={onReturn} />
      <ViewHead id="t-mdt" icon="team" title={title} lead="Závěr finalizuje předseda porady, ne systém." />
      <MdtNav caseId={caseId} current={section} onNavigate={onNavigate} />
      <CaseGate workspace={workspace} detail={matching}>
        {value => (
          <>
            <MdtWho detail={value} />
            {section === 'plan'
              ? <RecordedPlan detail={value} asOf={workspace.status === 'ready' ? workspace.value.asOf : null} />
              : value.mdt.preparation
                ? <Preparation prep={value.mdt.preparation} />
                : <Unavailable title="Příprava porady není k dispozici" text="Pro tento případ zdroj dat nedodal uzavřenou přípravu porady. Aktuální údaje případu se sem záměrně nedoplňují. Na seznamu můžete vybrat jiného pacienta." />}
          </>
        )}
      </CaseGate>
    </>
  )
}
