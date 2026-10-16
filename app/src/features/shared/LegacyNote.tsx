import { Notice } from '../../components/ui/Notice'
import { formatDate } from '../../lib/format'

/** Older demo process data (before the record's as-of date) is labelled, never presented as the current plan. */
export function LegacyProcessNote({ dates, asOf }: { readonly dates: readonly (string | null | undefined)[]; readonly asOf: string | null }) {
  const latest = dates.reduce<string>((max, date) => date && date > max ? date : max, '')
  if (!asOf || !latest || latest.slice(0, 10) >= asOf) return null
  return (
    <div className="legacy-note">
      <Notice tone="warning" icon="clock" title="Údaje o procesu jsou ze starší části ukázky" role="note">
        Poslední uvedený termín procesu je {formatDate(latest)}. Nejde o aktuální stav k {formatDate(asOf)}; zdravotní údaje v ostatních částech mají vlastní data.
      </Notice>
    </div>
  )
}
