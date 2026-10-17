# Oncology journey roles — evidence and frontend priorities

Research date: 16 October 2026. Scope: Czech oncology referral, diagnostic workup, MDT preparation and handover. This is a research report, **not a clinical protocol, permissions specification or instruction to change the app automatically**.

## Executive conclusion

The four roles do not need four differently coloured versions of the same dashboard. They need different working views of the same case:

| Role | Their central job | First question the interface should answer | Recommended leading surface |
|---|---|---|---|
| **Koordinátor** | Arrange and follow through on indicated care across people, documents and appointments | **What is holding this case up, who must act, and by when?** | An actionable work queue with the next step, owner, due date, missing material and handover status |
| **Pacient** | Understand their situation, participate in decisions and navigate their own care | **What is happening to me, what happens next, and who can help?** | A plain-language next event and current status, with access to explanations, results, questions and contact details |
| **Lékař** | Depends on whether they are referring, treating or providing a diagnostic opinion | **What do I need to know or do in this clinical role?** | Referrer: referral progress and returned outcome. Treating clinician: evidence, patient preferences and plan. Diagnostician: the question, material and result destination |
| **MDT** | Combine relevant clinical opinions into a documented recommendation and follow-up | **What question are we deciding, what evidence is available, and what happens after discussion?** | Preparation, meeting and outcome views of one shared record—not just a completeness bar or voting screen |

**The screen ordering above is a product recommendation derived from the evidence, not an empirically proven universal ranking.** Individual patients, diagnoses and local services differ.

## Evidence and its limits

- Six explorer/librarian lanes examined local assumptions, the implemented frontend and external sources. Failed rate-limited lanes were relaunched; snippet-only claims were subsequently checked, corrected or excluded.
- Czech KOC criteria and the Czech MDT guideline provide the strongest local role/workflow anchors. They do not establish every permission, deadline or portal requirement.
- NICE recommendations provide explicit patient-information and follow-up guidance. They are **English guidance, not Czech law**; no English referral deadline is adopted here.
- The cited patient-information review covers adults already diagnosed with cancer. It does not establish the correct first screen for someone with an unconfirmed diagnosis.
- No interviews or usability studies with this team's actual patients or staff were performed. The report is desk research, not local user validation.
- Primary recommendation chapters [P1–P3] were directly checked during synthesis, rather than relying only on search snippets or guideline overview pages.

## 1. Koordinátor: the person who keeps the journey moving

### What the role actually does

The Czech KOC criteria describe a coordinator acting on a **written request from treating physicians**, arranging **already-indicated planned care**, using hospital information systems, documenting coordination and reporting back to clinical staff. The described work includes consultations, imaging and surgery bookings. [C1]

This is a coordination function, not an automatic grant of authority to diagnose or choose treatment. A person may separately hold a clinical qualification and responsibilities; the product must not infer those responsibilities from the label “koordinátor”.

Do not merge all coordinator variants:

- **Patient-pathway coordinator:** follows a person through appointments, documentation and handovers.
- **MDT meeting coordinator/administrator:** assembles the agenda and material, records outcomes and distributes them. These duties overlap but are not the whole patient-pathway role. [M1]
- **Local diagnosis-specific, first-contact or regional arrangements:** must be established with the pilot centre, not invented as universal job categories.

### Information priorities — recommended

1. The next unresolved step and why it needs attention.
2. The physician's request: requester, date, indicated examination or service and supplied priority.
3. Named responsible person/team, due date and whether responsibility was accepted.
4. Missing documentation: exactly what is missing, who should supply it and when it was last pursued.
5. Relevant appointments and MDT date; booking/capacity information **only where the service actually supplies it**.
6. Communication history and explicit handover to the next responsible team.

Useful actions: arrange indicated care, request missing material, record contact, track follow-up and prepare the MDT packet. Exact authorization and escalation routes require local confirmation.

**Avoid:** opening on a long clinical record, making staff infer ownership from a timeline, treating every delay as clinical danger, or adding an autonomous medical-priority score.

### Corrections to our previous assumptions

- **K1/K2/K3 should not be presented as three official coordinator specializations.** The ministry presentation uses them for patient phases: before, during and after treatment. Earlier local documents overload these labels.
- Věstník 11/2025 supports the coordinator-position criteria, including a minimum 1.0 FTE and the statement that healthcare education is not required. The attribution of the **1 January 2026 date to the text of that Věstník alone** is not supported by the coordinator research; that date needs its separate ministry/accreditation source.
- “No clinical decision-making by virtue of this coordinator role” is a safe product boundary; do not misquote it as a verbatim statutory sentence.

## 2. Pacient: an informed participant, not a simplified staff user

### What the evidence supports

NICE explicitly recommends tailoring information to the person's preferred level and type of detail. The information includes their condition and options, where they will be seen, who will provide care and expected waiting times. It also recommends accurate updates about delays. [P1, 1.5.14 and 1.5.19]

For **suspected cancer**, the guidance is more specific: explain where the referral goes, what to expect, possible tests, expected timing of results, whether someone can accompany the person, who to contact if an appointment is not confirmed and sources of support. [P2, 1.14.3]

The patient-information systematic review identifies diagnosis, prognosis and treatment options as important stated needs among adults diagnosed with cancer. This does **not** justify presenting a prognosis before a diagnosis exists, or forcing everyone through the same amount of detail. [P4]

### Information priorities — recommended by situation

**While the diagnosis is uncertain:**
- What is known, what remains uncertain and why the next examination or consultation is happening.
- What happens next; when and where; whether attendance is required.
- When results or an update are expected, who owns that update and whom to contact if it does not arrive.

**After a diagnosis or MDT recommendation:**
- An understandable explanation and the next discussion with the treating clinician.
- Proposed options, uncertainty and the patient's questions and preferences.
- A clear distinction between a draft, an MDT recommendation and an agreed care plan. Shared decision-making is a collaboration with the patient, not an automatic consequence of the meeting. [P3]

**Throughout:**
- A recognisable care contact, with real supplied contact information.
- Access to more detail and relevant correspondence, with explanations rather than unexplained codes. NICE recommends offering accessible copies of professional correspondence. [P1, 1.5.9]
- Communication and accessibility preferences; whether and how family or carers should be involved. Do not assume access merely because someone is a relative. [P1, 1.3.10]

Useful actions, where supported by the actual service: ask a question, confirm an appointment, report a practical problem and record communication preferences. Clinical preparation instructions must come from the care team, not from interface authors.

**Avoid:** jargon-first records, unexplained alarming colours, operational SLA scores, implying that absence from the MDT means absence of patient input, or hiding meaningful information on the assumption that patients cannot understand it.

**Design implication:** keep the graphical next-step view, but pair its simplicity with optional depth and patient agency. NICE supports pictures and symbols alongside accessible language—not pictures instead of meaningful information. [P1, 1.5.4 and 1.5.13]

## 3. Lékař: distinguish the clinical hats

“Doctor” is not a sufficiently precise product persona. One person can wear more than one of these hats, so these are workflow contexts rather than rigid professional classes.

| Clinical hat | Must see first — recommended | Supporting information | Important boundary |
|---|---|---|---|
| **Referring GP or specialist** | Referral acceptance/progress, who owns it, missing information, what requires their response, returned outcome | Original referral reason, uploaded documents and relevant clinical context | Do not make AI-extraction review the main purpose of referral follow-up |
| **Treating clinician/oncologist** | Relevant evidence, current clinical question, previous care, patient preferences and proposed next plan | Histology, imaging, stage where established, performance status and comorbidities | MDT recommendation informs care; decisions with the patient and local clinical authority still matter |
| **Diagnostician** | The examination or opinion requested, clinical question, material/source availability, due date and result destination | Relevant previous findings and comparisons | “Assigned task” is not the whole clinical context needed to interpret a result |
| **MDT contributor/chair** | Their preparation question or the shared discussion agenda and outcome | Relevant specialties, attendance and evidence | Chair responsibilities must not silently attach to every “Lékař” account |

The Czech MDT evidence supports communicating outcomes to treating clinicians and GPs and including the appropriate clinical and patient context. [M1, M2]

NICE also explicitly assigns responsibility for reviewing and acting on investigation results to the professional who ordered the investigation **or someone to whom they explicitly pass responsibility**. This supports modelling responsibility and handover; it does not dictate our precise button or layout. [P2, 1.15.1]

The US referral study shows why a referral's status should not be assumed from its existence. It studied scheduling records, however—not Czech clinician preferences or the success of our design. Its appointment-completion metric must not be misrepresented as the rate of results returned to a GP. [D1]

**Corrections:** “GPs do not read histology” is unsupported. “A referring doctor never treats” is also wrong: a referring specialist may be involved in treatment. Avoid granting or denying medical authority merely from the selected screen.

**Current app gap:** our “Lékař” view is a **referring-doctor view** with a prominent source-review table. It is not yet a treating-oncologist workspace. A sensible next design test is to lead with the referral loop and place source review where a concrete review task exists.

## 4. MDT: a team process before, during and after a meeting

### What it actually is

The MDT combines relevant professional perspectives into a documented recommendation. The Czech sources describe collective formulation, appropriate specialty representation, chair/process responsibilities and coordination/recording duties. They do not establish one universal four-person voting threshold or one national software-signing workflow. [M1, M2]

### Information priorities — recommended by phase

| Phase | Leading information | What the workspace should support |
|---|---|---|
| **Before** | The question to the MDT; concise case context; patient preferences; available and missing evidence; relevant participants | Preparation ownership, source access, a diagnosis/centre-specific checklist and a clear reason for discussion |
| **During** | The case question, imaging/pathology findings, relevant views and uncertainty | Shared discussion record, participation, an explicit outcome and recording of disagreement or uncertainty |
| **After** | What was recommended or deferred; why; who must do what; communication destinations | Follow-up actions, named owners, dates, approval according to local policy, distribution and confirmation of handover |

The chair, coordinator/administrator, presenting clinician and contributors need different controls on that shared record. A meeting coordinator may record/distribute an outcome while clinical approval follows a separate local process. [M1, M4]

### Critical correction: completeness is not a universal binary lock

- The demo's five documents or earlier “mandatory triple” are **illustrative**, not a universal HPB clinical protocol.
- Missing histology does not mean every discussion must be prohibited. Outcomes can include requesting further workup, deferral and re-presentation; urgent exceptions and out-of-meeting routes need local clinical governance. [M1, M3]
- The Czech guideline explicitly says treatment must not be delayed merely because timely MDT consultation is organizationally impossible. Do not turn a software completeness gate into a clinical veto. [M1]
- Four-of-four quorum, chair-only finalization and specific communication deadlines must be confirmed locally. English regional 24-hour guidance is not a Czech national rule. [M4]

**Current app gap:** the MDT view demonstrates preparation, missing evidence and a blocked unsigned draft. It does not yet represent the full meeting/outcome/follow-up workflow. Keeping real finalization disabled in the present frontend is different from claiming that all real cases must remain blocked.

## 5. Product implications to validate next

These are **proposals**, not changes made by this report:

1. Keep the four top-level entry points, but specify whose job each view serves. Label the current physician view as referring-doctor work until a treating-clinician workspace is intentionally designed.
2. Coordinator: make requests, blockers, appointments and responsibility the centre of the work queue—not a reduced clinical chart.
3. Patient: retain the calendar/journey, add appropriately sourced status and contact detail, and allow optional depth, questions and communication preferences.
4. MDT: separate preparation, discussion and outcome/follow-up. Make the clinical question and patient preferences explicit. Treat missing/uncertain/not-applicable as different states.
5. Use one shared case truth, but different authorized projections and actions. A shared record does **not** mean everyone sees identical information.
6. Preserve the explicit mock-data banner and single data-source switch. These are user-required development safety controls, not clutter to remove based on role research.
7. Real patient views must be bound to authenticated patient access, not to whichever case was selected in a coordinator demo. The current URL role switch is presentation only.

## 6. Questions for local validation

- Which coordinator variants exist in the pilot, who requests their work and how are interventions recorded?
- Who may accept a task or KOC/ROC handover: an organization, a named person or a particular clinical role?
- Which physician is the primary target of “Lékař”, and what response do they need from the system most often?
- For the pilot diagnosis, which evidence is required for which type of MDT outcome, and which exceptions are legitimate?
- Who records, approves, signs and distributes the MDT conclusion locally?
- Who explains results to patients, what timing can honestly be shown, and what happens when it is missed?
- Which information, language, accessibility and caregiver preferences do actual patients want supported?

## Sources

**C1 — Czech KOC criteria, Věstník MZD 11/2025** (2025), coordinator article and KOC criteria. Primary local organizational/accreditation source; librarian checked the text concerning written physician requests, indicated care, documentation and qualifications. Do not infer a complete legal permission matrix from it. PDF: https://onconet.cz/res/file/dokumenty/vestnik-mzd-2025-11-01.pdf

**M1 — Organizace a činnost multidisciplinárního týmu v onkologii**, KDP-AZV-20 (2022; NIKEZ record republished 2024). Czech professional guidance/expert consensus, not trial evidence or a universal software protocol. Roles, case material, patient context, communication, clinical exceptions. https://kdp.uzis.cz/res/guideline/20-organizace-cinnost-multidisciplinarniho-tymu-v-onkologii-final.pdf — index: https://nikez.mzcr.cz/guideline/19-organizace-a-cinnost-multidisciplinarniho-tymu-v-onkologii/

**M2 — ČOS position statement: Systémová léčba a multidisciplinární spolupráce v klinické onkologii** (2023). Czech professional-society statement on collective recommendations and clinical collaboration. https://www.linkos.cz/ceska-onkologicka-spolecnost-cls-jep/stanoviska-cos/priority-a-stanoviska-cos/position-statement-cos-systemova-lecba-a-multidisciplinarni-spoluprace-v-klinick/

**M3 — NHS England, Streamlining Multi-Disciplinary Team Meetings** (January 2020). English operational guidance; discussed versus standard-of-care-listed cases, relevant data and patient preferences. Not a Czech quorum or SLA. https://www.england.nhs.uk/wp-content/uploads/2020/01/multi-disciplinary-team-streamlining-guidance.pdf

**M4 — West Midlands Cancer Alliance, Cancer MDM Best Practice Standardisation Guidance** (May 2022). Regional English guidance for preparation, outcome capture and distribution. Local process example, not Czech regulation. https://www.wmcanceralliance.nhs.uk/images/MDM_Best_Practice_Standardisation_Guidance_Final_v_1.0_May_2022.pdf

**P1 — NICE CG138, Patient experience in adult NHS services** (2012; last reviewed August 2021). Directly checked recommendations: 1.3.10 caregiver involvement; 1.4.3–1.4.6 information continuity, responsibilities and contacts; 1.5.4, 1.5.6, 1.5.9 and 1.5.11–1.5.19 accessible information, preferences, waits and delays. https://www.nice.org.uk/guidance/cg138/chapter/Recommendations

**P2 — NICE NG12, Suspected cancer: recognition and referral**, patient support/safety-netting chapter (cited recommendations marked 2005/2015). Directly checked 1.14.3–1.14.8 information and support during referral, 1.15.1 responsibility for results, 1.16.5–1.16.7 follow-up and referral context. No UK referral deadline is adopted. https://www.nice.org.uk/guidance/ng12/chapter/Recommendations-on-patient-support-safety-netting-and-the-diagnostic-process

**P3 — NICE NG197, Shared decision making** (last reviewed June 2021). Directly checked definition, 1.3.1–1.3.3 decision aids and 1.4.1–1.4.2 personalized discussion/uncertainty. International guidance, not a substitute for local clinical governance. https://www.nice.org.uk/guidance/ng197/chapter/Recommendations

**P4 — Tariman et al., Information Needs Priorities in Patients Diagnosed With Cancer: A Systematic Review** (2014). Thirty included studies; adults with diagnosed cancer. Supports diagnosis/prognosis/treatment information needs, not an ordering of screens for suspected cancer or a Czech portal evaluation. https://pmc.ncbi.nlm.nih.gov/articles/PMC4042668/

**D1 — Patel et al., Closing the Referral Loop: an Analysis of Primary Care Referrals to Specialists in a Large Health System**. US electronic-record analysis of referrals from July 2015 to June 2016. Supports the problem of undocumented referral outcomes; scheduling completion is not the same as returned specialist documentation or patient preference. https://pmc.ncbi.nlm.nih.gov/articles/PMC5910374/

### Excluded claims

Unverified snippet-only studies, guessed publication dates, general referral-closure percentages, payment figures, blanket statements about GP authority, and unverified Czech records-access interpretations are not used as evidence for this report. No claimed numerical benefit of our interface is supported by this desk research.
