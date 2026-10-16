import type { ClinicalCoverage } from '../../../data/clinical'
import type { CollectionCoverage, CoverageReason } from '../../../data/coverage'
import { Notice } from '../../../components/ui/Notice'

type Section = keyof ClinicalCoverage
const LABEL: Readonly<Record<Section, string>> = { conditions: 'Onemocnění', observations: 'Pozorování, laboratorní výsledky a měření', diagnosticReports: 'Zprávy z vyšetření', documents: 'Metadata dokumentů' }
const ORDER = Object.keys(LABEL) as Section[]

const TOO_LARGE = 'Načítání překročilo bezpečnostní limit aplikace. Úplnost této části proto nebylo možné ověřit.'
const NOT_REACHED = 'Zdroj dat se nepodařilo spolehlivě kontaktovat, takže jeho obsah nebyl ověřen.'
const UNSAFE = 'Odpověď zdroje nešlo bezpečně zpracovat, proto ji aplikace nepoužila.'
const UNKNOWN = 'Přesný důvod není známý.'
/** Plain-language cause per reason; anything unknown falls back to a neutral sentence (never "nothing exists"). */
const REASON: Readonly<Record<CoverageReason, string>> = {
  resource_limit: TOO_LARGE, truncated: TOO_LARGE,
  deadline_exceeded: 'Zdroj dat neodpověděl včas, takže jeho obsah nebyl ověřen.',
  upstream_error: NOT_REACHED, upstream_unavailable_or_incomplete: UNKNOWN,
  auth_failed: 'Aplikace nezískala ke zdroji dat přístup, takže jeho obsah nebyl ověřen.',
  invalid_response: UNSAFE, unsafe_paging_link: UNSAFE, paging_cycle: UNSAFE, duplicate_resource: UNSAFE, inconsistent_total: UNSAFE,
}

const known = (n: number | null | undefined): n is number => typeof n === 'number' && Number.isInteger(n) && n >= 0
/** Counts are shown only as reported facts — never as a difference or a "X z Y" ratio. */
function counts(detail: CollectionCoverage | undefined): string | null {
  if (!detail) return null
  const received = known(detail.receivedCount) ? detail.receivedCount : null
  const total = known(detail.serverTotal) ? detail.serverTotal : null
  if (received !== null && total !== null) return `Přijato záznamů: ${received}; zdroj uvádí celkem: ${total}.`
  if (received !== null) return `Přijato záznamů: ${received}; celkový počet zdroj neuvedl.`
  if (total !== null) return `Zdroj uvádí celkem záznamů: ${total}.`
  return null
}

interface Props {
  readonly coverage: ClinicalCoverage | undefined
  /** Optional per-section detail (reason, counters). Without it the notice still names the missing sections. */
  readonly detail?: Readonly<Partial<Record<Section, CollectionCoverage>>> | undefined
}

export function CoverageNotice({ coverage, detail }: Props) {
  if (!coverage) return null
  const failed = ORDER.filter(key => coverage[key] === 'unavailable')
  if (!failed.length) return null
  const title = failed.length === 1 ? `Nepodařilo se načíst: ${LABEL[failed[0]!]}` : 'Některé části záznamu se nepodařilo načíst'
  return <Notice tone="warning" icon="database" title={title} role="status">
    <ul className="coverage-notice__list">
      {failed.map(key => {
        const info = detail?.[key]
        const reason = info?.reason ? REASON[info.reason] ?? UNKNOWN : UNKNOWN
        const count = counts(info)
        return <li key={key}>
          {failed.length > 1 && <b>{LABEL[key]}: </b>}{reason}{count && <span className="coverage-notice__count"> {count}</span>}
        </li>
      })}
    </ul>
    <p className="coverage-notice__meaning">
      {failed.length === 1 ? 'Tato část se proto nezobrazuje vůbec, ani zčásti.' : 'Tyto části se proto nezobrazují vůbec, ani zčásti.'} Nelze z toho usuzovat, že údaje neexistují, ani že jsou v pořádku. Ostatní dostupné části zůstávají zobrazeny.
    </p>
  </Notice>
}
