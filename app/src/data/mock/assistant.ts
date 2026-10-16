import { ASSISTANT_FIELD_LABELS } from '../../assistant/contracts'
import type { Assistant, AssistantRequest, AssistantResult } from '../../assistant/contracts'
import { ASSISTANT_PROMPTS } from '../../assistant/prompts'
import { validRequest } from '../../assistant/validation'

const SCRIPTED_SENTINEL = 'RAKATHON_SCRIPTED_ASSISTANT_V1'

export function createScriptedAssistant(): Assistant {
  return Object.freeze({
    artifactMarker: SCRIPTED_SENTINEL,
    availability: 'available', provenance: 'scripted',
    async send(request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult> {
      if (signal.aborted) return { ok: false, error: { code: 'aborted' } }
      if (!validRequest(request)) return { ok: false, error: { code: 'invalid-request' } }
      const supported = ASSISTANT_PROMPTS[request.role].includes(request.text)
      let text: string
      if (!supported) {
        text = 'Tento volný dotaz skriptovaná ukázka nepodporuje. Použijte přesně nabízený dotaz; nejde o skutečnou AI.'
      } else if (!request.context) {
        text = 'Pro tento přehled nejprve výslovně zapněte sdílení zobrazeného náhledu kontextu. Bez něj nečtu žádný případ.'
      } else {
        text = request.context.fields.map(field => `${ASSISTANT_FIELD_LABELS[field.key]}: ${field.value}`).join('\n')
      }
      const sources = supported && request.context ? [...new Set(request.context.fields.map(field => field.source))] : []
      return { ok: true, value: {
        provenance: 'scripted',
        text: `Skriptovaná ukázka, nikoli AI.\n${text}\nPouze opis dodaných údajů; bez klinického posouzení, určení priority nebo schválení termínu.`,
        sources,
      } }
    },
  })
}
