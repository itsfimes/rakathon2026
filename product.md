# Product

<!-- impeccable:product-schema 1 -->

> Canonical product record (lowercase `product.md`). `PRODUCT.md` is only a symlink to this file for tooling; never keep a second copy. This file holds product truth only — no palette, type, components or layout. Visual decisions live in `design.md` once the visual sample is built and approved.

## Platform

web

## Stack

- **Now (design-language study):** plain static HTML + CSS + minimal classic JavaScript (no ES modules, no `fetch`), opened directly from disk. No network, web fonts, CDN, persistence, build step, packages or backend. Confirmed by the user.
- **Design base (accepted by the user):** the revised design study is the BASE for the real frontend. `sample/` stays as an immutable offline reference (static HTML/CSS, works without JS).
- **Application (implemented, frontend only):** `app/` — React + TypeScript + Vite with CSS custom properties, no UI framework. No backend exists; all data goes through a frontend-owned gateway (`app/src/data/`) that a real backend adapter will replace. One build-time switch `VITE_DATA_MODE`: unset/`backend` (default) = backend not configured, no patient data shown; exact `mock` = clearly bannered synthetic demo; anything else = configuration error. No automatic fallback, and backend builds are checked to contain no fixtures. The app needs JavaScript (`<noscript>` says so); it does not repeat the sample's no-JS stacked views. No auth, sending, signing, AI or finalisation.
- **Earlier note:** the design language must not assume a framework. Target architecture (context.md §6, architecture.md §1) is FHIR R4 data in InterSystems IRIS behind modular blocks B1–B7; the dashboard is block B3.

## Users

Four role views of one shared case (context.md §6, §7.1; architecture.md §4):

| Role (Czech label) | Situation | Job in the product |
|---|---|---|
| **Koordinátor** (K1, primary user) | Frequent, all-day desktop work inside a KOC; today runs on phone, paper, e-mail and a local NIS (context.md §7.2). Need not be a clinician and **does not decide treatment** (§2.8). | See a priority-ordered list of cases; for each case the phase, the **next step, who owns it, by when, and whether it was confirmed (ACK)**; chase missing documents; prepare MDT; inform the referring doctor in one action. |
| **Pacient** (and family) | Occasional use, mostly on a phone, under stress; sees only their own case. | Know in plain Czech **what happens next, when, where, and who to contact**. No clinical jargon, no internal deadlines framed as disease urgency. |
| **Lékař** (referring GP / specialist; ošetřující lékař where relevant) | Busy, intermittent; works in their own AIS/NIS. | Refer without an extra form; see whether the case was accepted, what is missing, and the MDT conclusion **with the original case context**; review AI-prepared extraction with citations before anything is used. |
| **MDT** (members and chair) | Meeting preparation and the meeting itself; time-boxed per patient. | See documentation completeness, what is uncertain or missing, the draft structured conclusion, and the human-review boundary. Only the chair governs quorum/finalisation; a doctor view is **not** MDT-chair authority. |

Other roles in the source (diagnostician, ROC, nurse, dispatch, VZP reviewer, IT) are out of scope for the design study.

## Product Purpose

G3 challenge (VZP), context.md §1.1, §2: a shared case for an oncology patient that connects doctor, coordinator and KOC, extracts data from documentation, watches documents, deadlines and responsibilities, and hands the result to MDT — faster path to treatment, less administration. Measured as time-to-treatment **T1 + T2 + T3** (§2.3), with SLA per diagnosis, never a universal 4-week rule.

Hackathon definition of done (§2.6, architecture.md §0): one diagnosis (HPB, synthetic "Pan Novák", ILLUSTRATIVE), one case end-to-end across six demo points: referral without a form, AI extraction with completeness check, case overview with status and deadline, owner of every next step, structured KOC/MDT conclusion, feedback and confirmed handover. "Rakathon ověří princip. Produkční integrace patří do další fáze."

**This design study's purpose:** define a professional, simple, memorable, low-motion dashboard language for the four role views, demonstrated by a small offline sample. It does **not** implement the six demo flows.

Success for the study: a person in each role can tell within seconds what the view is for and what the next step is; the language is reusable when the real frontend is chosen.

## Positioning

One shared case, many role views: the same data filtered per role (unless GDPR requires otherwise), where **every next step has a visible owner, deadline and acknowledgement** — "sent ≠ handed over" (architecture.md §3). The loop closes back to the referring doctor with the original context. AI only prepares; a human decides, with a citation behind every extracted claim.

## Operating Context

- Czech hospital oncology: KOC/ROC, MDT (indikační komise), referring GP, VZP as payer (context.md §5.2).
- Coordinator works mainly by phone today; there is no unified platform or capacity overview (§7.2) — the absence of a tool is the finding.
- MDT time per patient is short; team research (context.md Appendix D3, not verified here) names missing pathology/imaging and vague conclusions as dealbreakers.
- Alert fatigue is a known risk (figures in context.md §6.4 are research notes, not product facts); design intent: interrupt only for severe, actionable items, everything else passive.
- Patient phases K1 (before treatment, in scope) → K2 → K3.

## Capabilities and Constraints

**Confirmed for the study sample (illustrative only):** four role vignettes (Koordinátor / Pacient / Lékař / MDT) and selected state specimens; label the whole sample as a synthetic "Ukázka pohledu". No auth, no sending, approval, upload, ACK persistence, AI processing or network — and no copy claiming them.

**Terminology to keep:** KOC, ROC, MDT, PL (praktický lékař), T1/T2/T3, ACK / potvrzení převzetí, vlastník kroku, eŽádanka (national state machine; we adapt, never rebuild). Official eŽádanka states only: Nová / Přijatá / Neproveditelná / Stornovaná / Dokončená / Expirovaná (§8). Product case states from the brief: nový / v řešení / čeká na doplnění (§2.2).

**Hard constraints:**
- Process delay is never presented as disease severity or clinical risk; no clinical risk score from administrative data.
- SLA thresholds 48 h / 7 d are demo thresholds, labelled ILLUSTRATIVE, not norms (§8, architecture.md §6).
- AI: proposes only, citations + confidence per field, human signature/override, never auto-send or auto-finalise (architecture.md §7).
- Security is TARGET vs TODAY=MOCK; a demo role switch is not authorization and not privacy isolation (architecture.md §8).
- Patient-facing synthetic copy must not invent preparation instructions or real contact details. KOC e-mail `koordinace-hpb@vfn.cz` is unverified — never hardcode.

**Modularity principles (for the future frontend):**
- Shared tokens and a small set of primitives; each role view is a composition, not a fork.
- Views read from a framework-agnostic view-model; any adapter maps from FHIR-backed services and never adds a second proprietary ingestion path (single translation point stays in B1).
- No plugin kernel, runtime registry or backend scaffold in this study.
- A role view can be replaced or added without restyling the others.
- **Future access (not implemented):** what a user sees and which actions appear must come from server-enforced permissions/capabilities per role and purpose (TARGET SMART/RBAC, architecture.md §8). A role string in the URL or UI is never authority; the sample implements no permissions.

## Brand Commitments

- Team: "Správci Silnic" (README). No logo or brand assets exist.
- Earlier dark purple-blue hackathon mocks (context.md §11.1) are external and **not** a brand authority.
- Voice: plain, literal Czech; short sentences; jargon expanded for patients; professional and calm with humane warmth (especially for patients); never alarmist, never hype.
- User asked for: professional, simple, memorable, little or no motion.
- **Standing preference: familiar, conventional product UI** (user chose the category standard over themed directions). Craft benchmarks, delegated by the user and selected for principles only — not branding, not pixel copies: Gmail (list scanability), Linear (control consistency), GOV.UK (plain-language next steps). Cultural or metaphor motifs are out.
- **User steer after first sample (binding):** the first sample was too simplistic and text-heavy, especially for patients. Wanted: a middle ground — modest corners (not pill-heavy), clearly visible borders, easy compact role switching, and more graphical explanation (labelled icons, step/journey graphics) that needs no prior experience. Still the conventional blue dashboard; no decorative graphics, scores or motion spectacle.

## Evidence on Hand

- `context.md` (master context, incl. appendices A–E), `architecture.md`, `README.md`.
- Illustrative case "Pan Novák" (§2.7): 5. 1. 2026 icterus → 6. 1. UZ → 7. 1. hospitalisation → 9. 1. stent + histology → 12. 1. CT, TM → 13. 1. MDT 1 → 20. 1. MDT 2 → 26. 1. surgery; T1 2 d + T2 13 d + T3 6 d = 21 d. Ideal, not median.
- No real patient data, no screenshots, no testimonials, no benchmarks to quote. Slide-only numbers (§2.1, §2.8) must not be shown as facts.

## Product Principles

1. **Next step first.** Every view leads with what happens next, who owns it and by when.
2. **Sent is not handed over.** Acknowledgement is a visible state, never implied.
3. **Same case, role-appropriate depth.** Coordinator gets density, patient gets plain next steps, doctor and MDT get source context and review boundaries.
4. **Humans decide.** AI-prepared content is visibly a draft with its sources.
5. **Honest scope.** Synthetic, illustrative and mock states are labelled as such.

## Accessibility & Inclusion

- Target WCAG 2.2 AA (a target, not a certified outcome): text 4.5:1, large text 3:1, UI boundaries and focus 3:1; status never by colour alone; keyboard operable with visible, unobscured focus; 320 CSS px reflow; 200 % text resize; text-spacing tolerance.
- Stronger design targets: 44 px touch targets and ~7:1 body text in the patient view.
- No non-essential motion; honour `prefers-reduced-motion`.
- Czech plain-language writing (W3C WAI writing tips, COGA guidance). Essential specimen content readable without JavaScript.

## Open Questions

1. Future frontend stack and hosting (undecided).
2. SLA thresholds per diagnosis/phase; who may ACK KOC↔ROC handover (context.md §13 Q6, Q8).
3. MDT completeness set and quorum — universal or per diagnosis; who may override (Q7).
4. Real role/permission matrix and what the patient may see (Q15).
5. Real KOC contact address (Q1).
6. Whether patient view ships in the hackathon demo at all (architecture.md §13 allows cutting it).
