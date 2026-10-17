import type { ReactNode } from 'react'
import type { CaseDetail } from '../../../data/contracts'
import { Icon } from '../../../icons/Icon'
import { Notice } from '../../../components/ui/Notice'
import { Panel, PanelBody } from '../../../components/ui/Panel'
import { formatDayMonth } from '../../../lib/format'
import { ageText, diagnosisText } from '../../../lib/labels'
import type { ClinicianRole, ClinicianSection, Route } from '../../../lib/routes'
import { RouteLink } from '../RouteLinks'
import { FactTags } from './FactBlock'
import { CareBody } from './CareBody'
import { ClinicalRecordBody } from './ClinicalRecordBody'
import { CoverageNotice } from './CoverageNotice'
import { PersonBody } from './PersonBody'
import { attentionItems, DOMAIN_LABEL, DOMAIN_SECTION, SECTION_LABEL } from './facts'

const SECTION_ICON = { overview: 'queue', record: 'file', care: 'calendar', person: 'person' } as const
const ORDER: readonly ClinicianSection[] = ['overview', 'record', 'care', 'person']

/** Real links between the four case sections; wraps into a grid on narrow screens, no tabs semantics. */
export function CaseSectionNav({ role, caseId, section, onNavigate }: {
  readonly role: ClinicianRole; readonly caseId: string; readonly section: ClinicianSection; readonly onNavigate: (route: Route) => void
}) {
  return (
    <nav className="section-nav" aria-label="Části případu">
      <ul>
        {ORDER.map(item => (
          <li key={item}>
            <RouteLink route={{ view: role, page: 'detail', caseId, ...(item === 'overview' ? {} : { section: item }) }} onNavigate={onNavigate}
              className="section-nav__link" current={item === section}>
              <Icon name={SECTION_ICON[item]} />{SECTION_LABEL[item]}
            </RouteLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** Compact case identity, shown once per case page. No identifiers beyond the label. */
export function CaseHeader({ detail }: { readonly detail: CaseDetail }) {
  const { identity } = detail
  return (
    <div className="case-header">
      <h2 className="case-header__who"><Icon name="person" />{identity.patientLabel} · {ageText(identity.age)}</h2>
      <span className="case-header__item">{identity.diagnosis ? `${identity.diagnosis.code} ${identity.diagnosis.label}` : diagnosisText(null)}</span>
      <span className="case-header__item"><Icon name="steth" />{identity.referrer ? `${identity.referrer.name} (${identity.referrer.specialty})` : 'Odesílající neuveden'}</span>
      {identity.acceptedAt && <span className="case-header__item"><Icon name="building" />v KOC od {formatDayMonth(identity.acceptedAt)}</span>}
    </div>
  )
}

function RecordUnavailable() {
  return (
    <div className="view__state">
      <Notice tone="warning" icon="database" title="Rozšířený klinický záznam není k dispozici" role="status">
        Pro tento případ zdroj dat žádný strukturovaný záznam nedodal. Nic se nedoplňuje ani neodhaduje.
      </Notice>
    </div>
  )
}

/** Unresolved items are visible on the overview with links to where they live. */
export function AttentionPanel({ detail, role, onNavigate }: { readonly detail: CaseDetail; readonly role: ClinicianRole; readonly onNavigate: (route: Route) => void }) {
  const id = `t-attention-${role}`
  if (!detail.clinical) {
    return (
      <Panel id={id} icon="alert" title="Upozornění">
        <PanelBody><p className="placeholder-text">Rozšířený klinický záznam pro tento případ není k dispozici, proto zde nic není vyhodnoceno.</p></PanelBody>
      </Panel>
    )
  }
  const items = attentionItems(detail.clinical.domains)
  return (
    <Panel id={id} icon="alert" title={<>Upozornění<span className="tag tag--neutral">{items.length}</span></>}>
      <PanelBody>
        {items.length === 0 ? <p className="placeholder-text">Žádný rozpor ani nejistota nejsou v záznamu označeny.</p> : (
          <ul className="attention">
            {items.map(item => (
              <li key={item.id}>
                <span className="attention__what"><span className="attention__domain">{DOMAIN_LABEL[item.domain]}</span>{item.title}</span>
                <FactTags fact={item.fact} />
                <RouteLink route={{ view: role, page: 'detail', caseId: detail.identity.caseId, section: DOMAIN_SECTION[item.domain] }} onNavigate={onNavigate} className="attention__link">
                  {SECTION_LABEL[DOMAIN_SECTION[item.domain]]}
                </RouteLink>
              </li>
            ))}
          </ul>
        )}
      </PanelBody>
    </Panel>
  )
}

/** Section body below the header. Overview is role-specific and passed in; the record sections are shared. */
export function CaseSectionBody({ detail, role, section, overview }: {
  readonly detail: CaseDetail; readonly role: ClinicianRole; readonly section: ClinicianSection; readonly overview: ReactNode
}) {
  if (section === 'overview') return <><CoverageNotice coverage={detail.clinical?.coverage} detail={detail.clinical?.collectionCoverage} />{overview}</>
  if (!detail.clinical) return <RecordUnavailable />
  const prefix = `t-${role}-${section}`
  if (section === 'record') return <ClinicalRecordBody domains={detail.clinical.domains} sources={detail.clinical.sources} coverage={detail.clinical.coverage} coverageDetail={detail.clinical.collectionCoverage} idPrefix={prefix} />
  if (section === 'care') return <CareBody record={detail.clinical} idPrefix={prefix} />
  return <PersonBody record={detail.clinical} idPrefix={prefix} />
}
