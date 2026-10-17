# Design audit and handoff — sample/

Status: revised design-language proposal for user evaluation. Not the application, not user-approved final, no WCAG certification.

## Scope reviewed
Offline specimen `sample/index.html`: four role views (Koordinátor, Pacient, Lékař, MDT) plus the "Vizuální jazyk" token/component/state specimen. Desktop 1440 and mobile 390 full-page captures.

## Fixes made in this design study
- Rebuild after user rejected the first simple, text-heavy, rounded sample: 1px visible borders, 4px corners, icon+word tags, calendar tile and labelled journey for the patient, compact top role switch.
- Mobile role switch: horizontal strip that clipped labels replaced by a non-sticky 3-column, two-row grid; all options fit without horizontal clipping at page top, with a filled current-role state. The static header scrolls away normally.
- Sticky header covering skip/deep-link headings: header static on mobile; desktop targets get `scroll-margin-top: 4.5rem`.
- Queue scope: off-scope C24/C22 rows replaced with C25 pancreas fixtures; names, states, dates and layout unchanged.
- Docs: README describes the top-bar switch; surface brief says pancreatic (C25).

## Measured / observed (headless Chrome over CDP, file://, no dependencies)
- Generated text-node contrast check on sampled solid ancestor backgrounds: minimum 5.31:1, no failures within that check. This is not exhaustive coverage of placeholders, UI boundaries, interaction/focus states, alpha compositing or assistive-technology conformance. Decorative dividers (`line-soft`) and tag borders are not held to 3:1; control boundaries use `line-strong`.
- Tab → Enter on the skip link, every view, at 320 / 390 / 1440: focus on `#obsah`, view h1 below the header.
- Deep links `?role=pacient#obsah`, `#mdt`, `#lekar`: heading visible. Hash changes and back/forward preserve the current-role selected state at 320/390; its option fits the grid without horizontal clipping when the header is in view, but the non-sticky header can scroll out of the viewport normally.
- Shell size (fresh, cache disabled): 1440 sticky bar 65px, h1 top 89px; 390 static bar 136px, h1 148px; 320 bar 160px, h1 172px.
- No JS: all four role views and the specimen are visible; the state switch is hidden.
- No external requests, no console errors.
- Queue DOM (final evidence): Jan Novák C25 · hlava slinivky; Alena Šimková C25 · tělo slinivky; Tomáš Dušek C25 · tělo slinivky; Marie Králová C25 · ocas slinivky; Pavel Říha C25 · vývod slinivky; Karel Veselý C25 · nový případ.
- Known check flags: three queue column headings report past the edge at 320px; they are visually hidden on mobile and there is no sideways scroll, but the check does not prove that. The queue table overflows at 200% text size at 1280px (inside its scroll region).

## Detector warnings (last run, 8, interpreted, not zero)
1 side-tab: step bar current-step inset bottom rule (intentional, paired with fill and word).
6 cramped-padding: segmented controls (×2), disclosures (×3), calendar tile — flush children by design.
1 repeating-stripes-gradient: hatched "unsure" completeness cell (non-colour signal).

## Latest visual verdict
Independent reviewer: the mobile role-strip fix is resolved; ship for that fix only; no material regression; mobile shell is a little taller. It does not approve the whole design. The 8 other captures stay valid because the UI did not change after them; earlier coordinator captures still showed C24/C22, so use the `final-koordinator-*` captures.

## Still pending
Real touch devices, screen readers / assistive tech, OS high-contrast mode, browser zoom, usability testing with each role, user acceptance of this revised look. Future frontend stack, real role/capability matrix (proposal in `product.md`, not authorization), clinical rules and SLA values are open.

## How to open and re-check (installed tools only)
- Open: `xdg-open sample/index.html` (or any browser, `file://`). `?role=pacient` opens a view directly.
- Syntax: `node --check sample/app.js`
- Sidecar: `node -e 'JSON.parse(require("fs").readFileSync(".impeccable/design.json","utf8"))'`
- Whitespace: `git diff --check` and `git diff --no-index --check /dev/null <new file>` for untracked files.

Evidence in `.impeccable/review/` (`validation-r3*.txt`, `final-evidence.txt`, `final-koordinator-{desktop,mobile}.png`, role captures) is generated locally, ignored by git, and not part of the source.

## React app (app/) — verification and limits (frontend only)

- Checks: `npm run check` (typecheck, lint 0 warnings, 45 tests / 7 files, build, verify:no-mocks over 7 files) and `npm run build:mock` + `verify:mock` pass after the typography refinement.
- Final captures (after the mobile strip compaction, review-button wording and typography change): `.impeccable/review/app-final-backend-koordinator-{desktop,mobile}.png`, `app-final-mock-{koordinator,pacient,lekar,mdt,specimen}-{desktop,mobile}.png` (1440 / 390 full page). The earlier `app-*.png` captures without `final` are **replaced** (they show the 96px mobile strip, old button wording and old type sizes).
- Bounded browser checks (`app-final-type-checks.txt`, one run ≤ 50s): patient event/journey/helper text 16px/24px; panel title 19px; task 19px; table secondary 14px; quote 14px/21px; cite 13px; button 14px/17.5px at 40px height; computed weight 650. No horizontal overflow at 320px (all 5 views) or at 200% text (1280, 4 roles). Mock strip stays visible at the top when scrolled (390). No external requests, no page exceptions.
- Earlier runtime evidence still applies (code unchanged): skip link → heading visible below bars; history back/forward focus (`app-validation-r2-history.txt`); forced-colors current segment; text spacing. The long `app-validation-r2.txt` run has an invalid history section (harness timing) — use the history file.
- Detector: `impeccable detect --json app/src` → `[]` (`app-final-detect.json`). Not a claim of zero issues.
- Contrast: colours unchanged, prior sampled evidence reused; the new 16px muted patient text uses `--c-ink-muted` (≥ 5.3:1 measured earlier).
- Pending: real devices, screen readers, OS high contrast, usability with each role, a real backend adapter, the user's visual acceptance. No WCAG certification. The one-off capture of `lekar` desktop needed a second attempt (first frame blank due to readiness timing; recaptured once).
- Final visual evidence reconciliation: the specimen-mobile capture was also taken mid-bootstrap. It was replaced only after the source mode resolved to `mock`, with the synthetic banner and matching footer verified. Cache-busting copy: `app-final-mock-specimen-mobile-confirmed.png`; readiness record: `app-final-specimen-recapture.json`.
- Independent final visual disposition: **ship**, across the 12 valid final captures, with no open material visual finding. This is a visual review, not a runtime/accessibility certification or the user's final acceptance. Cosmetic whitespace on the desktop patient view and wrapping in a doctor-table button remain non-blocking observations.
- Parent reran both artifact verifiers successfully after final review: seven files in backend output and seven in explicit-mock output. Backend output excludes the fixture subtree; mock output contains its required sentinel.
