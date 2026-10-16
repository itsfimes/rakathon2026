import { CaseGate } from '../../components/shell/CaseGate'
import { ViewHead } from '../../components/shell/ViewHead'
import { Disclosure } from '../../components/ui/Disclosure'
import { NextStep } from '../../components/ui/NextStep'
import { Notice } from '../../components/ui/Notice'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Timeline } from '../../components/ui/Timeline'
import { Icon } from '../../icons/Icon'
import { calendarParts } from '../../lib/format'
import type { Route } from '../../lib/routes'
import type { RoleViewProps } from '../types'
import { RouteLink } from '../shared/RouteLinks'
import { ScopedDisclosure } from '../shared/ScopedDisclosure'
import { EventPanel } from './EventPanel'
import { HelperPanel } from './HelperPanel'
import { PatientRecordPage } from './PatientRecordPage'

const LANDING: Route = { view: 'pacient', page: 'view' }
const RECORD: Route = { view: 'pacient', page: 'record' }

/** True only for a valid calendar date strictly before the record's own "as of" day (not today's date).
    Same day is not earlier; undated or unparseable values are never classified as earlier. */
function isEarlier(date: string | undefined, asOf: string | null): boolean {
  if (!date || !asOf || !calendarParts(date) || !calendarParts(asOf)) return false
  return date.slice(0, 10) < asOf.slice(0, 10)
}

/** Calm, graphical patient view: what now, next date, journey, who helps; health data on its own page. */
export function PatientRoleView({ workspace, detail, route, onNavigate }: RoleViewProps) {
  const navigate = onNavigate ?? (() => {})
  const name = detail.status === 'ready' ? detail.value.identity.patientAddressLabel : null
  const asOf = workspace.status === 'ready' ? workspace.value.asOf : null
  if (route?.page === 'record') {
    return (
      <>
        <p className="back-link"><RouteLink route={LANDING} onNavigate={navigate}><Icon name="arrow" small />Zpět na přehled</RouteLink></p>
        <ViewHead id="t-pacient" icon="file" title={name ? `${name}: moje zdravotní údaje` : 'Moje zdravotní údaje'} />
        <CaseGate workspace={workspace} detail={detail}>
          {value => value.patient.record
            ? <PatientRecordPage record={value.patient.record} />
            : <div className="view__state"><Notice tone="warning" icon="database" title="Zdravotní údaje zatím nejsou k dispozici" role="status">
              Pro váš případ zatím nejsou k dispozici údaje ze zpráv. Nic se nedoplňuje ani neodhaduje.</Notice></div>}
        </CaseGate>
      </>
    )
  }
  return (
    <>
      <ViewHead id="t-pacient" icon="person" title={name ? `${name}: co vás čeká` : 'Pacient: co vás čeká'} />
      <CaseGate workspace={workspace} detail={detail}>
        {value => {
          const eventEarlier = isEarlier(value.patient.nextEvent?.date, asOf)
          // The instruction belongs to that event; once the event is only an earlier record, the instruction is too.
          const journey = value.patient.journey.map(item => item.state !== 'done' && isEarlier(item.date, asOf)
            ? { ...item, historical: true, note: 'Dříve uvedeno · aktuální stav zde není potvrzen' } : item)
          const journeyEarlier = journey.some(item => isEarlier(item.date, asOf))
          return (
            <div className="patient">
              <NextStep id="ns-p" title="Co teď" what={eventEarlier ? 'Další krok zatím není znám.' : value.patient.currentInstruction ?? 'Další krok zatím není znám.'}>
                {eventEarlier && <ScopedDisclosure icon="info" summary="Dříve uvedený pokyn"><p>{value.patient.currentInstruction}</p></ScopedDisclosure>}
              </NextStep>
              <EventPanel event={value.patient.nextEvent} earlier={eventEarlier} />
              <div className="patient__journey">
                <Panel id="t-journey" icon="calendar" title="Vaše cesta"
                  {...(journeyEarlier ? { meta: 'Termíny podle dřívějšího záznamu. Aktuální průběh zde není potvrzen.' } : {})}>
                  <PanelBody>{journey.length ? <Timeline items={journey} label="Vaše cesta" /> : <p className="placeholder-text">Průběh zatím není zaznamenán</p>}</PanelBody>
                </Panel>
              </div>
              <HelperPanel coordinator={value.patient.coordinator} />
              <section className="panel record-link" aria-labelledby="t-record-link">
                <div className="panel__body">
                  <h2 className="event__title" id="t-record-link"><Icon name="file" />Moje zdravotní údaje</h2>
                  <p>Výsledky, zprávy, léky, alergie a vaše přání ke sdílení, tak jak jsou zapsané ve zprávách.</p>
                  <RouteLink route={RECORD} onNavigate={navigate} className="btn btn--secondary">
                    {value.patient.record ? 'Otevřít moje zdravotní údaje' : 'Otevřít (zatím bez údajů)'}
                  </RouteLink>
                </div>
              </section>
              <Disclosure summary="Kdo je na poradě lékařů?">
                <p>Lékaři více oborů, například onkolog, chirurg, radiolog a patolog. Společně navrhnou další postup. O léčbě s vámi potom mluví váš lékař.</p>
              </Disclosure>
            </div>
          )
        }}
      </CaseGate>
    </>
  )
}
