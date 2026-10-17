import { memo, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, RefObject } from 'react'
import { ASSISTANT_FIELD_LABELS, ASSISTANT_LIMITS } from '../../assistant/contracts'
import { ASSISTANT_PROMPTS } from '../../assistant/prompts'
import type { useAssistant } from '../../assistant/useAssistant'
import { isAssistantRole } from '../../assistant/validation'
import type { ModeStripState } from '../../components/shell/ModeStrip'
import { Icon } from '../../icons/Icon'
import type { ViewId } from '../../lib/roles'
import { ContextAttach, Transcript } from './AssistantParts'
import { lockBodyScroll } from './bodyLock'
import { provenanceText } from './labels'
import { revealScrollTop } from './scroll'

type Controller = ReturnType<typeof useAssistant>

interface AssistantDialogProps {
  readonly sourceLabel?: string | undefined
  readonly open: boolean
  readonly onClose: () => void
  readonly assistant: Controller
  readonly view: ViewId
  readonly mode: ModeStripState['kind']
  /** Why case context cannot be attached right now (null when it can). */
  readonly contextReason: string | null
  readonly returnFocus: RefObject<HTMLElement | null>
  /** Returns true when the close came from navigation; the new page then owns focus. */
  readonly skipFocusRestore?: () => boolean
}

const MODE_TEXT: Record<ModeStripState['kind'], { readonly tone: string; readonly label: string }> = {
  mock: { tone: 'mock', label: 'DEMO · SYNTETICKÁ DATA · bez backendu' },
  backend: { tone: 'backend', label: 'Backend · není nakonfigurován' },
  'configuration-error': { tone: 'error', label: 'Konfigurace zdroje dat je neplatná' },
  starting: { tone: 'backend', label: 'Zdroj dat · načítání konfigurace' },
}

/** Non-modal docked panel (dialog.show): the page stays interactive and reflows around it
    (right column on desktop, bottom dock on phones). Escape inside the panel closes it. */
export function AssistantDialog({ open, onClose, assistant, view, mode, sourceLabel, contextReason, returnFocus, skipFocusRestore }: AssistantDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)

  // Closing plays a short slide-out before the real close. While it runs, the sheet shows a frozen
  // copy of the last open render (the hook clears on close) and is inert. Reopening cancels it.
  const [exiting, setExiting] = useState(false)
  const [wasOpen, setWasOpen] = useState(open)
  if (wasOpen !== open) {
    setWasOpen(open)
    setExiting(!open && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  }

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open) {
      if (!dialog.open) dialog.show()
      titleRef.current?.focus()
      return
    }
    if (!dialog.open) return
    if (!exiting) { dialog.close(); return }
    let done = false
    const finish = () => {
      if (done) return
      done = true
      setExiting(false)
      if (dialog.open) dialog.close()
    }
    const onEnd = (event: AnimationEvent) => { if (event.target === dialog) finish() }
    dialog.addEventListener('animationend', onEnd)
    const timer = window.setTimeout(finish, 400)
    return () => {
      dialog.removeEventListener('animationend', onEnd)
      window.clearTimeout(timer)
    }
  }, [open, exiting])

  const skipRef = useRef(skipFocusRestore)
  useLayoutEffect(() => { skipRef.current = skipFocusRestore }, [skipFocusRestore])
  useEffect(() => {
    if (!open || !window.matchMedia) return
    const query = window.matchMedia('(max-width: 760px)')
    let active = true
    let release: ReturnType<typeof lockBodyScroll> | undefined
    const sync = () => {
      if (!active) return
      if (query.matches) {
        release ??= lockBodyScroll()
      } else {
        release?.(!skipRef.current?.())
        release = undefined
      }
    }
    sync()
    query.addEventListener?.('change', sync)
    return () => {
      active = false
      query.removeEventListener?.('change', sync)
      release?.(!skipRef.current?.())
      release = undefined
    }
  }, [open])

  // Focus goes back to the trigger (or main content) whenever the dialog is closed by any route.
  function restoreFocus() {
    if (skipFocusRestore?.()) return
    const target = returnFocus.current ?? document.getElementById('obsah')
    target?.focus({ preventScroll: true })
  }

  return (
    <dialog ref={dialogRef} className={exiting ? 'assistant is-closing' : 'assistant'} inert={exiting || undefined} aria-labelledby="assistant-title" aria-describedby="assistant-scope"
      onCancel={event => { event.preventDefault(); onClose() }}
      onKeyDown={event => { if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); onClose() } }}
      onClose={() => { if (open) onClose(); restoreFocus() }}>
      {/* Mounted only while open (and its exit): the inspection view and scroll memory reset on every opening. */}
      {(open || exiting) && <HeldSheet frozen={!open} onClose={onClose} assistant={assistant} view={view} mode={mode} sourceLabel={sourceLabel} contextReason={contextReason} titleRef={titleRef} />}
    </dialog>
  )
}

/** While frozen (exit animation) the sheet keeps its last rendered content instead of the cleared state. */
const HeldSheet = memo(function HeldSheet(props: SheetProps & { readonly frozen: boolean }) {
  return <Sheet {...props} />
}, (_prev, next) => next.frozen)

interface SheetProps {
  readonly sourceLabel?: string | undefined
  readonly onClose: () => void
  readonly assistant: Controller
  readonly view: ViewId
  readonly mode: ModeStripState['kind']
  readonly contextReason: string | null
  readonly titleRef: RefObject<HTMLHeadingElement | null>
}

function Sheet({ onClose, assistant, view, mode, sourceLabel, contextReason, titleRef }: SheetProps) {
  const ids = useId()
  const inputId = `${ids}-input`
  const role = isAssistantRole(view) ? view : null
  const prompts = role ? ASSISTANT_PROMPTS[role] : []
  const modeText = sourceLabel ? { tone: MODE_TEXT[mode].tone, label: sourceLabel } : MODE_TEXT[mode]
  const scripted = assistant.provenance === 'scripted'
  const usable = assistant.available && role !== null

  // Exact-context inspection replaces the conversation inside the same dialog (no growing footer).
  const [inspecting, setInspecting] = useState(false)
  const showInspect = inspecting && assistant.contextPreview !== null
  const inspectHeading = useRef<HTMLHeadingElement>(null)
  const inspectButton = useRef<HTMLButtonElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  function openInspect() {
    setInspecting(true)
    requestAnimationFrame(() => inspectHeading.current?.focus())
  }
  function closeInspect() {
    setInspecting(false)
    requestAnimationFrame(() => inspectButton.current?.focus())
  }

  // A new turn is revealed only when the reader was already at the bottom; a long reply shows its start.
  // Pending state and typing never scroll; keyboard focus is never moved.
  const bodyRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const count = assistant.messages.length
  useLayoutEffect(() => {
    const body = bodyRef.current
    const turn = body?.querySelector<HTMLElement>('.assistant-turn:last-child')
    if (!body || !turn || !atBottom.current) return
    // Measure to the end of the content so trailing status lines cannot push the turn's first line out of view.
    body.scrollTop = revealScrollTop({ turnTop: turn.offsetTop, turnHeight: Math.max(turn.offsetHeight, body.scrollHeight - turn.offsetTop), viewport: body.clientHeight, scrollHeight: body.scrollHeight })
  }, [count])

  // While a request runs, controls that may hold focus stay focusable (aria-disabled + guarded handlers).
  const busy = assistant.pending
  const emptyInput = !assistant.input.trim()
  const nearLimit = assistant.input.length >= ASSISTANT_LIMITS.input * 0.8
  const nothingToClear = assistant.messages.length === 0 && !assistant.input && !assistant.contextSelected && !assistant.error
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || emptyInput) return
    setInspecting(false)
    void assistant.send()
  }
  // A suggestion fills the input for review; sending always goes through the one submit button.
  function applySuggestion(prompt: string) {
    assistant.setInput(prompt)
    inputRef.current?.focus({ preventScroll: true })
  }
  const replies = assistant.messages.filter(message => message.kind === 'assistant').length
  const last = assistant.messages.at(-1)
  const status = assistant.pending ? 'Čeká se na odpověď…'
    : last?.kind === 'assistant' ? `Odpověď ${replies} je připravena v konverzaci.`
      : last?.kind === 'user' && !assistant.error ? 'Dotaz byl zastaven, odpověď nepřišla.'
        : ''

  return (
    <div className="assistant__frame">
      <header className="assistant__head">
        <div className="assistant__heading">
          <h2 className="assistant__title" id="assistant-title" ref={titleRef} tabIndex={-1}>Asistent</h2>
          <span className={`assistant__badge${assistant.available ? '' : ' is-off'}`}>{provenanceText(assistant.provenance)}</span>
        </div>
        <p className={`assistant__mode is-${modeText.tone}`} title={modeText.label}><span className="assistant__dot" aria-hidden="true" /><span className="assistant__mode-text">{modeText.label}</span></p>
        <div className="assistant__head-actions">
          <button type="button" className="btn btn--secondary assistant__close" onClick={onClose}>Zavřít</button>
        </div>
      </header>

      {!usable
        ? <div className="assistant__body">
          <p className="visually-hidden" id="assistant-scope">Asistent není připojen.</p>
          <div className="assistant-empty">
            <span className="assistant-empty__mark is-off"><Icon name="lock" /></span>
            <p className="assistant-empty__title">Asistent není připojen</p>
            <p className="assistant-empty__text">
              {role ? 'V této instalaci asistent není nakonfigurován, proto tu nejde nic odeslat ani připojit. Ostatní části aplikace fungují dál.'
                : 'Asistent je k dispozici jen v pohledech rolí.'}
            </p>
          </div>
        </div>
        : <>
          {showInspect
            ? <div className="assistant__body assistant-inspect">
              <p className="visually-hidden" id="assistant-scope">Náhled údajů, které lze připojit k dotazu.</p>
              <button type="button" className="assistant-back" onClick={closeInspect}><Icon name="arrow" small />Zpět ke konverzaci</button>
              <h3 className="assistant-inspect__title" ref={inspectHeading} tabIndex={-1}>Údaje k připojení ({assistant.contextPreview!.fields.length})</h3>
              <p className="assistant-empty__text">{assistant.contextSelected ? 'Připojeno: k dalšímu dotazu se přidají přesně tyto údaje.' : 'Zatím nepřipojeno. Prohlížením se nic nepřipojí.'}</p>
              <dl className="assistant-inspect__list">
                {assistant.contextPreview!.fields.map((field, index) => <div key={index}><dt>{ASSISTANT_FIELD_LABELS[field.key]}</dt><dd>{field.value}</dd></div>)}
              </dl>
              <p className="assistant-attach__note">Nic dalšího: bez jména, diagnózy a celé dokumentace.</p>
            </div>
            : <div className="assistant__body" ref={bodyRef} onScroll={event => { const b = event.currentTarget; atBottom.current = b.scrollTop + b.clientHeight >= b.scrollHeight - 48 }}>
              <p className="assistant__scope" id="assistant-scope">
                {scripted ? 'Jen opakuje údaje, které připojíte; neradí ve zdraví ani léčbě.' : 'Neradí ve zdraví ani léčbě a nic neprovádí.'} Zavřením se vše smaže.
              </p>
              <Transcript messages={assistant.messages} available scripted={scripted} />
              {assistant.messages.length === 0 && prompts.length > 0 && <div className="assistant__suggest" role="group" aria-label="Nabízený dotaz">
                {prompts.map(prompt => (
                  <button key={prompt} type="button" className="assistant-chip" aria-label={`Vložit do pole: „${prompt}“`} onClick={() => applySuggestion(prompt)}>
                    <span className="assistant-chip__text">{prompt}</span><span className="assistant-chip__go">Vložit</span>
                  </button>
                ))}
              </div>}
              <p className="assistant__status" role="status">{status}</p>
              {assistant.error && <p className="assistant__error" role="alert"><Icon name="alert" small />{assistant.error}</p>}
              <button type="button" className="assistant__clear" aria-disabled={nothingToClear || undefined} onClick={() => { if (!nothingToClear) assistant.clear() }}>Vymazat konverzaci</button>
            </div>}

          {/* One composer unit: opt-in context strip, the question, and the send row. */}
          <form className="assistant__composer" onSubmit={submit}>
            <ContextAttach id={`${ids}-ctx`} preview={assistant.contextPreview} selected={assistant.contextSelected}
              available={assistant.contextAvailable} reason={contextReason} onSelect={assistant.selectContext}
              inspecting={showInspect} onInspect={showInspect ? closeInspect : openInspect} inspectRef={inspectButton} />
            <label className="visually-hidden" htmlFor={inputId}>Váš dotaz</label>
            <textarea id={inputId} ref={inputRef} className="assistant__input" rows={2} maxLength={ASSISTANT_LIMITS.input}
              placeholder="Napište dotaz…" value={assistant.input} onChange={event => assistant.setInput(event.target.value)} aria-describedby={`${ids}-count`} />
            <button type="submit" className="btn assistant__send" aria-disabled={busy || emptyInput || undefined}>Odeslat dotaz</button>
            <div className="assistant__composer-bar">
              <span className={`assistant__count${nearLimit ? '' : ' visually-hidden'}`} id={`${ids}-count`}>{assistant.input.length}/{ASSISTANT_LIMITS.input}</span>
              {busy && <button type="button" className="assistant__stop" onClick={() => { assistant.stop(); inputRef.current?.focus({ preventScroll: true }) }}>Zastavit</button>}
            </div>
          </form>
        </>}
    </div>
  )
}
