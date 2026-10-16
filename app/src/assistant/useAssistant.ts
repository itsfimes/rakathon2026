import { useLayoutEffect, useRef, useState } from 'react'
import type { Session } from '../data/contracts'
import type { ViewId } from '../lib/roles'
import { ASSISTANT_LIMITS } from './contracts'
import type { AssistantContext, AssistantReply, AssistantRequest } from './contracts'
import { isAssistantRole, validContext, validReply, validRequest } from './validation'

export interface AssistantOptions {
  readonly session: Session | null
  readonly view: ViewId
  /** Local invalidation keys ONLY; these are never request fields. */
  readonly caseId: string | null
  readonly version: number
  readonly resetKey?: number
  readonly scopeKey?: string
  readonly open: boolean
  readonly contextFresh: boolean
  readonly context: AssistantContext | null
}
export type AssistantMessage = { readonly kind: 'user'; readonly text: string } | { readonly kind: 'assistant'; readonly reply: AssistantReply }
interface State {
  readonly scope: AssistantOptions
  readonly input: string
  readonly messages: readonly AssistantMessage[]
  readonly contextSelected: boolean
  readonly pending: boolean
  readonly error: string | null
}

const empty = (scope: AssistantOptions): State => ({ scope, input: '', messages: [], contextSelected: false, pending: false, error: null })
const sameScope = (a: AssistantOptions, b: AssistantOptions) => a.session === b.session && a.view === b.view
  && a.caseId === b.caseId && a.version === b.version && a.resetKey === b.resetKey && a.scopeKey === b.scopeKey && a.open === b.open && a.contextFresh === b.contextFresh

export const ASSISTANT_FAILURE_MESSAGE = 'Odpověď není k dispozici. Zkuste požadavek znovu.'
export const ASSISTANT_UNAVAILABLE_MESSAGE = 'Asistent není připojen. Žádný požadavek nebyl odeslán.'

/** In-memory, explicit-send controller. Context preview is the exact field projection sent. */
export function useAssistant(options: AssistantOptions) {
  const [stored, setState] = useState<State>(() => empty(options))
  let state = stored
  // Derive resets during render so stale input/context/transcript never flash for another scope.
  if (!sameScope(stored.scope, options)) {
    state = empty(options)
    setState(state)
  }
  const active = useRef<AbortController | null>(null)
  const { session, view, caseId, version, resetKey, scopeKey, open, contextFresh, context } = options
  useLayoutEffect(() => () => {
    active.current?.abort()
    active.current = null
  }, [session, view, caseId, version, resetKey, scopeKey, open, contextFresh])

  const contextAvailable = open && caseId !== null && contextFresh && !!context && context.role === view && validContext(context)
  const contextPreview = contextAvailable ? context : null
  const selectedContext = state.contextSelected ? contextPreview : null
  const assistant = session?.assistant
  const available = assistant?.availability === 'available' && isAssistantRole(view)

  function abort() {
    active.current?.abort()
    active.current = null
  }
  function clear() {
    abort()
    setState(empty(options))
  }
  function stop() {
    abort()
    setState(previous => ({ ...previous, pending: false }))
  }
  function setInput(input: string) {
    if (!open) return
    setState(previous => input.length > ASSISTANT_LIMITS.input
      ? { ...previous, error: `Dotaz může mít nejvýše ${ASSISTANT_LIMITS.input} znaků.` }
      : { ...previous, input, error: null })
  }
  function selectContext(selected: boolean) {
    setState(previous => ({ ...previous, contextSelected: selected && contextAvailable }))
  }
  async function send(text = state.input): Promise<void> {
    if (!open || active.current || !isAssistantRole(view)) return
    if (!assistant || assistant.availability !== 'available') {
      setState(previous => ({ ...previous, error: ASSISTANT_UNAVAILABLE_MESSAGE }))
      return
    }
    if (state.messages.length + 2 > ASSISTANT_LIMITS.history) {
      setState(previous => ({ ...previous, error: 'Limit konverzace byl dosažen. Vymažte ji před dalším dotazem.' }))
      return
    }
    const request: AssistantRequest = {
      role: view, text: text.trim(),
      ...(selectedContext ? { context: Object.freeze({ role: selectedContext.role, fields: Object.freeze(selectedContext.fields.map(field => Object.freeze({ ...field }))) }) } : {}),
    }
    if (text.length > ASSISTANT_LIMITS.input || !validRequest(request)) {
      setState(previous => ({ ...previous, error: `Zadejte dotaz o 1 až ${ASSISTANT_LIMITS.input} znacích.` }))
      return
    }
    const controller = new AbortController()
    active.current = controller
    setState(previous => ({ ...previous, input: '', pending: true, error: null, messages: [...previous.messages, { kind: 'user', text: request.text }] }))
    const current = () => active.current === controller && !controller.signal.aborted
    try {
      const result = await assistant.send(request, controller.signal)
      if (!current()) return
      if (result.ok && validReply(result.value, request, assistant.provenance)) {
        const reply: AssistantReply = Object.freeze({ provenance: result.value.provenance, text: result.value.text, sources: Object.freeze([...result.value.sources]) })
        setState(previous => ({ ...previous, pending: false, messages: [...previous.messages, { kind: 'assistant', reply }] }))
      } else {
        setState(previous => ({ ...previous, pending: false, error: ASSISTANT_FAILURE_MESSAGE }))
      }
    } catch {
      if (current()) setState(previous => ({ ...previous, pending: false, error: ASSISTANT_FAILURE_MESSAGE }))
    } finally {
      if (active.current === controller) active.current = null
    }
  }
  return {
    input: state.input, messages: state.messages, pending: state.pending, error: state.error,
    contextAvailable, contextPreview, selectedContext, contextSelected: !!selectedContext,
    available, provenance: assistant?.provenance ?? 'none',
    setInput, selectContext, send, stop, clear, close: clear,
  }
}
