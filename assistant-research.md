# On-demand assistant: evidence and phase-one handoff

## Benefit hypothesis, not an outcome claim

The first candidate benefit is coordinator operational orientation: re-present supplied
next-step ownership and missing-document states. Patient benefit is orientation to the
patient's supplied instruction, event and contact; referrer benefit is referral-loop
state/obligations; MDT benefit is document-metadata retrieval only. These are pilot
hypotheses, not evidence that a chatbot improves outcomes, safety or anxiety.

The approved nonintrusive interaction is an explicit header trigger, never a proactive
bubble, notification or auto-open. The next designer phase will implement a native modal
dialog at every viewport, with constrained desktop side-sheet and mobile full-screen
presentation. Native modality avoids two divergent focus models. Escape, focus return,
background inertness, keyboard/mobile/zoom and visible mode/provenance require validation.
No UI is implemented in phase one.

## Evidence used (research completed 2026-10-16)

- [WHO, 2024 LMM governance guidance release](https://www.who.int/news/item/18-01-2024-who-releases-ai-ethics-and-governance-guidance-for-large-multi-modal-models):
  false/incomplete outputs and automation bias are material risks; not proof of benefit.
- [NICE NG12, patient support/safety-netting/diagnostic process](https://www.nice.org.uk/guidance/ng12/chapter/Recommendations-on-patient-support-safety-netting-and-the-diagnostic-process):
  status, contact, waiting information and responsibility support the orientation scope;
  this is neither endorsement of AI nor a Czech deadline policy.
- [NICE NG197, shared decision making](https://www.nice.org.uk/guidance/ng197/chapter/Recommendations):
  tailored information and explicit uncertainty, not automated clinical judgment.
- [WAI-ARIA APG modal dialog pattern](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/):
  focus within modal, Escape, focus return and inert background. Header-over-bubble is
  a design inference, not an experimentally established outcome.
- [OWASP prompt injection prevention](https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html)
  and [logging guidance](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html):
  treat supplied documents/model output as untrusted; plain-text rendering, no tool actions,
  and no prompt/health-text logging by default. Prompt wording is not authorization.
- [GDPR Article 5, secondary reproduction](https://gdpr-info.eu/art-5-gdpr/):
  minimization, purpose and retention principles. Local legal applicability and lawful
  basis must be assessed separately; context opt-in is not a legal consent mechanism.

## What exists and what does not

Phase one supplies a required `Session.assistant` capability separate from `Gateway`,
bounded DTOs, exact field-preview projection, an in-memory headless hook, unavailable
no-network backend and isolated explicitly scripted mock. It is **not real AI**. The mock
recognizes exact suggested prompts only, copies only supplied context, requests opt-in
when context is absent, and explicitly rejects unsupported free text. No glossary,
clinical inference, priority decision, timing approval, record mutation or clinical action.
Backend artifacts must contain neither mock provider modules nor scripted sentinels/answers.
The mock sentinel remains an internal capability marker, not human-facing reply text.

The field projection excludes identity, age, diagnosis, case IDs, revision, excerpts,
clinical finding/draft, source-field values, record history and person owners. It includes
only the role-specific operational/patient/referral/document metadata fields listed in
`app/src/assistant/context.ts`. Coordinator and MDT document entries use fixed app-owned
type/state labels mapped only from enums; free-text document labels/state labels and all
source metadata (titles/dates/pages) are excluded at projection, not regex-redacted.
Organization and contact labels are included only where needed; person-name fields are
never deliberately selected. This structural allowlist is not a PHI detector: other supplied
free text, including task titles, patient instructions, organization strings and contact
details, still needs upstream minimization. The user's own question may contain sensitive
text; no actual external endpoint is configured.

## Server and governance boundary

Before enabling any real provider, specify authenticated same-origin server transport,
server-enforced role/case authorization, request/response size/schema validation, rate
limits, cancellation/timeouts, safe typed errors, provider/region/retention arrangements,
audit metadata without prompt/health content, incident/kill-switch procedure, clinical
evaluation and legal/governance approval. Browser role selection and context checkbox
are not authorization. Keep vendor SDKs/keys server-side; no `VITE_*` credentials. No URL,
REST route, model or vendor is invented in this implementation.

The frontend contract sends only `{role, text, context?}`; it never sends history or local
case/revision/session keys. A future backend must independently authorize any access and
must not silently enrich requests with hidden records/history. Record source IDs are
app-owned field-provenance labels, not evidence approval, arbitrary URLs or model-selected
navigation. Any future public glossary needs distinct public-source metadata, not record
attribution. Generated content must render as text, never HTML/Markdown. See `app/README.md`
for exact headless wiring and freshness requirements.
