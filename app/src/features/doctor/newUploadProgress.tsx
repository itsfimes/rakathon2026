import { Icon } from '../../icons/Icon'
import type { UploadJob, UploadStatus } from '../../data/backend/uploads'

interface UploadProgressProps {
  readonly job: UploadJob
}

type StepState = 'done' | 'current' | 'waiting'

interface Step {
  readonly key: string
  readonly title: string
  readonly hint: string | null
  readonly state: StepState
  readonly icon: 'check' | 'clock' | 'info' | 'alert'
}

const CODE_LABELS: Readonly<Record<string, string>> = {
  queued: 'Zařazeno do fronty',
  running: 'Zpracování běží',
  known_start: 'Začátek převodu známého formátu',
  known_bypass: 'Známý formát, přímý převod',
  planner_start: 'Hledání postupu pro nový formát',
  new_format_detected: 'Zjištěn nový formát',
  cache_reuse: 'Opakovaný formát, osvědčený postup',
  planner_recipe: 'Postup navržený pomocníkem',
  planner_fallback: 'Záložní luštění bez pomocníka',
  decode_done: 'Rozluštění dokončeno',
  fhir_start: 'Převod do zdravotního formátu',
  charset_utf8: 'Čtení textu UTF-8',
  charset_utf16: 'Čtení textu UTF-16',
  charset_cp1250: 'Čtení textu Windows-1250',
  charset_windows1250: 'Čtení textu Windows-1250',
  charset_iso88592: 'Čtení textu ISO-8859-2',
  xml_safe: 'Bezpečné čtení XML',
  html_strip: 'Čištění webové stránky',
  xlsx_bounded: 'Čtení tabulky',
  rtf_text: 'Čtení RTF textu',
  zip_members: 'Čtení souborů z archivu',
  hl7_text: 'Čtení HL7 zprávy',
  rejected_executable: 'Odmítnuto: spustitelný soubor',
  rejected_encrypted: 'Odmítnuto: šifrovaný obsah',
  rejected_binary: 'Odmítnuto: nečitelná data',
  manual_review: 'Předáno ke kontrole člověkem',
}

const STATUS_TEXT: Readonly<Record<string, string>> = {
  ok: 'hotovo',
  failed: 'nezdařilo se',
  tried: 'zkoušeno',
  stale: 'zastaralé',
  'no-agent': 'bez pomocníka AI',
}

const REVIEW_BADGE: Readonly<Record<string, string>> = {
  pending: 'Čeká na kontrolu člověkem',
  draft: 'Rozpracovaná ruční kontrola',
  importing: 'Import do záznamu probíhá',
  imported: 'Importováno do záznamu',
  'import-failed': 'Import se nezdařil, návrh lze upravit znovu',
  'import-uncertain': 'Výsledek importu je nejistý',
}

function isPlaceholder(label: string): boolean {
  return /^Krok \d+$/.test(label.trim())
}

function humanize(code: string): string {
  return code.replace(/[_.-]+/g, ' ').trim() || 'záznam bez popisu'
}

function codeOf(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase()
}

function outcomeOf(status: string | null | undefined): string {
  const key = (status ?? '').trim().toLowerCase()
  return STATUS_TEXT[key] ?? (key === '' ? 'bez výsledku' : key)
}

function entryLabel(job: UploadJob, index: number): { text: string; described: boolean } {
  const entry = job.events[index]
  if (!entry) return { text: 'Záznam bez popisu', described: false }
  const code = codeOf(entry.code)
  if (entry.label && !isPlaceholder(entry.label)) return { text: entry.label, described: true }
  if (code !== '') return { text: CODE_LABELS[code] ?? humanize(code), described: true }
  if (entry.detail) return { text: entry.detail, described: true }
  return { text: 'Záznam bez popisu', described: false }
}

function terminalOf(status: UploadStatus): boolean {
  return status === 'complete' || status === 'manual-review' || status === 'failed' || status === 'cancelled' || status === 'interrupted'
}

function lastStatus(job: UploadJob, wanted: string): string | null {
  let found: string | null = null
  for (const entry of job.events) {
    if (codeOf(entry.code) === wanted) found = codeOf(entry.status)
  }
  return found
}

function hasCode(job: UploadJob, wanted: string): boolean {
  return job.events.some(entry => codeOf(entry.code) === wanted)
}

function phaseText(job: UploadJob, decodeOk: boolean, fhirStarted: boolean): string {
  if (job.status === 'queued') return 'Čeká ve frontě na serveru.'
  if (job.status === 'complete') return 'Převod je hotový ke kontrole.'
  if (job.status === 'manual-review') return 'Soubor čeká na kontrolu člověkem, nic se samo nezapsalo.'
  if (job.status === 'failed') return 'Převod se nezdařil, originál zůstává uložený.'
  if (job.status === 'cancelled') return 'Zpracování bylo zrušeno, originál zůstává uložený.'
  if (job.status === 'interrupted') return 'Zpracování přerušil restart serveru.'
  if (fhirStarted) return 'Server převádí rozluštěný text do zdravotního formátu.'
  if (decodeOk) return 'Text je rozluštěný, server ho převádí do zdravotního formátu.'
  if (job.newFormat) return 'Server převádí neznámý formát, může to trvat déle.'
  if (job.detectedType.trim() === '') return 'Server rozpoznává formát souboru.'
  return 'Server soubor převádí.'
}

function stepsOf(job: UploadJob, decodeOk: boolean, fhirStarted: boolean): Step[] {
  const terminal = terminalOf(job.status)
  const seen = Math.max(job.eventCount, job.events.length)
  const accepted: Step = {
    key: 'accepted',
    title: 'Přijato na server',
    hint: seen > 0 ? 'Server soubor přijal.' : 'Čeká na potvrzení serveru.',
    state: seen > 0 || terminal ? 'done' : 'current',
    icon: seen > 0 || terminal ? 'check' : 'clock',
  }
  const decode: Step = {
    key: 'decode',
    title: 'Rozpoznání a rozluštění',
    hint: decodeOk
      ? (job.recipeReuse ? 'Hotovo s osvědčeným postupem.' : 'Text se podařilo přečíst.')
      : job.status === 'queued'
        ? 'Server se k souboru ještě nedostal.'
        : terminal
          ? 'Rozluštění zůstalo nedokončené, proto je potřeba člověk.'
          : seen > 0
            ? `Server zatím hlásí ${seen} ${seen === 1 ? 'mezikrok' : seen >= 2 && seen <= 4 ? 'mezikroky' : 'mezikroků'}.`
            : 'Server formát zatím neurčil.',
    state: decodeOk ? 'done' : job.status === 'queued' ? 'waiting' : 'current',
    icon: decodeOk ? 'check' : terminal ? 'alert' : 'clock',
  }
  const model: Step = {
    key: 'model',
    title: 'Převod a kontrola',
    hint: job.status === 'complete'
      ? 'Převod skončil.'
      : fhirStarted
        ? 'Rozluštěný text se převádí do zdravotního formátu.'
        : terminal
          ? 'K převodu modelem se nedošlo.'
          : 'Čeká na rozluštěný text.',
    state: job.status === 'complete' ? 'done' : fhirStarted || (terminal && decodeOk) ? 'current' : 'waiting',
    icon: job.status === 'complete' ? 'check' : fhirStarted || (terminal && decodeOk) ? 'clock' : 'info',
  }
  const outcome: Step = {
    key: 'outcome',
    title: 'Výsledek',
    hint:
      job.status === 'complete'
        ? 'Hotovo ke kontrole.'
        : job.status === 'manual-review'
          ? 'Předáno člověku, nejde o hotový zápis.'
          : job.status === 'failed'
            ? 'Nezdařilo se, originál je uložený.'
            : job.status === 'cancelled'
              ? 'Zrušeno.'
              : job.status === 'interrupted'
                ? 'Přerušeno restartem.'
                : 'Výsledek zatím není.',
    state: terminal ? 'done' : 'waiting',
    icon: terminal ? (job.status === 'failed' ? 'alert' : 'check') : 'info',
  }
  return [accepted, decode, model, outcome]
}

export function UploadProgress({ job }: UploadProgressProps) {
  const decodeOk = lastStatus(job, 'decode_done') === 'ok' || hasCode(job, 'fhir_start') || job.status === 'complete'
  const fhirStarted = hasCode(job, 'fhir_start') || job.status === 'complete'
  const steps = stepsOf(job, decodeOk, fhirStarted)
  const review = job.review ?? null
  const badge = review ? (REVIEW_BADGE[review.state] ?? review.state) : null
  const total = Math.max(job.eventCount, job.events.length)
  const rows = job.events.map((entry, index) => ({ entry, index, ...entryLabel(job, index) }))
  const meaningful = rows.filter(row => row.described)
  const hiddenCount = rows.length - meaningful.length
  return (
    <div className="upload-progress">
      <p className="upload-progress__phase" role="status">
        <Icon name={job.status === 'failed' || job.status === 'manual-review' ? 'alert' : 'clock'} />
        <span>{phaseText(job, decodeOk, fhirStarted)}</span>
      </p>
      {badge && review && (
        <p className="meta"><strong>Kontrola: {badge}.</strong> Revize {review.revision} · uložená verze {review.valid ? 'platná' : 'neplatná'}.</p>
      )}
      <ol className="upload-progress__list">
        {steps.map(step => (
          <li
            key={step.key}
            className={`upload-progress__item upload-progress__item--${step.state}`}
            {...(step.state === 'current' ? { 'aria-current': 'step' } : {})}
          >
            <span className="upload-progress__dot" aria-hidden="true">
              <Icon name={step.icon} />
            </span>
            <span className="upload-progress__body">
              <span className="upload-progress__title">{step.title}</span>
              {step.hint && <span className="meta"> {step.hint}</span>}
            </span>
          </li>
        ))}
      </ol>
      <details className="upload-tech">
        <summary className="upload-tech__summary">Technický průběh ({total})</summary>
        {meaningful.length > 0 ? (
          <ol className="upload-tech__list">
            {meaningful.map(row => (
              <li key={`${job.id}-tech-${row.index}`}>
                <span>{row.text}</span>
                <span className="meta"> · {outcomeOf(row.entry.status)}</span>
                {row.entry.detail && <span className="meta"> · {row.entry.detail}</span>}
              </li>
            ))}
          </ol>
        ) : (
          <p className="meta">Server zatím neposlal slovní popis, jen počet mezikroků ({total}).</p>
        )}
        {hiddenCount > 0 && meaningful.length > 0 && (
          <p className="meta">Skryto {hiddenCount} {hiddenCount === 1 ? 'prázdný záznam' : hiddenCount >= 2 && hiddenCount <= 4 ? 'prázdné záznamy' : 'prázdných záznamů'} bez popisu.</p>
        )}
      </details>
    </div>
  )
}
