import type { RefObject } from 'react'
import { ASSISTANT_SOURCE_LABELS } from '../../assistant/contracts'
import type { AssistantContext } from '../../assistant/contracts'
import type { AssistantMessage } from '../../assistant/useAssistant'
import { Icon } from '../../icons/Icon'

/** Conversation: user turns as right-aligned bubbles, replies as plain text with fixed source labels. */
export function Transcript({ messages, available }: { readonly messages: readonly AssistantMessage[]; readonly available: boolean }) {
  if (messages.length === 0) {
    return (
      <div className="assistant-empty">
        <span className="assistant-empty__mark"><Icon name="help" /></span>
        <p className="assistant-empty__title">{available ? 'Na co se chcete zeptat?' : 'Asistent není připojen'}</p>
        <p className="assistant-empty__text">
          {available
            ? 'Odpovídá jen na základě údajů, které sami připojíte.'
            : 'Nic se neodesílá a žádné odpovědi nevznikají. Zbytek aplikace funguje dál.'}
        </p>
      </div>
    )
  }
  return (
    <ol className="assistant-log" aria-label="Konverzace">
      {messages.map((message, index) => message.kind === 'user'
        ? <li key={index} className="assistant-turn assistant-turn--user"><span className="visually-hidden">Vy: </span><p>{message.text}</p></li>
        : <li key={index} className="assistant-turn">
          <p className="assistant-turn__text">{message.reply.text}</p>
          {message.reply.sources.length > 0 && <p className="assistant-turn__sources">{message.reply.provenance === 'server' ? 'Předaný kontext: ' : 'Zdroj: '}{message.reply.sources.map(source => ASSISTANT_SOURCE_LABELS[source]).join(', ')}</p>}
        </li>)}
    </ol>
  )
}

interface ContextAttachProps {
  readonly id: string
  readonly preview: AssistantContext | null
  readonly selected: boolean
  readonly available: boolean
  readonly reason: string | null
  readonly onSelect: (selected: boolean) => void
  readonly inspecting: boolean
  readonly onInspect: () => void
  readonly inspectRef: RefObject<HTMLButtonElement | null>
}

/** One compact row: explicit opt-in checkbox with its state, and a separate button that opens the exact preview. */
export function ContextAttach({ id, preview, selected, available, reason, onSelect, inspecting, onInspect, inspectRef }: ContextAttachProps) {
  const count = preview?.fields.length ?? 0
  return (
    <div className={selected ? 'assistant-attach is-on' : 'assistant-attach'}>
      <label className="assistant-attach__check">
        <input type="checkbox" checked={selected} disabled={!available} onChange={event => onSelect(event.target.checked)} aria-describedby={`${id}-state`} />
        <span>Připojit údaje případu</span>
      </label>
      <span className="assistant-attach__state" id={`${id}-state`}>
        {preview ? (selected ? `Připojeno: ${count}` : `Nepřipojeno · ${count} údajů`) : reason ?? 'Nelze připojit'}
      </span>
      {preview && <button type="button" ref={inspectRef} className="assistant-attach__inspect" aria-expanded={inspecting}
        aria-label={inspecting ? 'Skrýt údaje' : 'Zobrazit údaje'} onClick={onInspect}>
        <Icon name="eye" small />{inspecting ? 'Skrýt' : 'Zobrazit'}
      </button>}
    </div>
  )
}
