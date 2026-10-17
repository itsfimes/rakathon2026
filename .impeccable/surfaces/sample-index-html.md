---
version: 1
slug: "sample-index-html"
primary_target: "sample/index.html"
related_targets: []
---

# Surface: sample/ — design-language specimen (development only)

Scope: offline static specimen of four role views (Koordinátor, Pacient, Lékař, MDT) for one synthetic pancreatic (C25) case, plus a compact token/component/state specimen. Operate mode, code-led. Not the application; no six-flow implementation.
Revision 2 (rebuild; documented in design.md, awaiting user evaluation): user rejected revision 1 as too simplistic and text-heavy; wants middle ground, modest corners, visible borders, compact role switch, more graphical explanation.
Unresolved: future stack; real role matrix; SLA values.

## Direction contract
THESIS: The category standard played straight, at a firmer middle ground — bordered panels, compact segmented role switch, labelled icons and step graphics — so every role sees the next step, owner and deadline instantly; refuses themed metaphors, hero metrics, pill-soft minimalism and prose walls.
OWN-WORLD: White panels with 1px slate borders (#B8C2CE) on cool grey #F1F4F8, ink #1B2430, one restrained blue #1F5FBF for action/selection/current step, 4px corners, rectangular status tags with icon+word; system-ui, fixed rem scale; 18px line icons authored inline, 1.75 stroke.
STORY: Coordinator scans a dense pancreatic (C25) queue and sees who owes what by when; patient sees the next date as a calendar tile, a short next-step panel and a labelled journey (done / now / later); doctor sees source excerpts with honest certainty; MDT sees completeness, current blocking step and an unsigned draft.
FIRST VIEWPORT: Compact top app bar: product name, short “Ukázka · smyšlená data” tag with link to full disclaimer, segmented role switch with icon+label: one sticky row on desktop (65px at 1440); on phones (≤760px) a non-sticky 3-column, two-row grid with every option visible (measured app bar 136px / h1 top 148px at 390; 160px / 172px at 320). Coordinator: KPI-free queue table left, case detail right with T1/T2/T3 step bar and Další krok panel.
FORM: Category standard (canon), Linear-consistent controls, GOV.UK-plain patient steps; seed: seed:058ee1a2750ab247
SIGNATURE: the “Další krok” panel with icon rows (co / kdo / do kdy / převzetí) shared across roles, and the labelled vertical journey with connectors for the patient. Motion: none beyond 150 ms colour change.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
