import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ASSISTANT_FIELD_LABELS, ASSISTANT_LIMITS } from '../../assistant/contracts'
import { ASSISTANT_PROMPTS } from '../../assistant/prompts'
import type { useAssistant } from '../../assistant/useAssistant'
import { isAssistantRole } from '../../assistant/validation'
import { Icon } from '../../icons/Icon'
import type { ViewId } from '../../lib/roles'
import { ContextAttach, Transcript } from './AssistantParts'
import { revealScrollTop } from './scroll'

function Chevron({ down }: { readonly down: boolean }) {
  return (
    <svg className="icon icon--sm" aria-hidden="true" focusable="false" style={{ transform: down ? undefined : 'rotate(180deg)' }}>
      <use href="#i-arrow" />
    </svg>
  )
}

type Controller = ReturnType<typeof useAssistant>

interface AssistantPanelProps {
  readonly expanded: boolean
  readonly onToggle: () => void
  readonly assistant: Controller
  readonly view: ViewId
  /** Why case context cannot be attached right now (null when it can). */
  readonly contextReason: string | null
}

/** Inline assistant panel rendered as part of the page flow, not an overlay. */
export function AssistantPanel({ assistant, view, expanded, onToggle, contextReason }: AssistantPanelProps) {
  const ids = useId()
  const inputId = `${ids}-input`
  const role = isAssistantRole(view) ? view : null
  const prompts = role ? ASSISTANT_PROMPTS[role] : []
  const usable = assistant.available && role !== null

  const [inspecting, setInspecting] = useState(false)
  const showInspect = inspecting && assistant.contextPreview !== null
  const inspectHeading = useRef<HTMLHeadingElement>(null)
  const inspectButton = useRef<HTMLButtonElement>(null)
  function openInspect() {
    setInspecting(true)
    requestAnimationFrame(() => inspectHeading.current?.focus())
  }
  function closeInspect() {
    setInspecting(false)
    requestAnimationFrame(() => inspectButton.current?.focus())
  }

  const bodyRef = useRef<HTMLDivElement>(null)
  const atBottom = useRef(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const count = assistant.messages.length
  useLayoutEffect(() => {
    const body = bodyRef.current
    const turn = body?.querySelector<HTMLElement>('.assistant-turn:last-child')
    if (!body || !turn || !atBottom.current) return
    body.scrollTop = revealScrollTop({ turnTop: turn.offsetTop, turnHeight: Math.max(turn.offsetHeight, body.scrollHeight - turn.offsetTop), viewport: body.clientHeight, scrollHeight: body.scrollHeight })
  }, [count])

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
    <section className="assistant" aria-labelledby="assistant-title">
      <div className="assistant__frame">
        <div className="assistant__head">
          <button type="button" className="assistant__toggle" onClick={onToggle} aria-expanded={expanded} aria-controls="assistant-body" aria-label="Asistent">
            <span className="assistant__heading">
              <h2 className="assistant__title" id="assistant-title">Asistent</h2>
            </span>
            <Chevron down={!expanded} />
          </button>
        </div>

        {expanded && (
          !usable
            ? <div id="assistant-body" className="assistant__body">
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
            : <div id="assistant-body">
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
                    Neradí ve zdraví ani léčbě a nic neprovádí. Zavřením se vše smaže.
                  </p>
                  <Transcript messages={assistant.messages} available />
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
            </div>
        )}
      </div>
    </section>
  )
}
