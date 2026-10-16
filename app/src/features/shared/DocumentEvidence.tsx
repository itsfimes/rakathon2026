import { Tag } from '../../components/ui/Tag'
import type { CaseDocument, SourceField } from '../../data/contracts'
import { sourceLine } from '../../lib/format'
import { documentLabel, REVIEWED_LOCAL } from '../../lib/labels'
import { ScopedDisclosure } from './ScopedDisclosure'

interface DocumentEvidenceProps {
  readonly documents: readonly CaseDocument[]
  /** Explicit excerpts for clinician views only, matched by documentId. Never passed for the patient. */
  readonly fields?: readonly SourceField[]
  readonly coordinatorLabels?: boolean
}

/** Per document: label and state (incl. local review) always visible; supplied sources and
    excerpts on demand. Only metadata exists in this app, never the full document. */
export function DocumentEvidence({ documents, fields = [], coordinatorLabels = false }: DocumentEvidenceProps) {
  return (
    <ul className="evidence">
      {documents.map(document => {
        const excerpts = fields.filter(field => field.documentId === document.id && field.quote)
        const count = document.sources.length + excerpts.length
        const label = coordinatorLabels ? document.coordinatorLabel ?? document.label : document.label
        return (
          <li key={document.id} className="evidence__item">
            <div className="evidence__row">
              <span className="evidence__label">{label}</span>
              <span className="checklist__tags">
                {document.reviewState === 'reviewed' && <Tag label={REVIEWED_LOCAL} />}
                <Tag label={documentLabel(document.state, document.stateLabel)} />
              </span>
            </div>
            {count === 0
              ? <p className="evidence__empty">Zdroj nebyl dodán.</p>
              : <ScopedDisclosure summary={excerpts.length > 0 ? `Zdroje a výňatky (${count})` : `Zdroje (${document.sources.length})`}>
                {document.sources.length > 0 && <ul className="evidence__sources">
                  {document.sources.map((source, index) => <li key={index}>{sourceLine(source)}</li>)}
                </ul>}
                {excerpts.map(field => (
                  <blockquote key={field.id} className="quote">„{field.quote}“
                    <cite>{field.label}{field.source ? ` · ${sourceLine(field.source)}` : ' · zdroj výňatku nebyl dodán'}</cite>
                  </blockquote>
                ))}
                <p className="meta">Jen dodaná metadata{excerpts.length > 0 ? ' a výňatky' : ''}. Plné znění dokumentu tu není k dispozici.</p>
              </ScopedDisclosure>}
          </li>
        )
      })}
    </ul>
  )
}
