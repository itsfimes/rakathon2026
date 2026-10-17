import type { AssistantReply } from '../../assistant/contracts'

/** Short provenance wording shared by the header badge and each reply. */
export function provenanceText(provenance: AssistantReply['provenance'] | 'none'): string {
  if (provenance === 'scripted') return 'Skriptovaná ukázka · není AI'
  if (provenance === 'server') return 'Odpověď serveru'
  return 'Asistent není připojen'
}
