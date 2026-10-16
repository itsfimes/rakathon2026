import type { AssistantRole } from './contracts'

/** Exact, supported demonstration intents; no keyword matching or clinical fallback. */
export const ASSISTANT_PROMPTS: Readonly<Record<AssistantRole, readonly string[]>> = Object.freeze({
  koordinator: Object.freeze(['Ukaž dodaný další krok a stavy podkladů.']),
  pacient: Object.freeze(['Ukaž můj dodaný pokyn, událost a kontakt.']),
  lekar: Object.freeze(['Ukaž dodané stavy odeslání a povinnosti.']),
  mdt: Object.freeze(['Ukaž dodaná metadata podkladů.']),
})
