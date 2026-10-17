import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { Button } from '../../components/ui/Button'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Tag } from '../../components/ui/Tag'
import { Icon } from '../../icons/Icon'
import type { UploadCapability, UploadJob, UploadReviewSummary, UploadStatus } from '../../data/backend/uploads'
import { useUploads } from '../../hooks/useUploads'
import { UploadProgress } from './newUploadProgress'
import { ReviewDialog } from './ReviewDialog'
import './uploadPanel.css'

interface UploadPanelProps {
  readonly capability: UploadCapability | null
  readonly caseId: string
  readonly mockMode: boolean
}

function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return 'neznámá velikost'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} kB`
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`
}

function statusTag(status: UploadStatus): { tone: 'info' | 'success' | 'warning' | 'danger' | 'neutral'; icon: 'clock' | 'check' | 'alert' | 'info' | 'missing'; text: string } {
  if (status === 'queued') return { tone: 'info', icon: 'clock', text: 'Ve frontě' }
  if (status === 'running') return { tone: 'info', icon: 'clock', text: 'Zpracovává se' }
  if (status === 'complete') return { tone: 'success', icon: 'check', text: 'Hotovo ke kontrole' }
  if (status === 'manual-review') return { tone: 'warning', icon: 'alert', text: 'Ke kontrole člověkem' }
  if (status === 'failed') return { tone: 'danger', icon: 'alert', text: 'Nezdařilo se' }
  if (status === 'cancelled') return { tone: 'neutral', icon: 'info', text: 'Zrušeno' }
  return { tone: 'neutral', icon: 'info', text: 'Přerušeno restartem' }
}

function JobCard({ job, capability, caseId }: { readonly job: UploadJob; readonly capability: UploadCapability; readonly caseId: string }) {
  const tag = statusTag(job.status)
  const counts = Object.entries(job.counts)
  const last = job.events[job.events.length - 1] ?? null
  const [open, setOpen] = useState(false)
  const [localReview, setLocalReview] = useState<UploadReviewSummary | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const shown = localReview ? { ...job, review: localReview } : job
  const reviewWired = capability.fetchReview !== undefined && capability.fetchModelText !== undefined
  const failedWithDraft = job.status === 'failed' && job.review !== undefined && job.review !== null
  const showReview = reviewWired && (job.status === 'complete' || job.status === 'manual-review' || failedWithDraft)
  function openReview() {
    if (showReview) setOpen(true)
  }
  return (
    <li className="upload-job" onDoubleClick={openReview}>
      <div className="upload-job__head">
        <span className="upload-job__name">{job.filename}</span>
        <Tag label={tag} />
      </div>
      <p className="meta">Rozpoznaný formát: {job.detectedType ? job.detectedType : 'zatím nezjištěn'}</p>
      {job.newFormat && (job.status === 'queued' || job.status === 'running') && (
        <p className="notice notice--warning"><Icon name="clock" /><span><strong>Nový formát – zpracování může trvat déle.</strong> Server takový soubor ještě nezná a zkouší ho rozluštit krok za krokem.</span></p>
      )}
      {job.recipeReuse && (
        <p className="notice notice--success"><Icon name="check" /><span><strong>Opakovaný formát.</strong> Použil se osvědčený postup, proto to bylo rychlejší.</span></p>
      )}
      {counts.length > 0 && (
        <p className="meta">Počty: {counts.map(([key, value]) => `${key}: ${value}`).join(' · ')}</p>
      )}
      <UploadProgress job={shown} />
      {job.status === 'manual-review' && (
        <p className="notice notice--warning"><Icon name="alert" /><span><strong>Potřebuje kontrolu člověkem.</strong>{last ? ` Poslední krok: ${last.label}.` : ''} Originál zůstává trvale uložený.</span></p>
      )}
      {job.status === 'failed' && (
        <p className="notice notice--danger"><Icon name="alert" /><span><strong>Zpracování se nezdařilo.</strong>{last ? ` Poslední krok: ${last.label}.` : ''} Originál zůstává trvale uložený.</span></p>
      )}
      <p className="meta">Model: {job.model.model} · {job.model.providerId} · režim {job.model.mode}</p>
      <div className="btn-row">
        <a className="btn btn--secondary" href={capability.originalUrl(job.id)} download><Icon name="file" />Stáhnout originál</a>
        <a className="btn btn--secondary" href={capability.exportUrl(job.id)} download><Icon name="database" />Stáhnout balíček (ZIP)</a>
        {showReview && (
          <button ref={triggerRef} type="button" className="btn btn--secondary" aria-haspopup="dialog" onClick={openReview}>
            <Icon name="eye" />Zkontrolovat / upravit
          </button>
        )}
      </div>
      {open && showReview && (
        <ReviewDialog
          key={`${caseId}:${job.id}`}
          capability={capability}
          caseId={caseId}
          job={job}
          returnFocus={triggerRef}
          onClose={() => setOpen(false)}
          onChanged={setLocalReview}
        />
      )}
    </li>
  )
}

export function UploadPanel({ capability, caseId, mockMode }: UploadPanelProps) {
  const uploads = useUploads(mockMode ? null : capability, caseId)
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const enabled = !mockMode && capability !== null && uploads.caps !== null && uploads.caps.enabled
  const disabledReason = mockMode
    ? 'Ukázkový režim bez serveru: nahrávání je vypnuté, nic se nikam neposílá.'
    : capability === null
      ? 'Nahrávání není v tomto pohledu k dispozici.'
      : uploads.capsPending
        ? null
        : uploads.capsNote ?? (uploads.caps && !uploads.caps.enabled
          ? uploads.caps.reason === 'forbidden_role'
            ? 'Vaše role nemůže nahrávat soubory.'
            : 'Převod je na serveru vypnutý. Soubory teď nahrát nejde.'
          : null)

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setOver(false)
    if (!enabled) return
    const files = Array.from(event.dataTransfer?.files ?? [])
    if (files.length > 0) uploads.queueFiles(files)
  }

  return (
    <Panel id="t-upload" icon="file" title="Nahrání podkladu" meta="Jeden soubor po druhém, originál zůstává trvale uložený.">
      <PanelBody>
        {disabledReason && (
          <p className="notice"><Icon name="lock" /><span>{disabledReason}</span></p>
        )}
        {!mockMode && capability !== null && uploads.caps !== null && uploads.caps.enabled && !uploads.caps.aiAvailable && (
          <p className="notice notice--info"><Icon name="info" /><span><strong>Server nemá klíč k umělé inteligenci.</strong> Soubor se bezpečně uloží a výsledek připraví ke kontrole člověkem.</span></p>
        )}
        {enabled && (
          <div className={over ? 'upload-drop upload-drop--over' : 'upload-drop'} onDragOver={event => { event.preventDefault(); setOver(true) }}
            onDragLeave={() => setOver(false)} onDrop={onDrop}>
            <Icon name="file" />
            <p><strong>Vyberte soubory</strong> nebo je sem přetáhněte.</p>
            <p className="meta">Libovolný typ kromě spustitelných, každý do 5 MiB. Neznámý soubor server přijme a prozkoumá.</p>
            <input ref={inputRef} type="file" multiple className="upload-drop__input" aria-label="Vybrat soubory k nahrání"
              aria-describedby="upload-drop-hint" onChange={event => {
                const files = Array.from(event.target.files ?? [])
                event.target.value = ''
                if (files.length > 0) uploads.queueFiles(files)
              }} />
            <p className="meta" id="upload-drop-hint">Odesílá se po jednom souboru, aby server stíhal.</p>
          </div>
        )}
        {uploads.pending.length > 0 && (
          <section aria-label="Fronta k odeslání">
            <h3 className="label">Fronta k odeslání</h3>
            <ul className="upload-queue">
              {uploads.pending.map(item => (
                <li key={item.key} className="upload-queue__item">
                  <span className="upload-queue__name">{item.file.name} <span className="meta">({formatBytes(item.file.size)})</span></span>
                  {item.state === 'uploading' && <Tag label={{ tone: 'info', icon: 'clock', text: 'Odesílá se' }} />}
                  {item.state === 'waiting' && <Tag label={{ tone: 'neutral', icon: 'clock', text: 'Čeká' }} />}
                  {item.note && <span className="meta">{item.note}</span>}
                  {(item.state === 'needs-retry' || item.state === 'blocked') && (
                    <span className="btn-row">
                      {item.state === 'needs-retry' && <Button variant="secondary" onClick={() => uploads.retry(item.key)}>Zkusit znovu</Button>}
                      <Button variant="secondary" onClick={() => uploads.remove(item.key)}>Odebrat</Button>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        {uploads.jobsNote && (
          <p className="notice notice--warning"><Icon name="alert" /><span>{uploads.jobsNote}</span></p>
        )}
        {uploads.jobs.length > 0 && (
          <section aria-label="Nahrané soubory">
            <h3 className="label">Nahrané soubory ({uploads.jobs.length})</h3>
            <ul className="upload-jobs">
              {uploads.jobs.map(job => (capability ? <JobCard key={job.id} job={job} capability={capability} caseId={caseId} /> : null))}
            </ul>
          </section>
        )}
        {uploads.busy && <p className="meta" role="status">Odesílám soubor…</p>}
      </PanelBody>
    </Panel>
  )
}
