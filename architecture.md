# G3 Patient Journey — System Architecture (EN, detailed)

> Main challenge G3 (VZP Patient Journey) + side G4 (InterSystems). One diagnosis end-to-end (HPB pancreas, Mr. Novak ILLUSTRATIVE), principle not production integration. Source of truth: `context.md` (13 chapters + appendices A–E, updated 16 Oct 2026).

## 0. Goals, scope, definition of done

**Goal (24–30h):** functional passage of 1 synthetic patient from referral to confirmed handover on FHIR data in IRIS, with AI extraction + watchdog + MDT gate.

**IN:**
- Referral upload without extra form (1–2 clicks, existing PDFs from GP system)
- AI extraction + completeness check + human-check
- Queue with T1+T2+T3 time-to-treatment, status, owner, due, ACK, escalation (48h / 7d = demo thresholds, NOT norms)
- MDT with completeness gate + quorum + SBAR + Provenance
- Step 04 FINALE: structured MDT conclusion to referrer one-click with original context + automatic structured export to reviewer + ROC acceptance = DONE
- G4 proof (30s): same data via FHIR REST + SQL, baseURL switch = second hospital, Vector RAG with citation

**OUT (say it loudly to jury):**
- No custom order-entry system — adapter to central eZadanka (NCEZ/MZ state machine)
- No full DASTA↔FHIR conversion, only demo mapping in B1
- No B1 FN Brno outlier model (narrative parallel only)
- No transport/dispatch module, only external connector placeholder
- No production RBAC/E2EE/SMART — TODAY=MOCK, TARGET=slide
- Only K1 phase (pre-treatment fast-track), no full K2/K3, no multi-DG, no federation

**Definition of Done:** 6 demo points pass on Mr. Novak + 1 negative case + 30s G4 insert without crash. Backup video on localhost.

**Personas:** GP Dr. Vesela (referrer), Coordinator Vankova K1 (main user, does NOT decide treatment), Mr. Novak 60y C25.0 pancreas head tumor (synthetic), lost histology (negative scenario), MDT chair, pathologist/radiologist, ROC, reviewer (VZP), IT/admin.

**Metrics:** T1 symptom→KOC handover, T2 KOC admit→MDT decision, T3 decision→treatment start. Novak: T1 2d (5.1→7.1) + T2 13d (7.1→20.1) + T3 6d (20.1→26.1) = 21d (demo HPB target ≤28d). SLA per diagnosis in `SLA.json`, never fixed 4 weeks.

---

## 1. Architecture overview — blocks B1–B7

Principle: 7 modular blocks, each with 2 connectors (input protocol → output protocol). Single proprietary↔FHIR translation point in B1. Inside B2–B6 FHIR↔FHIR only via InterSystems IRIS. One dashboard (same data unless GDPR) + role-view filter + Spotlight plain-language role-specific alerts + optional AI agent OFF by default, IDs-only with client-side PII mapping, hospital-chosen hosting/granularity, kill-switch.

```
[GP AIS / NIS / LIS / RIS / PACS / VZP CSV / HL7v2 / CDA / PDF / eZadanka events]
  │ proprietary
  ▼
B1 Ingest + normalize ── FHIR Bundle + $validate ──▶ IRIS FHIR R4 repository (CZ Core)
  │ FHIR only from here                                              │
  ▼                                                                  ▼
B2 Coordination core (EpisodeOfCare+CarePlan+Task+CareTeam) ◀──▶ B5 Watchdog (Flag/DetectedIssue + Subscription)
  │ ▲                                                                │
  ▼ │                                                                ▼
B3 Dashboard shell (read-model, role-view, Spotlight, offline cache) B4 MDT XTB-WD (Appointment + completeness lock + Provenance)
  │                                                                  │
  └────────────── B6 AI agent (MCP IDs-only, RAG, drafts, never write) ┘
                         │
B7 Identity/RBAC/audit/GDPR — TARGET SMART 2.2/IUA/ATNA/PIXm/trezor; TODAY MOCK ?role= + matice.json + audit.jsonl
```

Boundary rule: hospital proprietary↔FHIR ONLY in B1. No parallel proprietary shortcuts to UI/AI.

InterSystems building blocks: Interoperability Production (Business Service/Process/Operation + HTTP/REST/SOAP/FTP/TCP/File/SQL adapters + DTL), SDA intermediate (CDA/HL7v2→SDA→FHIR), FHIR server R4 REST, FHIR SQL Builder (FHIR as SQL tables without data move, Analyze→Spec→Projection, roles FSB_Data_Steward + FSB_Admin), Bulk FHIR Coordinator ($export ndjson — Bulk IG not core), FHIR Adapter + SDA↔FHIR DTL, Embedded Python, Vector Search (VECTOR type, HNSW index, VECTOR_COSINE), RAG/GraphRAG + MCP (iris-agentic-dev, ai-hub-eap). DASTA→FHIR not officially documented → custom EDI schema + DTL via SDA. Templates: `iris-fhir-template` (docker FHIR server), `FHIR-AI-Hackathon-Kit` V2 (Jupyter FHIR→SQL→Vector→LLM→agents→MCP), `iris-agentic-dev` (90+ MCP tools).

Second hospital = switching `FHIR_BASE_URL`. Interoperability is configuration, not integration.

---

## 2. B1 — Ingest + normalization (anti-corruption layer)

**What/why:** translator + customs at border. Hospitals speak PDF/ZIP/HL7v2/CDA/VZP-CSV/eZadanka events. B1 translates everything to FHIR R4 CZ Core and validates. Only translation point in system.

**IN:** `PDF/ZIP upload + HL7v2 + CDA + VZP-CSV + eZadanka events`
**OUT:** `POST /fhir/R4/Bundle (transaction) → $validate → 200 / 422 OperationOutcome`

**FHIR:** Patient, DocumentReference (envelope + attachment.url, type=propousteci/zprava, original kept), ServiceRequest, Observation, DiagnosticReport.

**API:**
- `POST /api/v1/referral/upload {files[], patientHint} → {bundleId, operationOutcome[]}`
- `GET /fhir/R4/Bundle/{id}/$validate → 200 | 422 + OperationOutcome.issue[]`
- Invalid → `Task(code=clean-manual, owner=K1)` manual cleanup queue, never dropped.

**Example:** 6 Jan Vesela drags 2 PDFs (UZ + labs) → one Bundle → 200 empty OperationOutcome. Broken input → 422 + error list + new Task in K1 queue.

**IRIS:** Production + adapters, SDA hop, DTL transforms.

**Demo:** 2-click upload → green 200; broken file → red 422 + Task.

## 3. B2 — Coordination core (source of truth)

**What/why:** Jira for patient + conscience. One EpisodeOfCare split into Tasks with owner+due+ACK, eZadanka state machine, Subscription notifications. Only source of truth — dashboard/MDT/watchdog read from here, nobody keeps diverging copy.

**FHIR:** EpisodeOfCare(type=K1, period, status) + CarePlan(subject, addresses Condition, activity Task) + Task(owner, requester, status=requested|accepted|in-progress|completed, executionPeriod.end=due, code) + CareTeam(participant role+actor) + ServiceRequest + Encounter + Appointment.

**API:**
- `POST /fhir/R4/Task`
- `PUT /fhir/R4/Task/{id}$accept {actor, note}` = ACK (taking ownership)
- `GET /fhir/R4/Task?owner=K1&status=requested&sort=_due`
- `POST /fhir/R4/Subscription` (rest-hook)
- `GET /fhir/R4/Patient/{id}/$everything` (full card)

**eZadanka mapping (team mapping, NOT NCEZ):** Nova→ServiceRequest.draft+Task.requested; Prijata→Task.accepted (ACK, binding); Dokoncena→DiagnosticReport+Task.completed; Neproveditelna/Stornovana/Expirovana→Task.cancelled/failed + Flag. Official states only: Nova/Prijata/Neproveditelna/Stornovana/Dokoncena/Expirovana. Vyhledat/Nacist = operations, Vysledek = part of vyridit, capacity = return-to-circulation reason. No ServiceRequest.accepted (only Task.accepted). Immutable Bundle + 9 ops + ETag/409 + 3-year expiry.

**Example:** ServiceRequest for Novak → EpisodeOfCare + CarePlan (stent 9.1, CT 12.1, MDT 13.+20.1) + CareTeam (Vesela, Vankova, Bielcikova, radio, patho, surgeon, ROC) + Task pathology `deliver histo by 16.1` + Appointment + Encounter 7.1. Pathology clicks accept = ACK. Sent ≠ handed over — without ACK everyone sees `waiting for acceptance`. Lost histology (sample 9.1 sent, nobody ACKed, result nowhere) becomes visible measurable problem.

**Demo:** task list with owner+due+ACK, Accept click changes state + notify, T1/T2/T3 bars.

## 4. B3 — Dashboard shell (read-model)

**What/why:** tailored glasses. Read-model composing role views from core. Rule: filter view, never duplicate data. Spotlight federated search (FHIR+Vector). Offline cache (last $everything in localStorage).

**API:**
- `GET /api/v1/queue?role=K1&sort=priority`
- `GET /api/v1/patient/{id}/summary` (timeline, milestones, missing)
- `GET /api/v1/spotlight?role=K1`

**Role views:** GP only own cases (traffic-light + missing + MDT conclusion); K1 full queue sorted `severity*daysWaiting`; K2 `Task.code=mdt-prepare`; diagnostician only `Task.owner=me+status=requested`; oncologist `CareTeam.participant=me`; MDT chair Appointment+Provenance; ROC only `Task.code=handover-roc`; patient only own Encounter/Appointment plain-text; reviewer structured export; IT AuditEvent + tenant.

**Layout:** left Queue, center Detail, right Spotlight+Actions, top T-ticker + role-switch + kill-switch.

**Queue columns:** Priority | Patient | K1 phase | Next step + owner | Due + T-days | Status (New/In-progress/Waiting/MDT/DONE). Example: `▲ Novak C25 | Waiting: histology | Owner: Patho Svoboda | Due 2d | T+14d`.

**Detail:** header `Novak *1966 C25.0 T21d`, timeline 5.1→26.1, checklist (UZ ☑ histo ☑ staging ☐ PDL-1 ☐), tasks [Accept][Done][Escalate], copyable documents (VZP requirement).

**Demo:** `?role=` switch (MOCK today), 3 views, summary, badge, offline mode.

## 5. B4 — MDT XTB-WD (PCC, not ITI)

**Flow:** Request→Schedule(Appointment)→Prepare(checklist)→Meeting(votes)→Finalize(lock+Provenance).

**IN:** CarePlan/Task/Appointment write. **OUT:** Provenance/AuditEvent + CarePlan.activity + Communication.

**FHIR:** Appointment(participant required: radio/patho/onco/surgeon/K2), Provenance(target=CarePlan, agent, signature), AuditEvent, DocumentReference (MDT report), Communication (step 04).

**API:** `POST /api/v1/mdt/{episodeId}/finalize {sbar, votes[]} → 409 if completeness<100% without overrideReason (chair only)`.

**Completeness gate:** mandatory set per HPB demo (histo + staging + onco-report; full HPB set: UZ/CT, histology, staging_TNM, TM_CA19-9, ECOG, comorbidities). Gate locks Approve. Unlock only chair + overrideReason → audit. Vague conclusion rejected by validator (must contain decision + modality + date + owner). Quorum 4/4 demo (numeric quorum not claimed as norm — chair governs). Votes Pro/Contra/Abstain. SBAR [Copy] one-click into email. After finalize: lock + Provenance + CarePlan.activity + Communication dispatch.

**Example:** MDT 13.1 checklist histo red (lost) → Finalize locked, API 409. After B5 retrieval, MDT2 20.1 quorum 4/4 → SBAR → Finalize+sign → Provenance.

**Demo:** completeness bar with lock, failed finalize (409), chair override, 4/4 votes, SBAR copy, locked record.

## 6. B5 — Watchdog SLA

**IN:** timer trigger cron 5min. **OUT:** Flag POST + notify webhook + ACK callback.

**FHIR:** Flag(status=active, code=missing-histology|ack-timeout|roc-noaccept, subject, period, author=system) + DetectedIssue + Subscription(rest-hook).

**Demo thresholds (NOT norms, label ILLUSTRATIVE):** eZadanka ACK >48h → moderate; histology >7d → severe; ROC no-accept >48h → severe. Config `SLA.json {dg:C25: {ack:48h, histo:168h}}`. Aggregation + daily digest against alert fatigue (override 46–96%, 187 monitor warnings/patient/day, ICU FP 80–99%).

**API:** `POST /fhir/R4/Flag`, `POST /api/v1/notify/ack {flagId, actor}`.

**Spotlight rules:** modal interrupt ONLY severe + confidence≥0.85 + low FP + actionable <24h (e.g. histo >7d, ROC 48h). Content: title + why with data + action [Supplement/Escalate] + consequence + ACK reasons (Not mine / Handling / Disagree→log). Rest badge/sidebar, tiered severe/moderate/minor. Max 2-click action. Override is feature (logged + learned).

**Example:** histology sample 9.1, due 16.1, nowhere → severe Flag → webhook to Vankova → escalate to pathology → retrieved → MDT can proceed. Negative demo cases: P4 lost histology SLA −3h, P6 unaccepted ROC care.

## 7. B6 — Optional local AI agent (default OFF)

**Tools (MCP IDs-only):** `getPatientJourney(pseudoId) → sorted Bundle + T-metrics, no names`, `searchEvidence(query) → top-3 Vector hits {docId, chunk, cosine, citation}`, `explainFlag(flagId) → why with data`, `draftSBAR(episodeId) → S-B-A-R 4 paragraphs with [D-Histo9.1] links`.

**API:** `POST /mcp/getPatientJourney`, `POST /api/v1/ai/extract {documentReferenceId} → {fields[{name,value,confidence,quote,docId,needsHuman}], completeness{have[],missing[],score}, action}`, `POST /api/v1/ai/kill {off:true}`.

**Extraction schema:** each field value+confidence+quote+docId+page. confidence<0.75 → yellow + needsHuman; <0.5 → not propagated without signature. No citation = not shown. Example histo date 0.97, dg C25.0 0.91, staging T2N0M0 0.62 needsHuman. Negation handled (`no metastasis` ≠ `missing result`).

**Guardrails:** human-on-the-loop (visible intermediate states, pause/rewind), proposes (summaries, prioritization, drafts) / human decides (signature, override, escalation); citation per claim; clinical narrative not SHAP heatmap; prefilled editable low-friction verification; UAII label + validation transparency + feedback. Never direct write to CarePlan/Task/MDT-report without `Provenance.agent=human`. Default IDs-only, scope patient/ + v2.2 filters, token exchange RFC 8693, ID↔PII mapping only client/B7 vault (HSM/KMS, split-key, audit). Granularity per hospital 0=OFF default / 1=summary no PII / 2=full context with purpose, each logged. Kill-switch one button (B6 stop, dashboard from cache, AI_DISABLED banner + audit). SMART 2.2 + Backend Services JWT + PKCE + short tokens. LLM default on-prem open-weights + local vector store; cloud only pseudonymized/UUID opt-in. Pseudonymization ≠ anonymization (Art.9 persists). Forbidden: auto-send to referrer, auto-finalize MDT, cloud LLM with PII. Backend holds Azure APIM key (`api-key` header), never frontend. Fallback on 429/401 → pre-baked extractions + regex rules.

**Demo:** OFF by default → ON → fields with citations+confidence, RAG `Does patient have histology?` with citation, write attempt rejected, kill-switch.

## 8. B7 — Identity, access, audit, GDPR (TARGET vs TODAY=MOCK)

| Area | TARGET (production) | TODAY=MOCK (demo) | Jury line |
|---|---|---|---|
| RBAC | SMART 2.2 + role×purpose matrix Art.6/9 | `?role=` select + `matice.json` | Today mock, target SMART/IUA, DPIA required |
| PII for AI | IDs-only + vault HSM/KMS, levels 0/1/2 | pseudoUUID, names client-only | Agent sees no names, rewrite in browser |
| E2EE | client-side blob only, else TLS+RBAC+audit — never claim E2EE over FHIR | TLS, claim nothing | Netvrdime E2EE nad FHIR |
| Audit | AuditEvent ATNA/BALP immutable + Provenance, retention per AI Act Art.12 | `audit.jsonl` in browser | Every override/finalize traced, today local |
| Kill-switch | B6 stop, cache mode, AI_DISABLED + audit | button hides AI panel | One button, visible state |
| Consent/retention | DPIA+FRIA (Art.35(3)(b) risk-conditional, not automatic), Art.22 HITL, Art.28 DPA | synthetic data, simulated consent | Synthetic, cloud only with guarantor OK |
| AI Act | CDS high-risk via Art.6(1)+Annex I (MDR SaMD) → conformity, logging Art.12, oversight Art.14; omnibus 2.12.2027 (Annex III) / 2.8.2028 (Annex I); general 2.8.2026; narrow transcribe→structure without scoring may fall out, proposing = high-risk | draft + human signature | AI only transcribes/proposes, never decides |

Jury sentence: `Honestly: today principle on synthetics without real RBAC. Production = SMART + vault + DPIA + audit. Nothing hidden.`

## 9. End-to-end data — Novak skeleton (MOCK R4 + CZ Core; SMART/RBAC/audit = TARGET)

Patient (Novak, pseudonym) → Encounter (hosp 7.1) → Condition (C25 pancreas tumor + staging) → Observation (TM CA19-9, histology) → DiagnosticReport (CT 12.1) + ImagingStudy → Procedure (stent 9.1, surgery 26.1) → ServiceRequest (eZadanka CT) → CarePlan (from MDT 13./20.1) + CareTeam (onco/surgeon/radio/patho/coordinator) + Tasks (owner+due+ACK) → DocumentReference (MDT report) → Communication (step 04 to referrer) + Provenance (votes) + AuditEvent (all) + Flag (missing TM) + RiskAssessment (B1 parallel only).

T-computation in B2 from Task.executionPeriod + Appointment.start + Procedure.performed.

## 10. G4 30s proof (IRIS+FHIR+AI)

Two windows on stage:
1. Same data two ways (10s): `GET https://iris.local/fhir/R4/Patient/Novak-pseudo/$everything → 14 resources` vs `SQL: SELECT id, code, performed FROM FHIR_OBSERVATION WHERE patient='Novak-pseudo' → 14 rows`. Line: no data move — FHIR SQL Builder projection.
2. Second hospital = baseURL switch (10s): `.env FHIR_BASE_URL=https://iris.local/fhir/R4 → https://roc-brno.local/fhir/R4`, refresh, same queue different data. Line: interoperability is configuration, not integration.
3. Vector RAG with citation (10s): `When was stent and why? → 9.1.2026, icterus, biliary stent [D-Histo9.1 p.1, cosine 0.87]`. Show VECTOR_COSINE + HNSW.

Tech: `iris-fhir-template` docker + Hackathon-Kit notebook (CSV→IRIS, FHIR CRUD, Bundle, FHIR→SQL, embeddings+RAG, LangChain) + $export ndjson. No HealthShare needed, IRIS for Health Community suffices. IRIS ops: $validate/$everything/List $find, Observation $lastn, $export (Bulk IG), $expand; multi-endpoint namespace; versioning.

## 11. UI/UX verified patterns, alert/AI trust

Single prioritized inbox (new/in-progress/resolved), persistent patient panel, summary-first timeline; navify −35.4% MDT time, −76.5% documentation (footnote: Taiwan 2021 single-centre, recording comments). Actions in context max ~2 clicks, visible owner+due+ACK, team routing (AIM −12.2 msgs/doctor/day). AI: citation per claim, narrative not heatmap, counterfactual curbs over-reliance, calibrated confidence (green/orange/red), quality of inputs, easy override with reason, audit trail, no bulk Accept-all, AI literacy, validation transparency, feedback, guidelines NCCN/ESMO. SHAP raises confidence not agreement. HITL +7.1% vendor-blog pending primary — do not claim. Documentation −24–72% only with real engagement, beware scapegoat-in-the-loop.

## 12. Demo script 4 min + pitch 3 min

**Demo (Novak + 1 incomplete):** 0:00–0:30 queue (6 patients C50/C34/C18, Novak HPB T2 running MDT 13.1 in 2d, red row missing TM SLA −3h); 0:30–1:10 referral no-form (PL 2 PDFs 2 clicks, B1 → Bundle + $validate empty) #1; 1:10–1:50 AI extraction + completeness (date, UZ/CT/TM, histo, stent, MDT dates, each quote+confidence, missing TM red Flag, second case negated finding) #2; 1:50–2:30 overview + owner (T1/T2/T3 bars, traffic-light, owner+ACK, escalation ROC 48h ping) #3#4; 2:30–3:20 MDT + conclusion (completeness gate histo+staging+onco-report proposal not norm, quorum, SBAR with source drill-down, votes→Provenance, output Tasks) #5; 3:20–4:00 feedback FINALE (referrer gets result with original context one-click, reviewer auto with AI sorting, handover confirmed → closed, audit trail on screen) #6; G4 30s anytime (REST+SQL SELECT, baseURL switch, Vector with citation).

**Pitch 3 min whole team (non-technical + health audience incl. PM/minister):** 0:00–0:20 hook (>50% lung Ca late — breast/pancreas not claimed; not disease fault, system fault; Novak ILLUSTRATIVE had luck — had coordinator); 0:20–1:00 problem (3 loss points, coordinators phone+paper, MDT without docs, loop never closes); 1:00–2:10 demo (6 points on Novak 90s + step-04 finale, T-metrics, principle not integration); 2:10–2:40 G4 + security (FHIR store + AI-ready, IDs-only kill-switch MOCK, GDPR matrix TARGET proposal); 2:40–3:00 impact + next (weeks saved, coordinator hours/day, VFN HPB pilot, VZP fast-track, one DG today all tomorrow). Each member ~30s block; backup video if wifi dies; thank mentors with verified spelling.

## 13. Build order 24h + owners + risks

- 0–3h FHIR+import (IRIS owner): docker template up + Novak Bundle + 1 incomplete P4 + Task/CarePlan; done $everything 14 resources; verify dataset links. Risk IRIS fails → HAPI FHIR / json-server + FHIR badge.
- 3–8h core+UI (fullstack): queue priority, T-metrics, owner+ACK + role UI (K1 main, GP, MDT, referrer PL). Risk time → cut patient view, keep K1.
- 8–14h AI+watchdog (AI): extract endpoint via backend (never key to frontend) + completeness + Flag cron 48h/7d. Done citations + gate. Risk 429/401 → pre-baked JSON + regex.
- 14–19h MDT+step04+RAG (fullstack+AI): lock + votes + SBAR + Communication + getPatientJourney MCP + SQL Builder. Done finalize→Provenance. Risk quorum complexity → 4 checkboxes + 1 signature.
- 19–24h demo+pitch (all): 6 points 3× rehearsal + G4 30s + $validate + OperationOutcome + submit + Azure RG cleanup. Done backup video + submit form (URL verify on site) + repo + image.
- Continuous: mentor checks (T-metrics, reviewer, GDPR matrix), clinical validation (deadlines, mandatory triple, quorum, who may ACK).

Fallbacks: IRIS→HAPI, Azure→mock JSON, wifi→localhost + video, guarantor N/A→demo thresholds labeled ILLUSTRATIVE.

## 14. Open questions (verify on site)

1. KOC mail hpb vs hbp — real box or placeholder? Do not hardcode.
2. Dataset/dictionary/indicator links — where (Slack?) live?
3. Exact deadlines: 19:00 team confirm where? ~13:00 = workshop resume (not submit); submit URL garbled (`subwit.caton.cz`?) + what to submit.
4. Names spelling (Chrastova/Vankova/Tuma…) + roles for slides.
5. Prices 100k/50k for what? Fast-track terms?
6. SLA per dg/phase (ACK? histo/staging?) — 48h/7d illustrative.
7. Mandatory triple + quorum — universal or per dg? Who unlocks + how audited?
8. Who may own Task and ACK KOC↔ROC (role vs person)?
9. Tenant: federation (data at source) vs central IRIS copy?
10. AI OFF + IDs-only: guarantor accepts utility without PII? Level-2 boundary?
11. Transport: external dispatch connector enough or full module?
12. Cloud LLM on (synthetic?) data — explicit guarantor consent?
13. Pilot KOC/region network (eZprava/eMeDocS/datovka)? Vendor NIS FHIR today (SMART launch? write-back? RBAC?)?
14. B1 numbers + InterSystems.txt (names, MDR, hospitals) — verify at stand, do not rely.
15. Role matrix for dashboard (KOC/coordinator/external/nurse/dispatch/driver): Art.6/9 title, confidentiality, retention — with DPO.

---
*End of architecture. One diagnosis, six demo points, principle not integration. TARGET vs TODAY + MOCK labeled where applicable.*
