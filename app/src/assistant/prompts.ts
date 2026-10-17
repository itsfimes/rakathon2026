import type { AssistantRole } from './contracts'

/** Exact, supported demonstration intents; no keyword matching or clinical fallback. */
export const ASSISTANT_PROMPTS: Readonly<Record<AssistantRole, readonly string[]>> = Object.freeze({
  koordinator: Object.freeze(['Shrň dostupné záznamy vybraného pacienta a upozorni na chybějící údaje.']),
  pacient: Object.freeze(['Vysvětli srozumitelně, jaké údaje o mně máš k dispozici.']),
  lekar: Object.freeze(['Shrň stručně, jaká data o pacientovi máš k dispozici (typy záznamů, počty).']),
  mdt: Object.freeze(['Shrň dostupné podklady vybraného pacienta pro MDT a jejich omezení.']),
})
