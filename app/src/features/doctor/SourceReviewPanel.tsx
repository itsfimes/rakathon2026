import { Button, ButtonRow, ExampleNote } from '../../components/ui/Button'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { StackCell, Table } from '../../components/ui/Table'
import { Tag } from '../../components/ui/Tag'
import type { CaseDocument, SourceField } from '../../data/contracts'
import { sourceLine } from '../../lib/format'
import type { DemoActions } from '../../hooks/useDemoActions'
import { REVIEWED_LOCAL, sourceFieldLabel } from '../../lib/labels'
import { UnavailableNote } from '../shared/DemoNote'
import { ScopedDisclosure } from '../shared/ScopedDisclosure'

/** Value and certainty stay in the table; the literal excerpt and its provenance open on demand.
    A quote without source metadata is still shown, with that gap stated. */
function Excerpt({ field }: { readonly field: SourceField }) {
  const fallback = field.quote ? 'Hodnota není zvlášť uvedena; viz doslovný výňatek.' : 'Ve zdroji není uvedeno.'
  const value = <span className={field.value ? undefined : 'placeholder-text'}>{field.value ?? fallback}</span>
  if (field.quote) {
    return <>{value}
      <ScopedDisclosure icon="file" summary="Doslovný výňatek">
        <blockquote className="quote">„{field.quote}“<cite>{field.source ? sourceLine(field.source) : 'Zdroj výňatku nebyl dodán.'}</cite></blockquote>
      </ScopedDisclosure>
    </>
  }
  if (field.source) {
    return <>{value}
      <ScopedDisclosure icon="file" summary="Zdroj">
        <p>{sourceLine(field.source)}</p>
        <p className="meta">Doslovný výňatek nebyl dodán.</p>
      </ScopedDisclosure>
    </>
  }
  return value
}

/** Supplied documents behind the fields, in first-mention order; ids without a supplied document are skipped. */
function reviewedDocuments(fields: readonly SourceField[], documents: readonly CaseDocument[]): CaseDocument[] {
  const ids = [...new Set(fields.map(field => field.documentId))]
  return ids.flatMap(id => documents.filter(document => document.id === id))
}

/** Source excerpts with honest certainty. The local review mark belongs to a whole document, so it is
    offered once per document after the table, with its scope explained before the buttons. */
export function SourceReviewPanel({ fields, documents, actions }: { readonly fields: readonly SourceField[]; readonly documents: readonly CaseDocument[]; readonly actions: DemoActions }) {
  const reviewable = actions.available ? reviewedDocuments(fields, documents) : []
  return (
    <Panel id="t-src" icon="file" title="Výpis z dokumentace ke kontrole"
      meta="Žádná umělá inteligence nic nezpracovává. Každý údaj potvrzuje lékař.">
      <Table labelledBy="t-src" columns={['Údaj', 'Hodnota a výňatek', 'Stav']}>
        {fields.map(field => (
          <tr key={field.id}>
            <StackCell label="Údaj"><b>{field.label}</b></StackCell>
            <StackCell label="Hodnota"><Excerpt field={field} /></StackCell>
            <StackCell label="Stav">
              <span className="checklist__tags">
                <Tag label={sourceFieldLabel(field)} />
                {field.reviewState === 'reviewed' && <Tag label={REVIEWED_LOCAL} />}
              </span>
            </StackCell>
          </tr>
        ))}
      </Table>
      <PanelBody>
        {reviewable.length > 0 && <section className="case-section review-docs" aria-labelledby="t-src-review">
          <h3 className="label case-section__label" id="t-src-review">Kontrola podkladů (lokálně v demu)</h3>
          <ExampleNote id="note-l-local">Označení platí pro celý podklad a všechny jeho údaje, jen v tomto okně. Není to klinické schválení, nejistotu ani chybějící údaj neodstraní.</ExampleNote>
          <ul className="review-docs__list">
            {reviewable.map(document => (
              <li key={document.id} className="review-docs__item">
                <span className="evidence__label">{document.label}</span>
                {document.reviewState === 'reviewed'
                  ? <Tag label={REVIEWED_LOCAL} />
                  : <Button variant="secondary" disabled={actions.busy} aria-describedby="note-l-local" onClick={() => actions.markReviewed(document.id)}>
                    <span>Označit podklad jako zkontrolovaný<span className="visually-hidden">: {document.label}</span></span>
                  </Button>}
              </li>
            ))}
          </ul>
        </section>}
        <ButtonRow>
          <Button disabled aria-describedby="note-l">Potvrdit výpis</Button>
          <Button variant="secondary" disabled aria-describedby="note-l">Upravit</Button>
        </ButtonRow>
        <UnavailableNote id="note-l" />
      </PanelBody>
    </Panel>
  )
}
