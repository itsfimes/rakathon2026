# Frontend opportunities from the role research

Status: investigated, **not implemented**. Basis: `role-research.md` compared with the current React features, shared components and frontend data contracts. Preserve the approved design, typography, component architecture and explicit mock-mode safeguards.

## Conclusion

Yes: the most useful next changes concern **information order, task clarity and honest workflow states**, not another visual redesign. Start with improvements supported by existing data. Treat richer role workflows as separate frontend-contract work, not as fields that can be invented in components.

## Recommended first implementation batch

### 1. Make the referring-doctor screen referral-first

**Benefit:** a referrer can immediately see progress, responsibility and whether a response is needed, rather than entering an extraction-review tool.

- Identify the current view as `Lékař · odesílající`, not a generic workspace for every clinical specialty.
- Lead with the existing referral timeline, next coordination step and supplied `obligations` text.
- Put source review after this summary; keep the evidence accessible rather than removing it.
- Distinguish **referral accepted by KOC** from **a particular task accepted by its owner**.
- Show useful task receipt information without assuming the selected viewer is the responsible clinician. Named owner visibility remains a local access-policy question.
- Remove directional wording such as “kontrola výpisu vlevo” if panel order changes.

**Data:** existing `identity.referredAt/acceptedAt`, `doctor.referralStatus`, `doctor.obligations` and `nextStep`.

**Scope:** small to medium; information hierarchy, labels and component composition. No new data contract required.

**Implementation anchors:** `app/src/features/doctor/DoctorView.tsx`, `SourceReviewPanel.tsx`, `features/shared/TaskFacts.tsx`.

### 2. Give the coordinator practical existing-field filters and truthful ordering

**Benefit:** staff can narrow the work queue to unresolved responsibility or requests for additional information without opening every case.

- Candidate filters: all cases, awaiting acceptance, awaiting additional information, and a clearly labelled deadline view where supported.
- Derive filter counts from returned queue items. Do not invent clinical severity or a new risk score.
- Surface the supplied `priorityExplanation` near the selected next step instead of making it accessible only through a closed disclosure.
- Show available referral/request dates with precise labels. `referredAt` is not proof of a written request for indicated care; `requestedAt` is not a last-reminder timestamp or proof of delivery.
- Correct the queue caption to describe the ordering actually supplied. The mock provider currently preserves fixture order; it does **not** implement the caption's claimed deadline/acceptance ranking algorithm. Agree a sorting policy separately instead of silently introducing one.

**Data:** existing queue `priority`, `phase`, task dates/acknowledgement, and selected-case `priorityExplanation`.

**Scope:** small to medium. Filters can be frontend-only; ordering must not be represented as a clinical rule.

**Implementation anchors:** `features/coordinator/CoordinatorView.tsx`, `QueueTable.tsx`, `CaseDetailPanel.tsx`, `data/mock/provider.ts`.

### 3. Separate MDT document gaps from the application's finalization restriction

**Benefit:** the interface does not imply that its illustrative checklist is a universal clinical veto.

- Keep available, missing and uncertain documents distinct in the preparation panel.
- Place the application's finalization restriction beside the disabled finalization control, not as the clinical consequence of the document count.
- Use an application-capability explanation, such as “Finalizace není v této verzi aplikace dostupná.” Keep case-specific missing evidence visible separately.
- Do not claim the case is clinically permitted to proceed merely because the wording is clearer.
- Do not encode chair-only approval, quorum, a universal histology requirement or a bypass action without a local clinical owner.

**Data:** existing documents, required-document IDs, uncertainties and blocked finalization state. The fixture's current chair/exception explanation also needs to be separated from the application's restriction.

**Scope:** small; presentation and truthful explanatory copy. **Finalization remains disabled.**

**Implementation anchors:** `features/mdt/CompletenessPanel.tsx`, `DraftPanel.tsx`, `data/contracts.ts`, `data/mock/fixtures.ts`.

### 4. Make patient attendance states easier to distinguish

**Benefit:** the patient can more quickly distinguish attendance required, attendance not required, and attendance not yet confirmed.

- Use the existing attendance enum and supplied label to select an appropriate labelled icon/treatment.
- Keep the current calendar, journey and readable typography.
- Do not confuse **attendance uncertain** with **appointment date uncertain**: the current enum describes attendance, not date confirmation.
- Keep the honest missing-contact fallback. Do not add a phone number, opening hours or a promised callback.
- Optional general explanations can use the existing disclosure component; new case-specific explanations must come from approved content/data.

**Data:** existing `patient.nextEvent.attendance`, `attendanceLabel`, `followup` and coordinator contact/help.

**Scope:** small. This is a clarity improvement, not a new appointment-confirmation workflow.

**Implementation anchors:** `features/patient/EventPanel.tsx`, `PatientView.tsx`, `HelperPanel.tsx`.

## Next tier: worthwhile frontend-contract and mock-provider extensions

These can be prototyped in the frontend compatibility layer before a backend exists, but must not be mislabelled as existing real information.

| Opportunity | Missing capability/data | Boundary |
|---|---|---|
| **Queue-level blockers** | Queue summary fields for missing/uncertain documents or explicitly supplied blockers | Return/derive summaries in the provider. Do not fetch every full case merely to add queue badges (N+1 reads). Document counts are not clinical eligibility rules. |
| **Patient waiting/unknown-date states** | Nullable event date and explicit date status, update owner, optional expected update, approved status explanation | Do not reuse a task deadline as an appointment or result date. Unknown timing must remain unknown. |
| **Patient known/uncertain information** | Clinically reviewed, patient-facing explanation and its provenance | Do not infer diagnosis, prognosis or a promised next action from administrative state. The existing `currentInstruction` is already gateway data, not a hardcoded fallback defect. |
| **MDT clinical question and preferences** | Explicit clinical question; patient preferences/context with source and date | Content comes from the care team/patient workflow. Do not fabricate preferences or assume absent information means “no preferences”. |
| **MDT outcomes and follow-up** | Explicit preparation/discussion/outcome states, deferred/additional-workup outcomes, follow-up owners and communication status | Define with the pilot team. Do not turn a proposed enum into a clinical authorization or national workflow rule. |
| **Real review provenance** | Reviewer identity, timestamp, scope, meaning and audit/action contract | Current review is document-wide and local to the demo. A `reviewed` boolean is not a clinical attestation or evidence that the current doctor approved something. |

The strongest second-batch candidates are **queue summaries**, **honest patient waiting states**, and **MDT question/preferences**. A full meeting-management workflow or new treating-oncologist workspace should be separately scoped.

## Do not change as part of this work

- The persistent source-mode banner or the single fail-closed `VITE_DATA_MODE` selection.
- Backend-unconfigured error states into empty successful lists or synthetic fallbacks.
- Disabled real sending, booking, signing and finalization into simulated successes.
- Patient access into a frontend role filter: real identity and authorization remain backend responsibilities.
- Referring doctors' clinical authority based solely on a UI label.
- Clinical priority, universal deadlines, numeric quorum or definitive checklist rules based on the demo fixtures.
- The design language or typography merely to accommodate new fields; reuse existing panels, facts, tags, tables, timelines and disclosures.

## Suggested acceptance checks for the first batch

1. Referrer status/required response appears before the source table on desktop and mobile.
2. Queue filters and counts use actual returned fields; empty filtered results differ from data errors.
3. Ordering descriptions match the supplied order; no implicit clinical ranking is added.
4. Referral receipt and task acknowledgement are labelled as different events.
5. Patient attendance labels do not invent patient actions or date certainty.
6. MDT document gaps remain visible, while finalization remains disabled for an explicit application reason.
7. Default backend mode still displays no synthetic patient data; explicit mock mode stays prominently marked through all states.
8. Existing typecheck, lint, provider/artifact tests, role interactions and responsive/keyboard checks remain valid after implementation.

## Confidence and limitations

The high-confidence recommendation is to improve **role fit using existing information**. The research supports making responsibility, progress, uncertainty and relevant information available; it does not prove this exact panel order or set of filters. Validate the first batch with a referring clinician, coordinator and patient representative before treating it as a settled workflow. No frontend code or runtime behavior was changed by this investigation.
