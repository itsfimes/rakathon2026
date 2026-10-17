import type { AssistantCoverage } from '../../assistant/contracts'
import type { AssistantMessage } from '../../assistant/useAssistant'
import { Icon } from '../../icons/Icon'
import { provenanceText } from './labels'

function Coverage({ coverage }: { readonly coverage: AssistantCoverage }) {
  return <p className="assistant-turn__sources">
    {coverage.status === 'general' ? 'Obecný dotaz bez záznamu pacienta.' : <>
      Pokrytí: {coverage.status === 'complete' ? 'úplné' : 'částečné'} · FHIR záznamy: {coverage.resources} · Nahrané soubory: {coverage.uploads}.
      {coverage.failedTypes.length > 0 && ` Nedostupné typy: ${coverage.failedTypes.join(', ')}.`}
      {!!coverage.unreadableAttachments && ` Nečitelné přílohy: ${coverage.unreadableAttachments}.`}
      {!!coverage.uploadsWithUnavailableArtifacts && ` Soubory s nedostupnými výstupy: ${coverage.uploadsWithUnavailableArtifacts}.`}
    </>}
  </p>
}

/** Server source labels are rendered as plain text, never links or HTML. */
export function Transcript({ messages, available, scripted }: { readonly messages: readonly AssistantMessage[]; readonly available: boolean; readonly scripted: boolean }) {
  if (messages.length === 0) return <div className="assistant-empty">
    <span className="assistant-empty__mark"><Icon name="help" /></span>
    <p className="assistant-empty__title">{available ? 'Na co se chcete zeptat?' : 'Asistent není připojen'}</p>
    <p className="assistant-empty__text">{available
      ? scripted ? 'Tahle skriptovaná ukázka není AI a nečte úplný zdravotní záznam.' : 'U vybraného pacienta odpovídá na základě úplného záznamu, který sestaví server. Bez výběru pacienta jde o obecný dotaz.'
      : 'Nic se neodesílá a žádné odpovědi nevznikají. Zbytek aplikace funguje dál.'}</p>
  </div>
  return <ol className="assistant-log" aria-label="Konverzace">
    {messages.map((message, index) => message.kind === 'user'
      ? <li key={index} className="assistant-turn assistant-turn--user"><span className="visually-hidden">Vy: </span><p>{message.text}</p></li>
      : <li key={index} className="assistant-turn">
        <p className="assistant-turn__by"><Icon name="help" small />{provenanceText(message.reply.provenance)}</p>
        <p className="assistant-turn__text">{message.reply.text}</p>
        <Coverage coverage={message.reply.coverage} />
        {message.reply.sources.length > 0 && <p className="assistant-turn__sources">Serverem předané zdroje: {message.reply.sources.join(', ')}</p>}
      </li>)}
  </ol>
}

export function RecordDisclosure({ caseId, scripted }: { readonly caseId: string | null; readonly scripted: boolean }) {
  return <p className="assistant-attach__note">{scripted
    ? 'Skriptovaná ukázka: žádná data se do Azure AI neposílají.'
    : caseId !== null
      ? `Vybraný pacient: ${caseId}. Odesláním dotazu se do Azure AI automaticky předá celý dostupný záznam tohoto pacienta: FHIR, dokumenty a přepisy nahraných souborů, včetně osobních a zdravotních údajů.`
      : 'Není vybrán pacient. Do Azure AI se odešle pouze váš obecný dotaz, bez záznamu pacienta.'}</p>
}
