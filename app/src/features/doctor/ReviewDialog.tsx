import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { UploadCapability, UploadJob, UploadReviewSummary } from '../../data/backend/uploads'
import { useUploadReview } from '../../hooks/useUploadReview'
import { Icon } from '../../icons/Icon'

interface ReviewDialogProps {
  readonly capability: UploadCapability
  readonly caseId: string
  readonly job: UploadJob
  readonly returnFocus: { readonly current: HTMLElement | null }
  readonly onClose: () => void
  readonly onChanged: (summary: UploadReviewSummary) => void
}

const LOCKED_STATES: readonly string[] = ['importing', 'imported', 'import-uncertain']

function approvalHelp(reason: string | null): string {
  if (reason === 'already_imported') return 'Už bylo importováno, proto schválení není potřeba.'
  if (reason === 'import_locked') return 'Import je právě zamčený jinou operací.'
  if (reason === 'invalid_candidate') return 'Uložená verze není platná, opravte ji a uložte znovu.'
  if (reason === 'not_configured') return 'Import není na serveru nastavený.'
  if (reason === 'forbidden') return 'Váš účet nemůže schvalovat změny.'
  return 'Služba není dostupná. Zkuste to prosím později.'
}

function draftCopy(reason: string | null): readonly [string, string] {
  if (reason === 'legacy-bundle-fallback') return ['Kandidát pochází z uloženého balíčku.', 'Surový výstup modelu se nedochoval, kandidát byl převzat z uloženého balíčku. Návrh se nedoplňuje automaticky, dopište ho ručně.']
  if (reason === null || reason === 'legacy-draft-missing') return ['Starší záznam bez uloženého výstupu modelu.', 'Návrh se nedoplňuje automaticky, kandidáta dopište ručně.']
  if (reason.startsWith('model-not-invoked:')) {
    const code = reason.slice(18)
    if (code === 'image_no_ocr' || code === 'scan_no_ocr') return ['Model soubor nečetl.', 'Tento záznam vznikl před podporou obrázků a model ho neviděl. Automaticky se nedoplňuje, soubor prosím nahrajte znovu.']
    if (code === 'secret_missing' || code === 'secret_empty' || code === 'secret_unreadable' || code === 'secret_not_file' || code === 'secret_permissions' || code === 'secret_symlink' || code === 'azure_not_opted_in') return ['Převod modelem nebyl zapnutý.', 'Služba AI nebyla pro tento záznam zapnutá nebo nastavená, proto výstup nevznikl. Kandidáta dopište ručně.']
    return ['Model se pro tento záznam nespustil.', 'Výstup modelu nevznikl a automaticky se nedoplňuje. Kandidáta dopište ručně.']
  }
  if (reason.startsWith('model-failed:')) return ['Model převod nedokončil.', 'Výstup se nedochoval a automaticky se nedoplňuje. Kandidáta dopište ručně.']
  return ['Výstup modelu se nedochoval.', 'Důvod se nepodařilo bezpečně určit. Nic se nedoplňuje automaticky, kandidáta dopište ručně.']
}

function receiptPreview(value: unknown): string | null {
  if (value === null || value === undefined) return null
  try {
    const text = JSON.stringify(value, null, 2)
    return text.length <= 4000 ? text : text.slice(0, 4000)
  } catch {
    return null
  }
}

function countsText(counts: Readonly<Record<string, number>>): string {
  const entries = Object.entries(counts)
  return entries.length === 0 ? 'žádné' : entries.map(([key, value]) => `${key}: ${value}`).join(' · ')
}

export function ReviewDialog({ capability, caseId, job, returnFocus, onClose, onChanged }: ReviewDialogProps) {
  const view = useUploadReview(capability, caseId, job.id)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const closedRef = useRef(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const titleId = useId()
  const editorId = useId()
  const confirmId = useId()
  const setConfirmed = view.setConfirmed
  const notifyChanged = onChanged

  const review = view.review

  useEffect(() => {
    const node = dialogRef.current
    const trigger = returnFocus.current
    if (node && !node.open) node.showModal()
    titleRef.current?.focus()
    return () => {
      if (node?.open) node.close()
      if (closedRef.current && trigger?.isConnected) trigger.focus({ preventScroll: true })
    }
  }, [returnFocus])

  useEffect(() => {
    setConfirmed(false)
  }, [review?.revision, setConfirmed])

  useEffect(() => {
    if (review) {
      notifyChanged({ state: review.state, revision: review.revision, valid: review.validation.valid, updatedAt: review.updatedAt, reviewedBy: review.reviewedBy })
    }
  }, [review, notifyChanged])

  function doClose() {
    if (closedRef.current) return
    closedRef.current = true
    onClose()
  }

  function requestClose() {
    if (view.dirty && !confirmDiscard) {
      setConfirmDiscard(true)
      return
    }
    doClose()
  }

  const locked = review ? LOCKED_STATES.includes(review.state) : false
  const valid = review ? review.validation.valid : false
  const canApprove = review !== null && !locked && valid && !view.dirty && view.confirmed && view.approvalEnabled && !view.saving && !view.approving && !view.loading
  const approveHelp = review === null
    ? 'Nejprve je potřeba načíst uloženou verzi.'
    : locked
      ? 'Záznam je uzamčený a nelze ho dále schvalovat.'
      : !valid
        ? 'Uložená verze není platná. Opravte ji v editoru a uložte znovu.'
        : view.dirty
          ? 'Změny nejsou uložené ani ověřené. Nejprve je uložte.'
          : !view.confirmed
            ? 'Schválení potřebuje výslovné potvrzení pacienta níže.'
            : !view.approvalEnabled
              ? approvalHelp(view.approvalReason)
              : null
  const receipt = review ? receiptPreview(review.importReceipt) : null
  const issues = review ? review.validation.issues.slice(0, 20) : []

  return createPortal(
    <dialog
      ref={dialogRef}
      className="review-dialog"
      aria-labelledby={titleId}
      onCancel={event => { event.preventDefault(); requestClose() }}
      onClose={() => doClose()}
      onClick={event => { if (event.target === event.currentTarget) requestClose() }}
    >
      <header className="review-dialog__head">
        <h2 ref={titleRef} id={titleId} tabIndex={-1} className="review-dialog__title">Kontrola a úprava převodu</h2>
        <button type="button" className="btn btn--secondary" onClick={requestClose}>Zavřít</button>
      </header>
      <div className="review-dialog__body">
        <p className="meta">Soubor {job.filename} · případ {caseId}</p>
        {view.loading && <p className="meta" role="status">Načítám uloženou kontrolu…</p>}
        {view.error && <p className="notice notice--danger" role="alert"><Icon name="alert" /><span>{view.error}</span></p>}
        {view.conflict !== null && (
          <p className="notice notice--warning">
            <Icon name="alert" />
            <span><strong>Server má novější verzi (revize {view.conflict}).</strong> Rozepsaný text zůstal v editoru. Načtení ho zahodí a přepíše verzí ze serveru.</span>
          </p>
        )}
        {view.conflict !== null && (
          <div className="btn-row">
            <button type="button" className="btn btn--secondary" onClick={view.reload}>Načíst znovu ze serveru (zahodí rozepsané změny)</button>
          </div>
        )}
        {review && (
          <>
            <section aria-label="Zdroj a původ">
              <h3 className="label">Zdroj a původ (nelze měnit)</h3>
              <dl className="review-grid">
                <div><dt>Originál</dt><dd><a className="btn btn--secondary" href={capability.originalUrl(job.id)} download><Icon name="file" />Stáhnout originál</a></dd></div>
                <div><dt>Zdroj</dt><dd>{review.sourceUrn}</dd></div>
                <div><dt>Otisk zdroje</dt><dd className="review-mono">{review.sourceSha256}</dd></div>
                <div><dt>Pacient</dt><dd>{review.patientRef}</dd></div>
                <div><dt>Revize</dt><dd>{review.revision} · stav {review.state}</dd></div>
              </dl>
              {review.transcriptionUntrusted && (
                <p className="notice notice--warning"><Icon name="alert" /><span>Přepis vytvořil model a nebyl nezávisle ověřen. Porovnejte údaje s originálem.</span></p>
              )}
              {!review.modelDraftAvailable && (
                <p className="notice"><Icon name="info" /><span><strong>{draftCopy(review.modelDraftReason)[0]}</strong>{` ${draftCopy(review.modelDraftReason)[1]}`}</span></p>
              )}
            </section>
            <details className="review-tech">
              <summary className="review-tech__summary">Výstup modelu (pouze ke čtení)</summary>
              {view.modelLoading ? (
                <p className="meta" role="status">Načítám výstup modelu…</p>
              ) : view.modelError ? (
                <p className="notice notice--danger" role="alert"><Icon name="alert" /><span>Výstup modelu se nepodařilo načíst: {view.modelError} S kandidátem níže můžete pracovat dál.</span></p>
              ) : view.modelText === null || view.modelText === '' ? (
                <p className="meta">{draftCopy(review.modelDraftReason)[0]} {draftCopy(review.modelDraftReason)[1]} Pracujte s kandidátem níže.</p>
              ) : (
                <pre className="review-pre" tabIndex={0}>{view.modelText}</pre>
              )}
            </details>
            <section aria-label="Kandidát ke schválení">
              <h3 className="label">Kandidát FHIR ke schválení</h3>
              <p className="meta">Ověření uložené verze (revize {review.revision}): {review.validation.valid ? 'platná.' : 'neplatná.'} Počty: {countsText(review.counts)}.</p>
              {!review.validation.valid && issues.length > 0 && (
                <ul className="review-issues">
                  {issues.map((issue, index) => (
                    <li key={index}><strong>{issue.code}</strong>{issue.path ? ` · ${issue.path}` : ''} — {issue.message}</li>
                  ))}
                </ul>
              )}
              {view.dirty && (
                <p className="notice notice--warning"><Icon name="alert" /><span><strong>Změny nejsou uložené ani ověřené.</strong> Zobrazené ověření patří poslední uložené verzi, ne rozepsanému textu.</span></p>
              )}
              <label className="visually-hidden" htmlFor={editorId}>Kandidát FHIR ve formátu JSON</label>
              <textarea
                id={editorId}
                className="review-editor"
                rows={12}
                spellCheck={false}
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                readOnly={locked}
                value={view.text}
                onChange={event => { view.setConfirmed(false); view.setText(event.target.value) }}
              />
              {review.state === 'importing' && (
                <p className="notice notice--info"><Icon name="clock" /><span><strong>Import probíhá na serveru.</strong> Dialog můžete zavřít, import běží dál. Po znovuotevření se stav načte.</span></p>
              )}
              {review.state === 'import-uncertain' && (
                <p className="notice notice--warning"><Icon name="alert" /><span><strong>Výsledek importu nelze potvrdit. Neopakujte import, nejdřív se poraďte s podporou.</strong></span></p>
              )}
              {review.state === 'import-failed' && (
                <p className="notice notice--danger"><Icon name="alert" /><span><strong>Import se nezdařil.</strong> Návrh můžete upravit a uložit znovu.</span></p>
              )}
              {review.state === 'imported' && (
                <div className="review-receipt">
                  <p className="notice notice--success"><Icon name="check" /><span><strong>Importováno do záznamu případu.</strong> Záznam je uzamčený proti další úpravě.</span></p>
                  <p className="meta">Potvrzení: {review.approvalId ?? 'bez čísla'} · <a className="btn btn--secondary" href={capability.exportUrl(job.id)} download><Icon name="database" />Stáhnout balíček (ZIP)</a></p>
                  {receipt && (
                    <details className="review-tech">
                      <summary className="review-tech__summary">Potvrzení importu (pouze ke čtení)</summary>
                      <pre className="review-pre" tabIndex={0}>{receipt}</pre>
                    </details>
                  )}
                </div>
              )}
            </section>
            <div className="btn-row">
              <button type="button" className="btn btn--secondary" disabled={locked || view.saving || view.approving || view.loading || review === null} onClick={view.save}>
                {view.saving ? 'Ukládám…' : 'Uložit k další kontrole'}
              </button>
            </div>
            <p className="meta">Uložení nic nezapisuje do záznamu případu, jen uchová návrh k další kontrole. Import přidá klinické záznamy k vybranému případu a nezapisuje do karty pacienta. Pravdivost údajů musí posoudit člověk.</p>
            {!locked && review.state !== 'imported' && (
              <div className="review-confirm">
                <input id={confirmId} type="checkbox" checked={view.confirmed} onChange={event => view.setConfirmed(event.target.checked)} />
                <label htmlFor={confirmId}>Potvrzuji, že záznam patří případu {caseId} (pacient {review.patientRef}) a smí se importovat.</label>
              </div>
            )}
            <div className="btn-row">
              <button type="button" className="btn" disabled={!canApprove} onClick={view.approve}>
                {view.approving ? 'Importuji…' : 'Schválit a importovat'}
              </button>
            </div>
            {approveHelp && <p className="meta">{approveHelp}</p>}
            {confirmDiscard && (
              <div className="review-discard" role="group" aria-label="Neuložené změny">
                <p><strong>Zahodit rozepsané změny a zavřít?</strong> Text v editoru se ztratí, uložená verze zůstane.</p>
                <div className="btn-row">
                  <button type="button" className="btn btn--secondary" onClick={doClose}>Zahodit a zavřít</button>
                  <button type="button" className="btn" onClick={() => setConfirmDiscard(false)}>Pokračovat v úpravách</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </dialog>,
    document.body,
  )
}
