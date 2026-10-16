import type { ClinicalCoverage } from '../../../data/clinical'
import { Notice } from '../../../components/ui/Notice'

const LABEL = { conditions: 'Onemocnění', observations: 'Pozorování, laboratorní výsledky a měření', diagnosticReports: 'Zprávy z vyšetření', documents: 'Metadata dokumentů' } as const
export function CoverageNotice({ coverage }: { readonly coverage: ClinicalCoverage | undefined }) {
  if (!coverage) return null
  const failed = (Object.keys(LABEL) as (keyof ClinicalCoverage)[]).filter(key => coverage[key] === 'unavailable')
  if (!failed.length) return null
  return <Notice tone="warning" icon="database" title="Část zdrojových dat není dostupná" role="status">
    {failed.map(key => LABEL[key]).join('; ')}. Není to potvrzení, že tyto údaje neexistují. Ostatní dodané údaje zůstávají zobrazeny.
  </Notice>
}
